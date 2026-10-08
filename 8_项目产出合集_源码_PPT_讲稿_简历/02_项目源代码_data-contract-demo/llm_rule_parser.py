"""Day 2 · Contract Copilot 第 2 小步：自然语言 -> 结构化规则 JSON

边界：
1. 本文件不修改 financial_data_contract.yaml。
2. 本文件不生成 YAML，只产出结构化 JSON。
3. 输出必须交给 contract_rule_schema.py 校验；未通过即终止，不允许自动修正后放行。
4. 第 1 版用固定 JSON 占位（假模型），先把管道打通，再替换为真实模型调用。

说明：
- strip_code_fence() 只剥离 Markdown 代码围栏（```json / ```），
  属于确定性归一化，不触碰任何字段、算符、数值。
  是否发生过剥离会被打印出来，便于取证。
- 除围栏外的一切内容不做任何修补：模型多说话、算符写中文、
  字段不存在，一律 REJECT 终止。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from contract_rule_schema import validate_rule_json
from llm_audit import log_llm_call

PROMPT_VERSION = "rule-extract-v1"
MODEL_VERSION = "stub-v1"  # 假模型；接真模型时用 --model 指定真实模型名

SYSTEM_PROMPT_V1 = """你是 ERP 财务数据契约的规则抽取器。
只做一件事：把用户的一句话需求抽取成 JSON 结构。不要生成 YAML，不要解释。

输出要求：
1. 只输出 JSON 本身，不要任何多余文字，不要 Markdown 代码块。
2. business_type 只能是业务类型，例如 采购 / 销售 / 报销。
3. conditions 与 requirements 至少各有一项。
4. operator 只能是 >、>=、<、<=、=、!= 之一，不要写中文。
5. 金额单位统一为元（500万 = 5000000）。
6. 字段名必须是 Contract 中真实存在的字段，不要自己发明。

结构：
{
  "business_type": "采购",
  "conditions": [{"field": "amount", "operator": ">", "value": 5000000}],
  "requirements": [
    {"field": "approval_level", "operator": ">=", "value": 4},
    {"field": "manual_entry_flag", "operator": "=", "value": 0}
  ]
}
"""

# ---------------------------------------------------------------------------
# rule-extract-v2
#
# 为什么有第二版：v1 的示例里写了 value: 5000000 与 approval_level >= 4。
# 实测（用例 06 / 10）证明，当用户句子里没有任何数值依据时，模型会直接复制示例值，
# 产出的规则看着合法、实际毫无业务依据，且两道闸都拦不住 —— 这就是示例泄漏。
# v2 针对两个实测缺陷：
#   1. 示例值改成占位值，并显式禁止照抄；
#   2. 补"何时必须拒答"：无可量化依据、或需求本身在削弱内控。
# 拒答约定：输出一行 `REJECT: 原因`。它不是合法 JSON，会被第一道闸拦下，
# 同时留下 `REJECT:` 前缀供统计拒绝率 —— 不需要为此改 Schema。
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_V2 = """你是 ERP 财务数据契约的规则抽取器。
只做一件事：把用户的一句话需求抽取成 JSON 结构。不要生成 YAML，不要解释。

输出要求：
1. 只输出 JSON 本身，不要任何多余文字，不要 Markdown 代码块。
2. business_type 只能是业务类型，例如 采购 / 销售 / 报销。
3. conditions 与 requirements 至少各有一项。
4. operator 只能是 >、>=、<、<=、=、!= 之一，不要写中文。
5. 金额单位统一为元（500万 = 5000000）。
6. 字段名必须是 Contract 中真实存在的字段，不要自己发明。
7. 审批层级是下限语义：句子说"必须N级审批"，应写成 approval_level >= N，
   不要写成 = N（写成等值会把走了更高级别审批的合规单据判成违规）。
8. 示例里的 1 只是占位符，不代表任何业务阈值，禁止照抄。
   阈值与级别必须来自用户原话；原话里没有的，一律不许自己填。

必须先拒答的两种情况。遇到时不要输出 JSON，只输出一行：
REJECT: 原因

情况一：需求里没有可量化的依据。
例如"金额比较大的采购，审批要严格一点"——没有金额阈值、没有审批级别，
不许猜，不许用示例值，不许沿用常识里常见的数字。
输出：REJECT: 句中无可量化依据，请补充具体金额阈值与审批级别

情况二：需求在削弱内控。
包括取消检查、忽略某个检查、放宽或豁免某项要求、允许申请人审批自己的单据等。
这类需求不是不能做，而是必须走契约变更单审批，不能由 Copilot 直接生成规则。
输出：REJECT: 该需求会削弱内控，需走契约变更单审批，不能由 Copilot 直接生成

