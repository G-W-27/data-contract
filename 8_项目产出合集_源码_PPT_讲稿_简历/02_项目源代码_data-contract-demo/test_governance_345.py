"""③ ④ ⑤ 治理能力 实证测试（用项目解释器 python 运行）。

断言重点：
- ③ 四分类正确、PASS->FAIL 触发 ② 审批人签字闸门。
- ③ diff_rules 能从真实契约字段识别出变化的规则。
- ④ 发布/回退只移动指针、不碰业务数据；回退动作本身生成待审批变更单。
- ⑤ 仅提示不拦截；① 未就绪时不启用；邻近带计数正确。
"""

import json
import os
import tempfile

from change_impact_assessment import (
    build_impact_report, classify, diff_rules, load_rules,
)
from contract_version_rollback import VersionStore, make_rollback_id
from near_threshold_interceptor import intercept, check_near_threshold

HERE = os.path.dirname(os.path.abspath(__file__))
YAML = os.path.join(HERE, "financial_data_contract.yaml")
OLD = os.path.join(HERE, "sample_impact_old_results.json")
NEW = os.path.join(HERE, "sample_impact_new_results.json")
HIST = os.path.join(HERE, "sample_transactions_near_threshold.json")
CANDS = os.path.join(HERE, "sample_candidates_near_threshold.json")

_fail = []


def check(cond: bool, msg: str) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {msg}")
    if not cond:
        _fail.append(msg)


def load(p):
    return json.load(open(p, encoding="utf-8"))


# ---------------------------------------------------------------- ③
def test_classify_four_categories() -> None:
    print("T1 ③ 四分类 + 签字闸门")
    old = load(OLD)
    new = load(NEW)
    r = classify(old, new)
    ov = r["overall"]
    check(ov["PASS->PASS"] == 4, f"PASS->PASS=4 (实得 {ov['PASS->PASS']})")
    check(ov["PASS->FAIL"] == 2, f"PASS->FAIL=2 (实得 {ov['PASS->FAIL']})")
    check(ov["FAIL->PASS"] == 0, f"FAIL->PASS=0 (实得 {ov['FAIL->PASS']})")
    check(ov["FAIL->FAIL"] == 2, f"FAIL->FAIL=2 (实得 {ov['FAIL->FAIL']})")
    check(set(r["flips_to_fail"]) == {"T002", "T005"}, f"需关注笔数={r['flips_to_fail']}")


def test_diff_rules_from_yaml() -> None:
    print("T2 ③ 从真实契约 diff 变化规则")
    old_rules = load_rules(YAML)
    # 构造一份"候选版"：把 amount 阈值从 5,000,000 改到 3,000,000
    import copy
    import yaml
    doc = yaml.safe_load(open(YAML, encoding="utf-8"))
    doc["models"]["erp_transactions"]["fields"]["amount"]["quality"][0]["query"] = (
        "SELECT COUNT(*) FROM erp_transactions WHERE ABS(amount) > 3000000"
    )
    new_yaml = os.path.join(tempfile.gettempdir(), "candidate_contract.yaml")
    yaml.safe_dump(doc, open(new_yaml, "w", encoding="utf-8"), allow_unicode=True)
    new_rules = load_rules(new_yaml)
    d = diff_rules(old_rules, new_rules)
    changed_ids = [c["rule_id"] for c in d["changed"]]
    check("erp_transactions.amount.q0" in changed_ids, f"amount.q0 被识别为变化规则 ({changed_ids})")


def test_impact_report_signoff_gate() -> None:
    print("T3 ③ 影响报告 assembly + 签字闸门")
    rep = build_impact_report(
        execution_id="exec-demo", change_request_id="CCR99999",
        old_results=load(OLD), new_results=load(NEW),
        old_version="1.0.0", new_version="1.1.0",
        old_rules=load_rules(YAML), new_rules=load_rules(YAML),
    )
    check(rep["requires_approver_signoff"] is True, "存在 PASS->FAIL -> 需 ② 签字")
    check(rep["signoff"]["role"] == "contract_approver", "签字角色复用 ② contract_approver")
    check(rep["signoff"]["rule"] == "requested_by != approved_by", "复用 ② 防自审批")
    check(rep["signoff"]["status"] == "PENDING", "未签时状态 PENDING")
    check(rep["assessment_id"].startswith("cia-"), f"assessment_id 内容寻址 ({rep['assessment_id']})")


