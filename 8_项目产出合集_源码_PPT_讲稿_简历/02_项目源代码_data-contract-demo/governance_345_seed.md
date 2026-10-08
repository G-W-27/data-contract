# ③④⑤ 治理能力 取证底稿（第八卷）

> 状态：✅ 实证已就绪、待写正文（与第七卷 A–H / Incident Copilot 同款取证做法）
> 代码位置：`data-contract-demo/` 下 `change_impact_assessment.py` / `contract_version_rollback.py` / `near_threshold_interceptor.py` + `test_governance_345.py` + 样例与实跑证据。
> 卷号口径：第 7 卷已完整交付；第八卷 = 真正的新工作，Incident Copilot 打头，③④⑤ 紧随。②③④⑤ 均落在主线「Governance 管契约变化」上，未偏题。

---

## 0. 为什么现在写（需求来源，先有需求后有功能）

第六卷第五章 §5.3 / §5.26 原话："顺序依据 V6：① → ② → ③（与②咬合）→ ④ → ⑤ → ⑥ → ⑦⑨。本轮只做 ①② 与 ⑥⑦⑨，③④⑤ 是下一轮。"

用户于 2026-10-04 明确指令"③④⑤ 治理能力这个写了吗，如果没有，先写"，即把上一轮挂起的 ③④⑤ 正式点名为第八卷下一动作。三项均有明确需求来源，不凭空：

- **③ 变更影响评估**：改完一条规则必须回答"以前那 137 笔历史交易呢？"——新旧契约各跑一遍 72 项检查，出 PASS→FAIL 四类，出口是 ② 审批人签字。
- **④ 契约版本回退**：坏规则发布后需回到上一个好版本；回退的是 Contract 版本指针不是业务数据，且回退动作本身走 ① 变更单 + 审计。
- **⑤ 事中拦截**：提交前用 near_threshold 提示一句客观政策事实，**不早于 ①、绝不拦截**。

---

## 1. 与既有主线的衔接（不重造）

| 项 | 复用对象 | 复用点 |
|----|----------|--------|
| ②（已落地，A 项） | `erp_app_v6.py` | `contract_change_requests` 表、`contract_approver` 角色、`requested_by != approved_by` 防自审批、防重复提交 |
| ③ 出口 | ② | 签字动作复用 contract_approver 审批链路；本模块只产出"需签字"状态，不重造审批 |
| ④ | ① + ② | `current_version / target_version / change_request_id` 概念与 erp_app_v6 一致；回退生成一条待 ② 审批的变更单 |
| ⑤ | ① | 仅在"契约变更可追溯就绪"后启用；提示归属到 ① 变更单语境 |

契约真实字段已核对：版本 `1.0.0`；`amount` 规则 `ABS(amount) > 5000000 mustBe 0`；`approval_level` `NOT IN (1,2,3,4) mustBe 0`。③ 的 diff 直接从该 YAML 抽取规则元数据。

---

## 2. ③ 变更影响评估（change_impact_assessment.py）

**产出物**：一份"契约变更影响评估报告"——新旧规则 diff + 历史结果四分类 + PASS→FAIL 笔数清单 + ② 签字闸门。

**核心函数**
- `load_rules(yaml)`：从契约抽取 `rule_id={model}.{field}.q{idx}` 的元数据（query/mustBe/severity/description）。
- `diff_rules(old, new)`：返回 added/removed/changed（仅在 query/mustBe/severity 有差异时计入）。
- `classify(old_results, new_results)`：按 (transaction_id, rule_id) 对齐，四分类；缺省视为 PASS；收集 flips_to_fail。
- `build_impact_report(...)`：组装报告，`requires_approver_signoff = len(flips_to_fail) > 0`，signoff 字段复用 ② 角色与防自审批规则。

**诚实边界**：不重新执行 SQL（datacontract-cli 负责跑新旧两份检查，结果集作输入）；演示结果集为等价构造，非 PG 实跑；签字是状态标记，真正签字在 erp_app_v6.py。

---

## 3. ④ 契约版本回退（contract_version_rollback.py）

**产出物**：版本时间线 + 回退动作（新指针 + 待审批变更单）。

**核心类 `VersionStore`**
- `record_publish(version_id, yaml_path, git_tag, change_request_id, operator)`：登记发布并置 is_current。
- `current_version()`：返回当前指针。
- `rollback_to(target_version_id, operator, change_request_id)`：移动 is_current 到新记录，新记录 `yaml_path` 指向目标版本内容、`kind=rollback`、`change_request_id` 是一条新的 ① 变更单；**不修改任何业务表**。

**诚实边界**：演示用 `contract_versions.json` 作存储，生产应落契约仓库 + Git tag；回退只移指针，业务数据零改动；真正送审/发布在 erp_app_v6.py。

