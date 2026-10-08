# Failure Explanation 取证底稿（第七卷 ⑦，Day 4/5 范畴）

> 本文件是 Day 2 之后 ⑦ Failure Explanation 的取证底稿，供统一写第七卷正文时使用。
> 第七卷正文当前只写到 Day 2 前半，本文件内容属于「后半补写」，尚未进入 LLM卷.md 正文。

## 一、设计约束（来自第七卷 9.3 / 整体思路第十四节）

- 契约先做**确定性分类**：把 datacontract-cli 的 FAIL 结果规范化为 `(rule_id, error_signature)` 类别。
- LLM **只解释已经确定的异常类别**，不参与判断「到底哪条数据违规」。
- 一类一次解释 + 缓存；缓存 key 五项：
  `contract_version + rule_id + error_signature + prompt_version + model_version`
  任一变化 → 旧解释立即失效。

## 二、模块 `failure_explainer.py`（新建）

职责分解，刻意让「发现 FAIL」与「解释 FAIL」解耦：

1. `extract_rules(yaml)`：从契约确定性派生每条 quality 规则的 `rule_id`，格式
   `{model}.{field}.q{index}`（例 `erp_transactions.amount.q0`）、`description`、`mustBe`。
2. `classify_failures(rules, check_results, contract_version)`：把规范化
   `check_results`（字段 `[{rule_id, actual_count, passed}]`）聚成类别；
   `passed=True` 项忽略；`error_signature` 默认取类别级指纹 `mustBe={must_be}`
   （**不含 actual_count**，保证「同一规则只要 FAIL，解释命中同一缓存」）。
3. `ExplanationCache`（JSONL `failure_explanations.cache.jsonl`）：五 key → 解释文本。
4. `Explainer` 抽象：
   - `DeterministicExplainer`：离线、可复现、**不调模型**，仅基于结构信息生成「结构级」解释；
     证明解释动作本身不需要 LLM，LLM 只是在类别已知后补充业务语义。
   - `LLMExplainer`：prompt **只描述类别、不给任何具体数据行**，因此 LLM 无从「判断哪条数据违规」；
     本 demo 不直连模型（网页对话端代码层抓不到），用 `from_text` 回填，或未来接 API 传 `fetcher`。
5. `explain_failures(...)`：聚类 → 逐类查缓存 → 未命中调解释器 → 写缓存 → 返回报告。

## 三、真实 FAIL 证据（不是模拟）

演示库当前 12 条 quality 规则全通过。为取得真实 FAIL，向 `erp_transactions` 注入一条
`amount=6000000` 脏数据（TRX10024），其余字段不动。**选择 amount 的原因见第五节诚实边界。**

SQL 直算确认：
```
remaining_amount_violations : 1   (ABS(amount) > 5000000)
```

datacontract test 真实输出（节选，逐字）：
```
│ failed │ Quality Check        │ amount               │ Actual               │
│        │                      │                      │ custom_sql(amount)   │
```
即 datacontract-cli 端到端真实报出 amount 的 Quality Check 为 failed，Actual 来自 `custom_sql(amount)`。

## 四、聚类与缓存验证（实测）

规范化输入 `check_results.json`：
```json
[{"rule_id":"erp_transactions.amount.q0","actual_count":1,"passed":false}]
```

RUN 1（首次，期望 CACHE_HITS=0）：
```
CONTRACT_VERSION: 1.0.0   PROMPT_VERSION: fx-v1   MODEL_VERSION: deterministic-baseline
FAILURES: 1   CATEGORIES: 1   CACHE_HITS: 0
```

RUN 2（同类别重跑，期望 CACHE_HITS=1，证明「一类一次」）：
```
FAILURES: 1   CATEGORIES: 1   CACHE_HITS: 1
```

契约版本隔离（`contract_version=1.0.1`，期望 CACHE_HITS=0）：
```
CACHE_HITS(contract_version=1.0.1): 0
CACHE_HITS(model_version 变化): 0
```

缓存文件 `failure_explanations.cache.jsonl` 实测含三条不同 key 记录，分别对应
`1.0.0/fx-v1/deterministic-baseline`、`1.0.1/...`、`1.0.0/.../deterministic-baseline-OTHER`，
证明五项 key 各自独立生效。

生成的解释文本（deterministic 基线，逐字）：
```
【规则 erp_transactions.amount.q0】交易金额（允许负数）。该字段要求满足 mustBe=0，即不允许
出现约束之外的值。当前检测到 1 条违反。这意味着存在不满足该字段业务约束的交易记录，可能对应
录入错误、流程越界或系统集成偏差，应结合契约变更单（CCR）流程追溯责任人并定位根因。
```

## 五、诚实边界（写正文必须写明）

1. **演示库 11/12 质量规则在 DB 层不可违反。** `journal_entries` 表对 12 个契约字段
   全部加了 check 约束（`chk_journal_approval_level` 等），其中 11 个（范围/枚举类）直接禁止契约
   禁止的值。因此这些字段在 DB 写入路径上**物理上无法产生契约 FAIL**——这也解释了为何
   全通过态下 datacontract 的 Quality Check 全部 passed。只有 `amount`（`chk_journal_amount`
   仅要求 `>0`，不阻止超过 500 万）可在不破坏表约束前提下制造真实 FAIL。
   → 这不是缺陷，是 Day 1「后端强制」的延续，且提示：契约的价值跨引擎（datacontract 还查
   schema/presence/type/物理类型），且 journal check 只覆盖 DB 写入路径，其他入口未必有。
2. **DeterministicExplainer 仅生成结构级解释**；业务语义解释需 LLM，本 demo 用 `from_text`
   回填，未直连模型（网页对话端限制，与 C 项审计日志同一边界）。
3. **仿真 FAIL 输入**：除 amount 这条是真实脏数据驱动外，若需演示「多类别聚类」，其余字段因
   journal check 无法造脏，须用仿真规范化输入，且必须标注为仿真，不得冒充真实违规。

## 六、与第七卷附录的对应

- 附录 19「Failure Explanation」：本轮由 ⏳ 转为 ✅（实证已就绪，待写正文）。
- 设计满足 9.3「确定性分类 → LLM 只解释已确定类别 → 一次解释加缓存 → 不让 LLM 判断违规」全部要点。
