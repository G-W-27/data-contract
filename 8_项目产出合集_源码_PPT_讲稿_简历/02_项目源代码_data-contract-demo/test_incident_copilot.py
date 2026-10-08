"""
Incident Copilot 实证测试（不调模型、不连库、不引 Redis）。

覆盖：
  T1 incident_id 内容寻址幂等：相同输入两次 → 同一 incident_id
  T2 四节报告齐全：confirmed_facts / anomaly_evidence / potential_causes / repair_suggestions
  T3 异常证据抽取到失败规则字段名相关的 Kestra 日志行
  T4 潜在原因复用 ⑦ 缓存：连续两次调用，第二次 cache_hit=True（一类一次）
  T5 复用 F 去重：同窗口第二次调用 incident_id 相同 → emit=False（被抑制）
  T6 诚实边界字段存在（llm_mode / kestra_log_source / locate_mode）
"""

from __future__ import annotations

import json
from pathlib import Path

from incident_copilot import (
    build_incident_report,
    make_incident_id,
    parse_execution_log,
    relevant_log_lines,
)
from failure_explainer import ExplanationCache

YAML = "financial_data_contract.yaml"
LOG = json.loads(Path("sample_execution_log.json").read_text(encoding="utf-8"))
CHECK = json.loads(Path("incident_check_results.json").read_text(encoding="utf-8"))
EXEC_ID = "kestra-exec-20261004-001"
CV = "1.0.0"
PV = "inc-v1"
MV = "deterministic-baseline"

FAILS = 0


def check(cond: bool, name: str) -> None:
    global FAILS
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILS += 1
    print(f"  [{status}] {name}")


def test_idempotent_id() -> None:
    print("T1 incident_id 内容寻址幂等")
    rid = [c["rule_id"] for c in CHECK if not c["passed"]]
    a = make_incident_id(EXEC_ID, CV, rid, 1000)
    b = make_incident_id(EXEC_ID, CV, rid, 1000)
    check(a == b, f"相同输入两次得到同一 incident_id ({a})")
    c = make_incident_id(EXEC_ID, CV, ["other.rule.q0"], 1000)
    check(a != c, "失败规则集合不同 → 不同 incident_id")


def test_four_sections() -> None:
    print("T2 四节报告齐全")
    rep = build_incident_report(
        EXEC_ID, CHECK, parse_execution_log(LOG), YAML, PV, MV, now=2000.0
    )
    for sec in ("confirmed_facts", "anomaly_evidence", "potential_causes", "repair_suggestions"):
        check(sec in rep, f"报告含 {sec}")
    cf = rep["confirmed_facts"]
    check(cf["explained_categories"] == 2, "已确认事实解释 2 个失败类别（不含 passed）")
    check(len(rep["potential_causes"]) == 2, "潜在原因 2 条（每类别一条）")
    check(len(rep["repair_suggestions"]) == 2, "修复建议 2 条（每类别一条）")


def test_log_extract() -> None:
    print("T3 异常证据抽取相关 Kestra 日志行")
    rep = build_incident_report(
        EXEC_ID, CHECK, parse_execution_log(LOG), YAML, PV, MV, now=2000.0
    )
    excerpt = rep["anomaly_evidence"]["kestra_log_excerpt"]
    hit_amount = any("amount" in line.lower() for line in excerpt)
    hit_support = any("missing_support_flag" in line.lower() for line in excerpt)
    check(hit_amount and hit_support, "日志摘录同时命中 amount 与 missing_support_flag")
    check(len(rep["anomaly_evidence"]["failing_rules"]) == 2, "失败规则列表 = 2")


def test_cache_reuse() -> None:
    print("T4 潜在原因复用 ⑦ 缓存（一类一次）")
    import tempfile, os
    tmp = os.path.join(tempfile.gettempdir(), "inc_cache_iso.jsonl")
    if os.path.exists(tmp):
        os.remove(tmp)
    cache = ExplanationCache(tmp)
    kw = dict(execution_id=EXEC_ID, check_results=CHECK,
              execution_log=parse_execution_log(LOG), yaml_path=YAML,
              prompt_version=PV, model_version=MV, now=3000.0, cache=cache)
    r1 = build_incident_report(**kw)
    r2 = build_incident_report(**kw)
    hits1 = [c["cache_hit"] for c in r1["potential_causes"]]
    hits2 = [c["cache_hit"] for c in r2["potential_causes"]]
    check(all(not h for h in hits1), "第一次调用 cache_hit 全 False（生成并写缓存）")
    check(all(h for h in hits2), "第二次调用 cache_hit 全 True（命中 ⑦ 缓存）")
    check(r1["incident_id"] == r2["incident_id"], "两次 incident_id 一致（幂等）")


def test_f_dedup() -> None:
    print("T5 复用 F 去重：同窗口第二次 emit=False")
    kw = dict(execution_id=EXEC_ID, check_results=CHECK,
              execution_log=parse_execution_log(LOG), yaml_path=YAML,
              prompt_version=PV, model_version=MV, now=4000.0)
    r1 = build_incident_report(**kw)
    r2 = build_incident_report(**kw)
    check(r1["emit"]["emit"] is True, "第一次 emit=True（窗口内首次）")
    check(r2["emit"]["emit"] is False, "第二次 emit=False（同窗口同类被抑制）")
    check(r2["emit"]["suppressed_count"] >= 1, "被抑制计数 >= 1")


def test_boundary() -> None:
    print("T6 诚实边界字段存在")
    rep = build_incident_report(
        EXEC_ID, CHECK, parse_execution_log(LOG), YAML, PV, MV, now=5000.0
    )
    b = rep["boundary"]
    check("llm_mode" in b and "kestra_log_source" in b and "locate_mode" in b,
          "boundary 含 llm_mode / kestra_log_source / locate_mode")
    check(b["locate_mode"] == "offline", "offline 模式（未连库）正确标注")


def main() -> None:
    print("=" * 64)
    print("Incident Copilot 实证测试（离线 / 确定性）")
    print("=" * 64)
    test_idempotent_id()
    test_four_sections()
    test_log_extract()
    test_cache_reuse()
    test_f_dedup()
    test_boundary()
    print("=" * 64)
    if FAILS == 0:
        print("ALL INCIDENT TESTS PASSED")
    else:
        print(f"{FAILS} TEST(S) FAILED")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
