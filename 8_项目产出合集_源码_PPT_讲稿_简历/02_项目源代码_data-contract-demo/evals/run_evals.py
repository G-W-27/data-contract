"""Day 2 · Contract Copilot Evals 回归执行器

它做什么：
1. 把 evals/raw/ 下的模型原始返回重放进两道闸门（离线回放，不调用模型、不联网）。
2. 逐条比对「闸门结果」与 cases.json 里记录的 expect_gate。
3. 重算 RULE_ID 并与 expect_rule_id 比对 —— 内容寻址必须可复现，
   一旦不一致说明确定性管道被改动过。
4. 统计「业务上必须拒绝、但闸门放行」的条数 —— 这是闸门缺口，不是执行器的失败。

它不做什么：
- 不调用模型（本评测集是取证记录 + 闸门回归，不是模型精度的统计测量）。
- 不生成 candidate / diff，不触碰 financial_data_contract.yaml。

退出码：0 = 全部与记录一致；1 = 出现偏差（需要人工复核）。

用法：
    python evals\\run_evals.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from contract_rule_schema import validate_rule_json  # noqa: E402
from contract_yaml_diff import rule_signature, validate_target_fields  # noqa: E402
from llm_rule_parser import strip_code_fence  # noqa: E402

CASES_PATH = HERE / "cases.json"
CONTRACT_PATH = ROOT / "financial_data_contract.yaml"

MUST_REJECT = "MUST_REJECT"


def read_raw(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def run_case(case: dict) -> dict:
    """把一条原始返回送进两道闸门，返回实际结果。"""
    raw_path = HERE / case["raw"]
    text, stripped = strip_code_fence(read_raw(raw_path))

    result = {"fence_stripped": stripped, "rule_id": None}

    try:
        rule = json.loads(text)
    except json.JSONDecodeError as exc:
        result.update(
            gate="GATE1_REJECT",
            msg=f"不是合法 JSON：{exc}",
        )
        return result

    try:
        validate_rule_json(rule)
    except ValueError as exc:
        result.update(gate="GATE1_REJECT", msg=str(exc).splitlines()[0])
        return result

    contract_text = CONTRACT_PATH.read_text(encoding="utf-8")
    try:
        validate_target_fields(contract_text, rule)
    except ValueError as exc:
        result.update(gate="GATE2_REJECT", msg=str(exc).splitlines()[0])
        return result

    result.update(gate="PASS", msg="", rule_id=f"copilot_{rule_signature(rule)}")
    return result


def main() -> int:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]

    print(f"Contract   : {CONTRACT_PATH.name}")
    print(f"Prompt     : {data['meta']['prompt_version']}")
    print(f"用例总数   : {len(cases)}")
    print()

    header = f"{'ID':<6}{'闸门':<14}{'预期':<14}{'RULE_ID':<24}{'ID一致':<8}{'语义判定'}"
    print(header)
    print("-" * len(header))

    mismatches: list[str] = []
    gap_ids: list[str] = []
    gate_reject_ids: list[str] = []

    for case in cases:
        actual = run_case(case)
        expect_gate = case["expect_gate"]
        expect_id = case["expect_rule_id"]

        gate_ok = actual["gate"] == expect_gate
        id_ok = (actual["rule_id"] == expect_id) if actual["rule_id"] or expect_id else (
            actual["rule_id"] == expect_id
        )

        if not gate_ok:
            mismatches.append(f"{case['id']}: 闸门 {actual['gate']} != 预期 {expect_gate}")
        if not id_ok:
            mismatches.append(
                f"{case['id']}: RULE_ID {actual['rule_id']} != 预期 {expect_id}"
            )

        if actual["gate"] != "PASS":
            gate_reject_ids.append(case["id"])
        if case["verdict"] == MUST_REJECT and actual["gate"] == "PASS":
            gap_ids.append(case["id"])

        print(
            f"{case['id']:<6}"
            f"{actual['gate']:<14}"
            f"{expect_gate:<14}"
            f"{str(actual['rule_id'] or '-'):<24}"
            f"{('OK' if id_ok else 'DIFF'):<8}"
            f"{case['verdict']}"
        )
        if actual["msg"]:
            print(f"      └─ {actual['msg']}")

    print()
    print("=== 汇总 ===")
    print(f"偏差（闸门或 RULE_ID 与记录不符）：{len(mismatches)}")
    for line in mismatches:
        print(f"  - {line}")
    print(f"被闸门拦下：{len(gate_reject_ids)} 条 -> {', '.join(gate_reject_ids) or '无'}")
    print(f"闸门缺口（业务上必须拒绝、闸门却放行）：{len(gap_ids)} 条 -> {', '.join(gap_ids) or '无'}")

    if mismatches:
        print()
        print("结论：确定性管道与取证记录不一致，需人工复核后再改 PROMPT 或闸门。")
        return 1

    print()
    print(
        "结论：闸门行为与 RULE_ID 全部可复现；"
        f"闸门缺口 {len(gap_ids)} 条是结构化闸门的已知天花板，"
        "由 Day 1 变更单（CCR -> 独立审批 -> Git -> CI）兜底。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
