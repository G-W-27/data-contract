"""
Failure Explanation — 确定性分类 + LLM 只解释已确定类别 + 一类一次缓存。

设计约束（第七卷 9.3 / 整体思路第十四节）：
  1. 契约先做确定性分类：把 datacontract-cli 的 FAIL 结果规范化为 (rule_id, error_signature) 类别。
  2. LLM 只解释已经确定的异常类别，不参与判断「哪条数据违规」。
  3. 一类一次解释 + 缓存；缓存 key 五项：
        contract_version + rule_id + error_signature + prompt_version + model_version
     任一变化 → 旧解释立即失效。

本文件不依赖 datacontract-cli 的具体输出格式：它消费一个规范化的
check_results 列表（由确定性分类器产出），因此「发现 FAIL」与「解释 FAIL」
被明确解耦——前者是 datacontract-cli 的职责，后者是本模块的职责。

可用作库 import，也可 CLI 运行：
    python failure_explainer.py --yaml financial_data_contract.yaml \
        --results check_results.json \
        --prompt-version fx-v1 --model-version deepseek-web-chat-20261002
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


CONTRACT_VERSION_FALLBACK = "unknown"


# --------------------------------------------------------------------------- #
# 1. 确定性分类：从契约派生规则清单，并把原始 FAIL 聚成类别
# --------------------------------------------------------------------------- #
@dataclass
class Rule:
    rule_id: str            # 从 yaml 结构确定性派生，例如 erp_transactions.amount.q0
    model: str
    field: str
    description: str
    query: str
    must_be: int
    index: int


@dataclass
class Category:
    rule_id: str
    contract_version: str
    error_signature: str    # 类别级指纹（默认 mustBe=N），不含实际违反数
    actual_count: int
    description: str
    must_be: int


def extract_rules(yaml_path: str) -> list[Rule]:
    """从契约 yaml 确定性派生每条 quality 规则的 rule_id / 描述 / mustBe。"""
    if yaml is None:
        raise RuntimeError("需要 PyYAML：pip install pyyaml")
    text = Path(yaml_path).read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    version = (
        doc.get("info", {}).get("version", CONTRACT_VERSION_FALLBACK)
        if isinstance(doc, dict)
        else CONTRACT_VERSION_FALLBACK
    )
    rules: list[Rule] = []
    models = doc.get("models", {}) if isinstance(doc, dict) else {}
    for model_name, model_def in models.items():
        fields = model_def.get("fields", {}) if isinstance(model_def, dict) else {}
        for field_name, field_def in fields.items():
            qualities = field_def.get("quality", []) if isinstance(field_def, dict) else []
            for idx, q in enumerate(qualities):
                rules.append(
                    Rule(
                        rule_id=f"{model_name}.{field_name}.q{idx}",
                        model=model_name,
                        field=field_name,
                        description=field_def.get("description", ""),
                        query=(q.get("query", "") or "").strip(),
                        must_be=int(q.get("mustBe", 0)),
                        index=idx,
                    )
                )
    return rules


def classify_failures(
    rules: list[Rule],
    check_results: list[dict],
    contract_version: str,
    signature_hints: Optional[dict[str, str]] = None,
) -> list[Category]:
    """
    把规范化 check_results 聚成类别。

    check_results 每项形如：
        {"rule_id": "erp_transactions.amount.q0", "actual_count": 3, "passed": False}
    passed=True 的项被忽略（不解释合规项）。

    error_signature 默认取类别级指纹 `mustBe={must_be}`（不含 actual_count），
    保证「同一规则只要 FAIL，解释命中同一缓存」；可通过 signature_hints 覆盖
    为更细的指纹（例如按具体违反形态分桶）。
    """
    signature_hints = signature_hints or {}
    rule_by_id = {r.rule_id: r for r in rules}
    categories: list[Category] = []
    for res in check_results:
        if res.get("passed", False):
            continue
        rid = res["rule_id"]
        rule = rule_by_id.get(rid)
        if rule is None:
            # 不在契约清单内的 FAIL：仍归类为未知规则，便于审计而非静默丢弃
            categories.append(
                Category(
                    rule_id=rid,
                    contract_version=contract_version,
                    error_signature=signature_hints.get(rid, "mustBe=unknown"),
                    actual_count=int(res.get("actual_count", -1)),
                    description=res.get("description", ""),
                    must_be=-1,
                )
            )
            continue
        sig = signature_hints.get(rid, f"mustBe={rule.must_be}")
        categories.append(
            Category(
                rule_id=rid,
                contract_version=contract_version,
                error_signature=sig,
                actual_count=int(res.get("actual_count", -1)),
                description=rule.description,
                must_be=rule.must_be,
            )
        )
    return categories


# --------------------------------------------------------------------------- #
# 2. 缓存：五 key → 解释文本，JSONL 落盘
# --------------------------------------------------------------------------- #
def make_cache_key(
    contract_version: str,
    rule_id: str,
    error_signature: str,
    prompt_version: str,
    model_version: str,
) -> str:
    raw = f"{contract_version}|{rule_id}|{error_signature}|{prompt_version}|{model_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class CacheRecord:
    key: str
    rule_id: str
    contract_version: str
    error_signature: str
    prompt_version: str
    model_version: str
    explanation: str
    source: str            # deterministic | llm
    created_at: str


class ExplanationCache:
    def __init__(self, path: str = "failure_explanations.cache.jsonl"):
        self.path = Path(path)

    def get(self, key: str) -> Optional[CacheRecord]:
        if not self.path.exists():
            return None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("key") == key:
                return CacheRecord(**rec)
        return None

    def put(self, rec: CacheRecord) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# 3. 解释器抽象：Deterministic（离线基线） / LLM（只解释已确定类别）
# --------------------------------------------------------------------------- #
class Explainer:
    """解释器接口：输入一个已确定的 Category，返回解释文本。"""

    source = "base"

    def explain(self, cat: Category) -> str:  # pragma: no cover - 抽象
        raise NotImplementedError


class DeterministicExplainer(Explainer):
    """
    确定性解释器（离线、可复现、不调模型）。

    它只持有规则的结构信息（description / mustBe / actual_count），生成「结构级」
    解释。它证明了：解释这一动作本身不需要 LLM 也能完成；LLM 只是在类别已知后
    补充业务语义，而不是去判断违规本身。
    """

    source = "deterministic"

    def explain(self, cat: Category) -> str:
        if cat.actual_count == -1:
            cnt_desc = "（实际违反数未在结果中给出）"
        else:
            cnt_desc = f"当前检测到 {cat.actual_count} 条违反"
        base = (
            f"【规则 {cat.rule_id}】{cat.description}。该字段要求满足 mustBe={cat.must_be}，"
            f"即不允许出现约束之外的值。{cnt_desc}。"
        )
        if cat.must_be == 0:
            meaning = (
                "这意味着存在不满足该字段业务约束的交易记录，"
                "可能对应录入错误、流程越界或系统集成偏差，"
                "应结合契约变更单（CCR）流程追溯责任人并定位根因。"
            )
        else:
            meaning = (
                "该规则的期望约束非 0，偏离即代表数据未达约定状态，"
                "需核对上游来源或既有变更是否覆盖此场景。"
            )
        return base + meaning


class LLMExplainer(Explainer):
    """
    LLM 解释器：只在「已确定的类别」上工作，构造的 prompt 不含任何具体数据行，
    因此 LLM 没有机会去「判断哪条数据违规」——它只解释类别含义。

    本 demo 不直连模型（网页对话端无法在代码层调用），用 from_text 把网页端
    返回的解释回填；未来接 API 时传入 fetcher=call_llm 即可。
    """

    source = "llm"

    def __init__(
        self,
        prompt_version: str,
        model_version: str,
        fetcher: Optional[Callable[[str], str]] = None,
    ):
        self.prompt_version = prompt_version
        self.model_version = model_version
        self.fetcher = fetcher

    @staticmethod
    def _build_prompt(cat: Category) -> str:
        # 关键点：prompt 只描述「类别」，不给任何具体数据行
        return (
            "以下是已确定的契约异常类别，请只用业务语言解释其风险含义，"
            "不要判断或枚举具体哪些数据行违规。\n"
            f"规则：{cat.rule_id}\n"
            f"字段含义：{cat.description}\n"
            f"约束：mustBe={cat.must_be}\n"
            f"当前违反条数：{cat.actual_count}\n"
        )

    def explain(self, cat: Category, manual_text: Optional[str] = None) -> str:
        if manual_text is not None:
            return manual_text
        if self.fetcher is None:
            raise RuntimeError("LLMExplainer 未配置 fetcher，且未提供 manual_text")
        return self.fetcher(self._build_prompt(cat))


# --------------------------------------------------------------------------- #
# 4. 主流程：聚类 → 逐类查缓存 → 未命中调解释器 → 写缓存
# --------------------------------------------------------------------------- #
@dataclass
class ExplanationOutcome:
    rule_id: str
    error_signature: str
    actual_count: int
    explanation: str
    cache_hit: bool
    source: str


def explain_failures(
    rules: list[Rule],
    check_results: list[dict],
    contract_version: str,
    prompt_version: str,
    model_version: str,
    explainer: Explainer,
    cache: Optional[ExplanationCache] = None,
    signature_hints: Optional[dict[str, str]] = None,
) -> dict:
    cache = cache or ExplanationCache()
    categories = classify_failures(rules, check_results, contract_version, signature_hints)

    outcomes: list[ExplanationOutcome] = []
    for cat in categories:
        key = make_cache_key(
            cat.contract_version,
            cat.rule_id,
            cat.error_signature,
            prompt_version,
            model_version,
        )
        hit = cache.get(key)
        if hit is not None:
            outcomes.append(
                ExplanationOutcome(
                    rule_id=cat.rule_id,
                    error_signature=cat.error_signature,
                    actual_count=cat.actual_count,
                    explanation=hit.explanation,
                    cache_hit=True,
                    source=hit.source,
                )
            )
            continue
        text = explainer.explain(cat)
        cache.put(
            CacheRecord(
                key=key,
                rule_id=cat.rule_id,
                contract_version=cat.contract_version,
                error_signature=cat.error_signature,
                prompt_version=prompt_version,
                model_version=model_version,
                explanation=text,
                source=explainer.source,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        outcomes.append(
            ExplanationOutcome(
                rule_id=cat.rule_id,
                error_signature=cat.error_signature,
                actual_count=cat.actual_count,
                explanation=text,
                cache_hit=False,
                source=explainer.source,
            )
        )

    return {
        "contract_version": contract_version,
        "prompt_version": prompt_version,
        "model_version": model_version,
        "total_failures": len(check_results),
        "explained_categories": len(outcomes),
        "cache_hits": sum(1 for o in outcomes if o.cache_hit),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outcomes": [o.__dict__ for o in outcomes],
    }


# --------------------------------------------------------------------------- #
# 5. CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Failure Explanation：确定性分类 + 缓存解释")
    ap.add_argument("--yaml", default="financial_data_contract.yaml")
    ap.add_argument(
        "--results",
        required=True,
        help="规范化检查结果的 JSON 文件：[{rule_id, actual_count, passed}]",
    )
    ap.add_argument("--prompt-version", default="fx-v1")
    ap.add_argument("--model-version", default="deterministic-baseline")
    ap.add_argument(
        "--explainer",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="llm 模式需配合 --manual-text 或未来接入 fetcher",
    )
    ap.add_argument("--manual-text", default=None, help="llm 模式下回填的网页端解释")
    ap.add_argument("--cache", default="failure_explanations.cache.jsonl")
    ap.add_argument("-o", "--out", default="failure_explanation_report.json")
    args = ap.parse_args()

    rules = extract_rules(args.yaml)
    # 契约版本：从 yaml 读，作为缓存 key 第一项
    if yaml is not None:
        doc = yaml.safe_load(Path(args.yaml).read_text(encoding="utf-8"))
        contract_version = doc.get("info", {}).get("version", CONTRACT_VERSION_FALLBACK)
    else:  # pragma: no cover
        contract_version = CONTRACT_VERSION_FALLBACK

    check_results = json.loads(Path(args.results).read_text(encoding="utf-8"))

    if args.explainer == "llm":
        explainer: Explainer = LLMExplainer(
            args.prompt_version, args.model_version
        )
        # llm 模式若给了 manual_text，则每个类别都用同一回填文本（demo 简化）
        if args.manual_text:
            orig = explainer.explain

            def patched(cat):  # type: ignore
                return orig(cat, manual_text=args.manual_text)

            explainer.explain = patched  # type: ignore
    else:
        explainer = DeterministicExplainer()

    report = explain_failures(
        rules,
        check_results,
        contract_version,
        args.prompt_version,
        args.model_version,
        explainer,
        ExplanationCache(args.cache),
    )
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"CONTRACT_VERSION: {contract_version}")
    print(f"PROMPT_VERSION : {args.prompt_version}")
    print(f"MODEL_VERSION  : {args.model_version}")
    print(f"EXPLAINER      : {explainer.source}")
    print(f"FAILURES       : {report['total_failures']}")
    print(f"CATEGORIES     : {report['explained_categories']}")
    print(f"CACHE_HITS     : {report['cache_hits']}")
    print(f"WROTE: {args.out}")


if __name__ == "__main__":
    main()
