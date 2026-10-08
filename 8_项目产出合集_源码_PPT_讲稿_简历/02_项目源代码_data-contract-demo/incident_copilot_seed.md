# Incident Copilot 取证底稿（第八卷首项）

> 本件是第八卷第一篇实证底座，对应「LLM 辅助运行诊断」主线节点。
> 它**只做取证与底稿**，不写第八卷正文（正文待统一动笔，同第七卷 I 阶段做法）。

## 一、需求来源（先有需求，后有功能）

`⑦ Failure Explanation` 解释「单条 / 单类别 FAIL」。但在真实运行里，一次 Kestra
执行（`datacontract test`）往往**同时炸出多类失败**（或同类多实例）。若仍逐类别解释，
会得到 N 份互不相干的说明，**丢失「这是同一次执行、很可能同一根因」的相关性**。

真实需求由此产生：**把一次执行的失败批次 + Kestra 执行日志，聚合为一份结构化事故报告**，
区分四节——已确认事实 / 异常证据 / 潜在原因 / 修复建议。
它是 `⑦` 的升级形态（单条 FAIL 解释 → 一次事故 = 一批同类失败 + 日志聚合），
落在主线定义的合法位置之一：**运行诊断**（主线 = Contract 管数据 / Runtime 管 Contract
持续执行 / Governance 管 Contract 变化 / LLM 辅助 Governance 与运行诊断）。
**不偏题**：不做事故大屏 / 工单系统 / 知识库 / 图谱。

## 二、设计（复用既有节点，不重复造轮子）

新文件 `incident_copilot.py`，复用四个既有模块：

| 复用对象 | 来自 | 本模块用途 |
|---|---|---|
| `extract_rules` / `classify_failures` / `explain_failures` / `make_cache_key` / `ExplanationCache` / `DeterministicExplainer` / `LLMExplainer` | `failure_explainer.py`（⑦） | 确定性分类 + **五 key 缓存** + 一类一次解释；③ 潜在原因直接调 `explain_failures` |
| `AlertDeduplicator` / `build_brief` | `alert_dedup.py`（F） | 进程内去重单例；同一事故同窗口只发一次 |
| `REPAIR_GUIDANCE` / `build_locate_sql` / `generate_repair_orders` | `repair_order.py`（E） | ② 异常证据 + ④ 修复建议的确定性定位与指引 |
| `log_llm_call` / `mask_pii` | `llm_audit.py`（C） | 跨切面审计；事故事件记入同一审计日志 |

四个关键设计点：
1. **incident_id 内容寻址**（`make_incident_id`）：`sha256(execution_id|contract_version|排序后失败规则集合|窗口起点)[:12]`，前缀 `inc-`。
   同一次失败批次必得同一 ID（幂等），与规则候选 `copilot_`、⑦ 缓存键区分。
2. **四节报告**：① 已确认事实（确定性，无模型）② 异常证据（失败规则 + 定位交易 + 相关 Kestra 日志行）
   ③ 潜在原因（复用 ⑦ `explain_failures`，LLM 只看类别）④ 修复建议（确定性 `REPAIR_GUIDANCE` + 定位）。
3. **复用 F 去重**：进程内单例（`get_dedup`），同 `(execution_id, incident_id, 窗口)` 只在窗口内首次 `emit=True`。
4. **跨切面审计**：每次生成事故记一行 `INCIDENT: <id>` 到 `llm_audit.log`，PII 已脱敏。

## 三、四护栏（沿用第七卷语义）

- ① 不直接改生产契约：只读 `check_results` 与日志，产出报告，不碰 `financial_data_contract.yaml`。
- ② 不直接执行修复：修复建议是确定性指引 + 定位 SQL，执行权留给人工 / 变更单。
- ③ 输出必过确定性分类：所有 FAIL 先经 `classify_failures` 归类，LLM 只看类别不看数据行。
- ④ 版本可追溯：incident_id 内容寻址；潜在原因复用 ⑦ 五 key 缓存；报告含 `contract_version / prompt_version / model_version / incident_id`。

## 四、诚实边界（写第八卷须逐字写明）

- 演示环境**未直连 LLM**：③ 潜在原因用 `DeterministicExplainer` 基线，或经 `--manual-text` 回填网页端解释；不声称模型在线推断。
- Kestra 执行日志在演示中为**结构化镜像输入**（`sample_execution_log.json`）；生产中由 Kestra execution API / 任务日志提供，解析层（`parse_execution_log`）形态一致。
- 定位 SQL 经契约视图 `erp_transactions` 筛 `transaction_id` 再 JOIN `journal_entries`（同 E）；演示 offline 模式 `located=0`，PG 实跑需连库（同 E 边界）。
- 测试过程向共享 `failure_explanations.cache.jsonl` 与 `llm_audit.log` 写了取证条目，属预期证据产物。

## 五、测试实证（`test_incident_copilot.py`，离线 / 确定性，全 PASS）

```
T1 incident_id 内容寻址幂等
  [PASS] 相同输入两次得到同一 incident_id (inc-d2703ee177e6)
  [PASS] 失败规则集合不同 → 不同 incident_id
T2 四节报告齐全
  [PASS] 报告含 confirmed_facts / anomaly_evidence / potential_causes / repair_suggestions
  [PASS] 已确认事实解释 2 个失败类别（不含 passed）
  [PASS] 潜在原因 2 条 / 修复建议 2 条（每类别一条）
T3 异常证据抽取相关 Kestra 日志行
  [PASS] 日志摘录同时命中 amount 与 missing_support_flag
T4 潜在原因复用 ⑦ 缓存（一类一次）
  [PASS] 第一次 cache_hit 全 False；第二次全 True；incident_id 一致
T5 复用 F 去重：同窗口第二次 emit=False（suppressed>=1）
T6 诚实边界字段存在（llm_mode / kestra_log_source / locate_mode）
ALL INCIDENT TESTS PASSED
```

## 六、CLI 实跑（`incident_report.json` 已落盘）

```
INCIDENT_ID     : inc-96dfb5c864ac
EXECUTION_ID    : kestra-exec-20261004-001
CONTRACT_VERSION: 1.0.0
CATEGORIES      : 2
LOCATED_ROWS    : 0   （offline 模式，未连库，诚实标注）
CAUSES          : 2
REPAIRS         : 2
EMIT            : True (suppressed=0)
WROTE: incident_report.json
```

跨切面审计确认（`llm_audit.log` 末尾）：
```
INCIDENT: inc-96dfb5c864ac emit=True   ← CLI 产生的事故事件，已记入同一审计日志
```

## 七、新增 / 改动文件清单（均 untracked，待收尾统一 commit）

- `incident_copilot.py`（新建，核心模块）
- `test_incident_copilot.py`（新建，实证测试）
- `sample_execution_log.json`（新建，Kestra 结构化镜像输入）
- `incident_check_results.json`（新建，一次执行的两类失败样本）
- `incident_report.json`（新建，CLI 实跑证据）
- 复用：`failure_explainer.py` / `alert_dedup.py` / `repair_order.py` / `llm_audit.py`（未改动）

> 注：A–H 全部新代码 / 底稿仍 `untracked`（含本件）；git 收尾（统一 commit，避开 B 项证据
> commit `23421e0…`）待用户拍板，与 Incident Copilot 一并或之后处理。