---

## 4. ⑤ 事中拦截 / near_threshold 提示（near_threshold_interceptor.py）

**产出物**：提示清单（hints）——绝不阻断。

**核心函数**
- `check_near_threshold(candidate, historical_values, band_pct=0.05)`：候选含新阈值，历史样本落在阈值 ±5% 带内则生成一条客观提示。
- `intercept(candidates, historical_values, traceability_ready, band_pct)`：批量入口；`traceability_ready=False` 时返回 `enabled=False` 空提示（不早于 ①）；正常返回 hints + note"仅提示，不拦截"。

**诚实边界**：advisory only，返回 dict 不抛异常、不改数据；band 是工程约定非内控规则；演示历史样本为等价构造。

---

## 5. 测试与实跑证据（原文）

### 5.1 单元测试 `test_governance_345.py`（8/8 PASS，项目解释器 `python`）
```
T1 ③ 四分类 + 签字闸门
  [PASS] PASS->PASS=4  [PASS] PASS->FAIL=2  [PASS] FAIL->PASS=0  [PASS] FAIL->FAIL=2
  [PASS] 需关注笔数=['T002', 'T005']
T2 ③ 从真实契约 diff 变化规则
  [PASS] amount.q0 被识别为变化规则 (['erp_transactions.amount.q0'])
T3 ③ 影响报告 assembly + 签字闸门
  [PASS] 存在 PASS->FAIL -> 需 ② 签字
  [PASS] 签字角色复用 ② contract_approver
  [PASS] 复用 ② 防自审批
  [PASS] 未签时状态 PENDING
  [PASS] assessment_id 内容寻址 (cia-082959f21d1d)
T4 ④ 发布→回退只移指针、不碰业务数据
  [PASS] 当前指针=v1.1.0  [PASS] 回退生成一条新指针记录
  [PASS] 新记录 kind=rollback  [PASS] 回退指向目标版本内容
  [PASS] 回退动作本身是一条变更单(①)  [PASS] 当前指针已移到回退记录  [PASS] is_current=True
T5 ④ 回退不存在版本应抛错 -> ValueError
T6 ⑤ 邻近提示计数正确（①就绪）
  [PASS] enabled=True  [PASS] 命中 1 条规则提示  [PASS] 邻近 2 笔
  [PASS] 邻近示例=['T001', 'T002']  [PASS] note 声明仅提示不拦截
T7 ⑤ ①未就绪时不启用 -> enabled=False, 空提示, reason 指明缺 ①
T8 ⑤ 极端候选也不抛异常（只提示）
结果: 全部 PASS (8/8)
```

### 5.2 CLI 实跑
```
[③] assessment_id=cia-082959f21d1d
[③] 四分类={'PASS->PASS': 4, 'PASS->FAIL': 2, 'FAIL->PASS': 0, 'FAIL->FAIL': 2}
[③] PASS->FAIL 笔数=2 -> 需审批=True
[③] 报告已写出: impact_report.json

[④] 已发布并设为当前: v1.0.0
[④] 已发布并设为当前: v1.1.0
[④] 已回退: 新指针 cvr-9a97284f5b 指向 v1.0.0 的内容 (kind=rollback, 待②审批)
[④] 当前版本: cvr-9a97284f5b (rollback)

[⑤] enabled=True hint_count=1 -> near_threshold_hints.json
```

### 5.3 产出证据文件
- `impact_report.json`（③ 报告：四分类 + flips_to_fail + ② 签字闸门）
- `contract_versions_demo.json`（④ 时间线：publish×2 + rollback×1，当前指针指向回退记录）
- `near_threshold_hints.json`（⑤ 提示：amount 新阈值 800 万邻近 2 笔）
- 样例：`sample_impact_old_results.json` / `sample_impact_new_results.json` / `sample_transactions_near_threshold.json` / `sample_candidates_near_threshold.json`

---

## 6. 与第七卷附录 21 的对应

第七卷附录 21 原标 🔵（规划）。本底稿将 ③ ④ ⑤ 由 🔵 转 ✅（实证已就绪、待写正文）。仍为"治理治理能力"主线，未引入页面/审批流/中间件等偏题产出物。

---

## 7. 待写正文时引用的关键表述（中性、可复核）

- ③："契约规则变更后，对历史交易做新旧结果四分类，凡出现 PASS→FAIL 的笔数必须由独立审批人签字确认影响可接受，方可进入发布。"
- ④："契约版本回退只移动 Contract 版本指针并登记一条回退变更单（走既有变更追溯与审批），不修改任何业务数据。"
- ⑤："提交候选契约变更前，对阈值邻近的历史交易给出客观提示；该提示不早于契约变更追溯链路启用，且仅提示、不拦截。"