# ---------------------------------------------------------------- ④
def test_version_publish_and_rollback() -> None:
    print("T4 ④ 发布→回退只移指针、不碰业务数据")
    store_path = os.path.join(tempfile.gettempdir(), "contract_versions_test.json")
    if os.path.exists(store_path):
        os.remove(store_path)
    s = VersionStore(store_path)
    s.record_publish("v1.0.0", "financial_data_contract.yaml", "v1.0.0",
                     "CCR00001", "E001", note="初始发布")
    s.record_publish("v1.1.0", "candidate_contract.yaml", "v1.1.0",
                     "CCR00002", "E001", note="收紧金额阈值")
    cur = s.current_version()
    check(cur["version_id"] == "v1.1.0", f"当前指针=v1.1.0 (实得 {cur['version_id']})")
    before = len(s.entries)
    rb = s.rollback_to("v1.0.0", "E002", "CCR00003", note="回退坏阈值")
    after = len(s.entries)
    check(after == before + 1, "回退生成一条新指针记录")
    check(rb["kind"] == "rollback", "新记录 kind=rollback")
    check(rb["yaml_path"] == "financial_data_contract.yaml", "回退指向目标版本内容")
    check(rb["change_request_id"] == "CCR00003", "回退动作本身是一条变更单(①)")
    cur2 = s.current_version()
    check(cur2["version_id"] == rb["version_id"], "当前指针已移到回退记录")
    check(cur2["is_current"] is True, "回退记录 is_current=True")


def test_rollback_unknown_raises() -> None:
    print("T5 ④ 回退不存在版本应抛错")
    store_path = os.path.join(tempfile.gettempdir(), "contract_versions_test2.json")
    if os.path.exists(store_path):
        os.remove(store_path)
    s = VersionStore(store_path)
    s.record_publish("v1.0.0", "x.yaml", "v1.0.0", "CCR1", "E001")
    raised = False
    try:
        s.rollback_to("v9.9.9", "E002", "CCR2")
    except ValueError:
        raised = True
    check(raised, "目标版本不存在 -> ValueError")


# ---------------------------------------------------------------- ⑤
def test_intercept_hints() -> None:
    print("T6 ⑤ 邻近提示计数正确（①就绪）")
    cands = load(CANDS)
    hist = load(HIST)
    res = intercept(cands, hist, traceability_ready=True)
    check(res["enabled"] is True, "①就绪 -> 启用")
    check(res["hint_count"] == 1, f"命中 1 条规则提示 (实得 {res['hint_count']})")
    hint = res["hints"][0]
    check(hint["near_count"] == 2, f"邻近 2 笔 (实得 {hint['near_count']})")
    check(set(hint["near_examples"]) == {"T001", "T002"}, f"邻近示例={hint['near_examples']}")
    check("仅提示" in res["note"] and "不拦截" in res["note"], "note 声明仅提示不拦截")


def test_intercept_disabled_without_traceability() -> None:
    print("T7 ⑤ ①未就绪时不启用")
    res = intercept(load(CANDS), load(HIST), traceability_ready=False)
    check(res["enabled"] is False, "未就绪 -> enabled=False")
    check(res["hints"] == [], "未就绪 -> 空提示")
    check("①" in res["reason"], "reason 指明缺 ①")


def test_intercept_never_blocks() -> None:
    print("T8 ⑤ 极端候选也不抛异常（只提示）")
    extreme = [{"rule_id": "x.y.q0", "field": "amount", "value_column": "amount",
                "new_threshold": 0}]  # 阈值 0 不应导致崩溃
    hist = load(HIST)
    res = intercept(extreme, hist, traceability_ready=True)
    check(isinstance(res, dict), "返回 dict 不抛异常")
    check("hints" in res, "结构含 hints 键")


def main() -> None:
    test_classify_four_categories()
    test_diff_rules_from_yaml()
    test_impact_report_signoff_gate()
    test_version_publish_and_rollback()
    test_rollback_unknown_raises()
    test_intercept_hints()
    test_intercept_disabled_without_traceability()
    test_intercept_never_blocks()
    print("=" * 60)
    if _fail:
        print(f"结果: {len(_fail)} 项 FAIL")
        for m in _fail:
            print("  -", m)
        raise SystemExit(1)
    print("结果: 全部 PASS (8/8)")


if __name__ == "__main__":
    main()
