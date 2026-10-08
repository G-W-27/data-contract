"""
⑤ 事中拦截 / near_threshold 提示（Pre-submission Advisory）
========================================================

需求来源（先有需求，后有功能）
------------------------------
V6 演进顺序明确：事中拦截"提交前用 near_threshold 提示一句客观政策事实，不早于 ①"。
即：在把候选契约变更提交给 ① 变更单之前，若某条规则的阈值改动会让一批历史交易
"踩在阈值边上"，就提示一句客观事实（例如"新阈值 800 万，历史有 12 笔在 760~840 万之间"），
让申请人/审批人意识到影响。**它只提示、绝不拦截**——不做成又一个审批门、不早于 ① 的追溯链路。

本模块产出物是"提示清单"（hints），不是阻断。复用 ① 的前提：只有在契约变更可追溯
（contract_change_requests 已存在）的环境下，提示才有归属对象。

诚实边界（🔵 规划落地的诚实标注）
---------------------------------
- 本模块是 advisory only：返回 hints，调用方决定是否在 UI 上展示；不抛异常、不改数据。
- "near band" 是相对阈值的百分比带（默认 5%），属工程约定，不是内控规则本身。
- 不早于 ①：模块接受 traceability_ready 开关，False 时直接返回空提示并标注"未启用追溯，跳过"。
- 演示用历史样本（sample_transactions_near_threshold.json）是等价构造，非 PG 实跑。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_BAND_PCT = 0.05  # 阈值上下 5% 视为"邻近"


@dataclass
class Hint:
    rule_id: str
    field: str
    new_threshold: float
    band_low: float
    band_high: float
    near_count: int
    near_examples: list
    text: str


def _in_band(value: float, threshold: float, band_pct: float) -> bool:
    if threshold == 0:
        return False
    lo = threshold * (1 - band_pct)
    hi = threshold * (1 + band_pct)
    return lo <= abs(value) <= hi


def check_near_threshold(
    candidate: dict,
    historical_values: list[dict],
    band_pct: float = DEFAULT_BAND_PCT,
) -> list[Hint]:
    """给定一条候选规则变更（含新阈值）与历史交易样本，产出邻近提示。

    candidate 形如:
      {"rule_id": "erp_transactions.amount.q0", "field": "amount",
       "new_threshold": 8000000, "value_column": "amount"}
    historical_values 形如: [{"transaction_id": "T001", "amount": 7800000}, ...]
    """
    hints: list[Hint] = []
    col = candidate.get("value_column", candidate.get("field"))
    thr = float(candidate["new_threshold"])
    lo = thr * (1 - band_pct)
    hi = thr * (1 + band_pct)
    near = [r for r in historical_values if _in_band(float(r.get(col, 0)), thr, band_pct)]
    if near:
        examples = [r.get("transaction_id") for r in near[:5]]
        hints.append(Hint(
            rule_id=candidate["rule_id"],
            field=col,
            new_threshold=thr,
            band_low=round(lo, 2),
            band_high=round(hi, 2),
            near_count=len(near),
            near_examples=examples,
            text=(f"规则 {candidate['rule_id']} 新阈值 {thr:,.0f}；历史有 {len(near)} 笔落在 "
                  f"[{lo:,.0f}, {hi:,.0f}] 邻近带内（示例 {examples}），提交前请评估影响。"),
        ))
    return hints


def intercept(
    candidates: list[dict],
    historical_values: list[dict],
    traceability_ready: bool = True,
    band_pct: float = DEFAULT_BAND_PCT,
) -> dict:
    """事中拦截入口：批量候选变更 → 提示清单。

    不早于 ①：traceability_ready=False 时返回空提示并标注未启用。
    """
    if not traceability_ready:
        return {
            "enabled": False,
            "reason": "契约变更可追溯（①）未就绪，事中提示不启用",
            "hints": [],
        }
    all_hints: list[dict] = []
    for cand in candidates:
        for h in check_near_threshold(cand, historical_values, band_pct):
            all_hints.append(h.__dict__)
    return {
        "enabled": True,
        "hint_count": len(all_hints),
        "hints": all_hints,
        "note": "仅提示，不拦截；提交仍须经 ① 变更单与 ② 审批",
    }


def main_cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="⑤ 事中拦截（near_threshold 提示）")
    p.add_argument("--candidates", required=True, help="候选规则变更 JSON（list）")
    p.add_argument("--history", required=True, help="历史交易样本 JSON（list）")
    p.add_argument("--traceability-ready", action="store_true", help="① 追溯就绪才启用")
    p.add_argument("--band-pct", type=float, default=DEFAULT_BAND_PCT)
    p.add_argument("-o", "--output", default="near_threshold_hints.json")
    a = p.parse_args()

    candidates = json.loads(Path(a.candidates).read_text(encoding="utf-8"))
    history = json.loads(Path(a.history).read_text(encoding="utf-8"))
    result = intercept(candidates, history, traceability_ready=a.traceability_ready, band_pct=a.band_pct)
    Path(a.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[⑤] enabled={result['enabled']} hint_count={result.get('hint_count', 0)} -> {a.output}")


if __name__ == "__main__":
    main_cli()