结构：
{
  "business_type": "采购",
  "conditions": [{"field": "amount", "operator": ">", "value": 1}],
  "requirements": [
    {"field": "approval_level", "operator": ">=", "value": 1},
    {"field": "manual_entry_flag", "operator": "=", "value": 0}
  ]
}
"""

PROMPT_VERSIONS = {
    "rule-extract-v1": SYSTEM_PROMPT_V1,
    "rule-extract-v2": SYSTEM_PROMPT_V2,
}

# 兼容既有 --print-prompt 用法（不带 --prompt-version 时打印 v1）
SYSTEM_PROMPT = SYSTEM_PROMPT_V1

FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def strip_code_fence(raw: str) -> tuple[str, bool]:
    """只剥离 Markdown 代码围栏；返回 (文本, 是否发生过剥离)。"""
    match = FENCE_RE.match(raw.strip())
    if match:
        return match.group(1), True
    return raw, False


def call_llm(natural_language: str) -> str:
    """第 1 版：假模型，返回固定 JSON 文本，用来验证管道。
    第 2 版：这里替换为真实模型调用，返回模型的原始文本。"""
    return json.dumps(
        {
            "business_type": "采购",
            "conditions": [{"field": "amount", "operator": ">", "value": 5000000}],
            "requirements": [
                {"field": "approval_level", "operator": ">=", "value": 4},
                {"field": "manual_entry_flag", "operator": "=", "value": 0},
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def gate(raw: str) -> dict[str, Any]:
    """闸门：模型输出一律视为不可信输入。"""
    print("----- 模型原始返回 -----")
    print(raw)
    print("------------------------")

    text, stripped = strip_code_fence(raw)
    print(f"FENCE_STRIPPED: {stripped}")

    try:
        rule = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"REJECT：返回的不是合法 JSON：{exc}")

    try:
        validate_rule_json(rule)
    except ValueError as exc:
        raise SystemExit(f"REJECT：Schema 校验未通过\n{exc}")

    print("SCHEMA: PASS")
    return rule


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="财务人员的一句话需求")
    ap.add_argument("--from-file", help="校验一个已保存的模型原始返回文本文件")
    ap.add_argument("--model", default=MODEL_VERSION, help="模型版本标识，用于取证")
    ap.add_argument(
        "--prompt-version",
        default=PROMPT_VERSION,
        choices=sorted(PROMPT_VERSIONS),
        help="提示词版本标识，用于取证",
    )
    ap.add_argument("--print-prompt", action="store_true", help="只打印 SYSTEM_PROMPT")
    ap.add_argument("-o", "--out", default="rule_request_from_llm.json")
    ap.add_argument("--operator", default="unknown", help="操作人标识，用于审计链路")
    ap.add_argument(
        "--change-id",
        default=None,
        help="关联的 Contract 变更单号，用于把本次抽取串到变更单上",
    )
    args = ap.parse_args()

    if args.print_prompt:
        sys.stdout.write(PROMPT_VERSIONS[args.prompt_version])
        return

    print(f"PROMPT_VERSION: {args.prompt_version}")
    print(f"MODEL_VERSION : {args.model}")

    if args.from_file:
        raw = Path(args.from_file).read_text(encoding="utf-8")
    else:
        if not args.text:
            raise SystemExit("请给出一句话需求，或用 --from-file 指定文件")
        raw = call_llm(args.text)

    # 跨切面护栏：模型原始返回即记审计（结构化交接点）。
    # 先假设会 PASS；被闸门 REJECT 时改写 outcome 并仍记一笔，再原样抛出。
    outcome = "SCHEMA: PASS"
    try:
        rule = gate(raw)
    except SystemExit as exc:
        outcome = f"REJECT: {exc}"
        # gate() 抛出的 SystemExit 消息本身已以「REJECT：」开头，
        # 这里去掉其原有前缀再统一加英文 REJECT: 标识，避免双重前缀。
        msg = str(exc).lstrip()
        if msg.startswith("REJECT："):
            msg = msg[len("REJECT："):]
        outcome = f"REJECT: {msg}"
        log_llm_call(
            raw,
            model=args.model,
            prompt_version=args.prompt_version,
            output=outcome,
            operator=args.operator,
            change_id=args.change_id,
            extra={"source_file": args.from_file},
        )
        raise

    log_llm_call(
        raw,
        model=args.model,
        prompt_version=args.prompt_version,
        output=outcome,
        operator=args.operator,
        change_id=args.change_id,
        extra={"source_file": args.from_file, "out_json": args.out},
    )

    Path(args.out).write_text(
        json.dumps(rule, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"WROTE: {args.out}")


if __name__ == "__main__":
    main()
