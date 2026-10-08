"""
③ 变更影响评估（Change Impact Assessment）
==========================================

需求来源（先有需求，后有功能）
------------------------------
V6 演进顺序里，改完一条契约规则必须回答："以前那 137 笔历史交易呢？"
即：候选契约（new）相对当前生产契约（old）改了某些规则后，
历史 erp_transactions 里有多少笔会从"通过"变成"不通过"？
这些 PASS->FAIL 的笔数不能悄无声息地放过，必须由 ② 独立审批人签字确认影响可接受，
才允许进入发布流程。这就是 ③ 的产出物：一份"契约变更影响评估报告"，出口是 ② 审批人签字。

本模块不重造 ②：它只负责"新旧规则 diff + 历史结果四分类 + 标注需审批的笔数"，
签字动作复用 erp_app_v6.py 的 contract_approver 审批链路。

诚实边界（🔵 规划落地的诚实标注）
---------------------------------
- 本模块不重新执行 SQL。生产里"旧版/候选版各跑一遍 72 项检查"是 datacontract-cli 的职责，
  跑出的两份 check-result 集合作为本模块输入；本模块只做 diff 与分类。
- 演示用样例结果集（sample_*_results.json）是等价构造，不是 PG 实跑；PG 实跑需连库。
- 出口"需审批人签字"是状态标记 + 待办占位，真正的签字调用在 erp_app_v6.py。
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CONTRACT_PREFIX = "cia-"
CATEGORIES = ("PASS->PASS", "PASS->FAIL", "FAIL->PASS", "FAIL->FAIL")


def load_rules(yaml_path: str) -> dict:
    """从契约 YAML 抽取规则元数据，rule_id = {model}.{field}.q{index}。

    返回 {rule_id: {"field", "model", "query", "mustBe", "severity", "description"}}。
    用于让 diff 出的变化规则可追溯到真实契约字段（而非凭空）。
    """
    import yaml  # 延迟导入；演示用 <Python安装目录> 解释器自带

    with open(yaml_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    rules: dict = {}
    for model, mdef in (doc.get("models") or {}).items():
        fields = mdef.get("fields") or {}
        for fname, fdef in fields.items():
            for i, q in enumerate(fdef.get("quality") or []):
                rid = f"{model}.{fname}.q{i}"
                severity = "error"
                desc = (q.get("description") or "").strip()
                if "warn" in desc.lower():
                    severity = "warning"
                rules[rid] = {
                    "model": model,
                    "field": fname,
                    "query": q.get("query") or q.get("check"),
                    "mustBe": q.get("mustBe"),
                    "severity": severity,
                    "description": desc,
                }
    return rules


def diff_rules(old_rules: dict, new_rules: dict) -> dict:
    """对比新旧规则集，返回 {added, removed, changed}。

    changed 的元素为 {rule_id, old, new}；仅在 query/mustBe/severity 有差异时计入。
    """
    added, removed, changed = [], [], []
    for rid in new_rules:
        if rid not in old_rules:
            added.append(rid)
        else:
            o, n = old_rules[rid], new_rules[rid]
            if (o.get("query") != n.get("query")
                    or o.get("mustBe") != n.get("mustBe")
                    or o.get("severity") != n.get("severity")):
                changed.append({"rule_id": rid, "old": o, "new": n})
    for rid in old_rules:
        if rid not in new_rules:
            removed.append(rid)
    return {"added": added, "removed": removed, "changed": changed}


def _index(results: list[dict]) -> dict:
    return {(r["transaction_id"], r["rule_id"]): r.get("status", "PASS") for r in results}


def classify(old_results: list[dict], new_results: list[dict]) -> dict:
    """核心：把新旧两份检查结果按 (transaction_id, rule_id) 对齐，做四分类。

    缺省视为 PASS（该规则未命中该笔交易）。
    返回 {overall, per_rule, flips_to_fail, transaction_count}。
    """
    old_map = _index(old_results)
    new_map = _index(new_results)
    keys = set(old_map) | set(new_map)

    overall = {c: 0 for c in CATEGORIES}
    per_rule: dict = {}
    flips_to_fail: set = set()

    for k in keys:
        txn, rid = k
        o = old_map.get(k, "PASS")
        n = new_map.get(k, "PASS")
        cat = f"{o}->{n}"
        overall[cat] += 1
        per_rule.setdefault(rid, {c: 0 for c in CATEGORIES})
        per_rule[rid][cat] += 1
        if cat == "PASS->FAIL":
            flips_to_fail.add(txn)

    return {
        "overall": overall,
        "per_rule": per_rule,
        "flips_to_fail": sorted(flips_to_fail),
        "transaction_count": len({k[0] for k in keys}),
    }


@dataclass
class ImpactAssessment:
    execution_id: str
    change_request_id: str
    old_version: str
    new_version: str
    contract_path: str = ""
    assessor: str = "system"
    results: dict = field(default_factory=dict)
    diff: dict = field(default_factory=dict)
    requires_approver_signoff: bool = False
    signoff: dict = field(default_factory=dict)
    timestamp: float = 0.0

    def to_report(self) -> dict:
        report = {
            "assessment_id": make_assessment_id(self.execution_id, self.change_request_id),
            "execution_id": self.execution_id,
            "change_request_id": self.change_request_id,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "contract_path": self.contract_path,
            "diff_rules": self.diff,
            "classification": self.results,
            "requires_approver_signoff": self.requires_approver_signoff,
            "signoff": self.signoff,
            "assessor": self.assessor,
            "timestamp": self.timestamp,
        }
        return report


def make_assessment_id(execution_id: str, change_request_id: str) -> str:
    h = hashlib.sha256(f"{execution_id}|{change_request_id}".encode("utf-8")).hexdigest()[:12]
    return CONTRACT_PREFIX + h


def build_impact_report(
    execution_id: str,
    change_request_id: str,
    old_results: list[dict],
    new_results: list[dict],
    old_version: str = "1.0.0",
    new_version: str = "1.1.0",
    old_rules: Optional[dict] = None,
    new_rules: Optional[dict] = None,
    contract_path: str = "",
    assessor: str = "system",
    timestamp: float = 0.0,
) -> dict:
    """组装一份完整的影响评估报告。"""
    results = classify(old_results, new_results)
    diff = {}
    if old_rules is not None and new_rules is not None:
        diff = diff_rules(old_rules, new_rules)
    # 出口闸门：只要存在 PASS->FAIL，就要求 ② 独立审批人签字
    requires = len(results["flips_to_fail"]) > 0
    signoff = {
        "required": requires,
        "role": "contract_approver",  # 复用 ② 角色
        "rule": "requested_by != approved_by",  # 复用 ② 防自审批
        "signed_by": None,
        "signed_at": None,
        "status": "PENDING" if requires else "NOT_REQUIRED",
    }
    assessment = ImpactAssessment(
        execution_id=execution_id,
        change_request_id=change_request_id,
        old_version=old_version,
        new_version=new_version,
        contract_path=contract_path,
        assessor=assessor,
        results=results,
        diff=diff,
        requires_approver_signoff=requires,
        signoff=signoff,
        timestamp=timestamp,
    )
    return assessment.to_report()


def main_cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="③ 变更影响评估")
    p.add_argument("--old-results", required=True, help="旧版契约跑出的检查结果 JSON")
    p.add_argument("--new-results", required=True, help="候选版契约跑出的检查结果 JSON")
    p.add_argument("--old-yaml", default=None, help="可选：旧版契约 YAML（用于 diff 规则）")
    p.add_argument("--new-yaml", default=None, help="可选：候选版契约 YAML")
    p.add_argument("--execution-id", default="exec-demo")
    p.add_argument("--change-request-id", default="CCR99999")
    p.add_argument("--old-version", default="1.0.0")
    p.add_argument("--new-version", default="1.1.0")
    p.add_argument("-o", "--output", default="impact_report.json")
    p.add_argument("--operator", default="system")
    a = p.parse_args()

    old_results = json.loads(Path(a.old_results).read_text(encoding="utf-8"))
    new_results = json.loads(Path(a.new_results).read_text(encoding="utf-8"))
    old_rules = load_rules(a.old_yaml) if a.old_yaml else None
    new_rules = load_rules(a.new_yaml) if a.new_yaml else None

    report = build_impact_report(
        execution_id=a.execution_id,
        change_request_id=a.change_request_id,
        old_results=old_results,
        new_results=new_results,
        old_version=a.old_version,
        new_version=a.new_version,
        old_rules=old_rules,
        new_rules=new_rules,
        contract_path=a.new_yaml or "",
        assessor=a.operator,
    )
    Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[③] assessment_id={report['assessment_id']}")
    print(f"[③] 四分类={report['classification']['overall']}")
    print(f"[③] PASS->FAIL 笔数={len(report['classification']['flips_to_fail'])} -> 需审批={report['requires_approver_signoff']}")
    print(f"[③] 报告已写出: {a.output}")


if __name__ == "__main__":
    main_cli()
