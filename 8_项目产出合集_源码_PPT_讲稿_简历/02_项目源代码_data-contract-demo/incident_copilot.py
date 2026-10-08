"""
Incident Copilot —— 一次执行的多失败聚合为结构化事故报告。

需求来源（先有需求，后有功能）：
  ⑦ Failure Explanation 解释「单条 / 单类别 FAIL」。当一次 Kestra 执行
  （datacontract test）同时炸出多类失败（或同类多实例）时，逐类别解释会得到
  N 份互不相干的说明，丢失「这是同一次执行、很可能同一根因」的相关性。
  Incident Copilot 把「一次执行的失败批次 + Kestra 执行日志」聚合成**一份**
  结构化事故报告，分四节：
    ① 已确认事实  —— 确定性分类 + 计数（不含任何模型推断）
    ② 异常证据    —— 失败规则 + 已定位交易 + 相关 Kestra 日志行
    ③ 潜在原因    —— LLM 只解释「已确定的类别」，复用 ⑦ 缓存键，不判数据行
    ④ 修复建议    —— 确定性 REPAIR_GUIDANCE + 定位 SQL / 已定位交易

它落在本项目主线定义的合法位置之一：**运行诊断**（主线 = Contract 管数据 /
Runtime 管 Contract 持续执行 / Governance 管 Contract 变化 / LLM 辅助 Governance
与运行诊断）。它是 ⑦ 的升级形态，不是新方向。

设计约束（不偏题）：不建事故大屏 / 工单系统 / 知识库 / 图谱。只产结构化报告 + CLI。

复用（避免重复实现，符合本项目演进路径——新能力站在既有节点上）：
  - failure_explainer：extract_rules / classify_failures / explain_failures /
    make_cache_key / ExplanationCache / DeterministicExplainer / LLMExplainer
    （⑦ 的确定性分类 + 五 key 缓存 + 一类一次解释，本模块 ③ 直接复用 explain_failures）
  - alert_dedup：AlertDeduplicator / build_brief（F 的进程内去重；本模块用它决定
    同一事故在窗口内是否重复发出，而非每条失败刷一次）
  - repair_order：REPAIR_GUIDANCE / build_locate_sql / generate_repair_orders
    （E 的确定性定位 + 修复单，本模块 ② ④ 直接复用）
  - llm_audit：log_llm_call / mask_pii（跨切面审计 + PII 脱敏；本模块把事故事件
    记入同一审计日志，串联治理链路）

四护栏（沿用第七卷护栏语义，写本卷须写明）：
  ① 不直接改生产契约：本模块只读 check_results 与日志，产出报告，不碰
     financial_data_contract.yaml。
  ② 不直接执行修复：修复建议是确定性指引 + 定位 SQL，执行权留给人工 / 变更单。
  ③ 输出必过确定性分类：所有 FAIL 先经 classify_failures 归类，LLM 只看类别不看数据行。
  ④ 版本可追溯：incident_id 内容寻址；潜在原因复用 ⑦ 五 key 缓存；报告含
     contract_version / prompt_version / model_version / incident_id。

诚实边界（写本卷须写明）：
  - 演示环境未直连 LLM：③ 潜在原因用 DeterministicExplainer 基线，或经
    --manual-text 回填网页端解释；不声称模型在线推断。
  - Kestra 执行日志在演示中为结构化镜像输入（sample_execution_log.json）；生产中由
    Kestra execution API / 任务日志提供，解析层不变（parse_execution_log 形态一致）。
  - 定位 SQL 经契约视图 erp_transactions 筛 transaction_id 再 JOIN journal_entries
    （同 E）；演示以内存镜像 / offline 模式驱动，PG 实跑需连库（同 E 的边界）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

# 复用第七卷 ⑦ / E / F 与跨切面审计（注入式导入，避免硬依赖顺序，便于单元测试）
try:
    from failure_explainer import (
        extract_rules,
        classify_failures,
        explain_failures,
        make_cache_key,
        ExplanationCache,
        DeterministicExplainer,
        LLMExplainer,
    )
except ImportError:  # pragma: no cover
    extract_rules = classify_failures = explain_failures = make_cache_key = None
    ExplanationCache = DeterministicExplainer = LLMExplainer = None  # type: ignore

try:
    from alert_dedup import AlertDeduplicator, build_brief
except ImportError:  # pragma: no cover
    AlertDeduplicator = build_brief = None  # type: ignore

try:
    from repair_order import (
        REPAIR_GUIDANCE,
        build_locate_sql,
        generate_repair_orders,
    )
except ImportError:  # pragma: no cover
    REPAIR_GUIDANCE = build_locate_sql = generate_repair_orders = None  # type: ignore

try:
    from llm_audit import log_llm_call, mask_pii
except ImportError:  # pragma: no cover
    log_llm_call = mask_pii = None  # type: ignore


INCIDENT_PREFIX = "inc-"
EMIT_WINDOW_SECONDS_DEFAULT = 300  # 与 F 默认窗口一致，事故报告同窗口只发一次

# 进程内去重单例：同一事故在同一窗口只发一次（与 F 的进程内语义一致，
# 跨多次 build_incident_report 调用共享，而非每次新建实例）。
_DEDUP_CACHE: dict = {}


def get_dedup(window_seconds: int):
    if AlertDeduplicator is None:
        return None
    if window_seconds not in _DEDUP_CACHE:
        _DEDUP_CACHE[window_seconds] = AlertDeduplicator(window_seconds=window_seconds)
    return _DEDUP_CACHE[window_seconds]


# --------------------------------------------------------------------------- #
# 1. incident_id 内容寻址（幂等，与 copilot_ / 缓存键区分）
# --------------------------------------------------------------------------- #
def make_incident_id(
    execution_id: str,
    contract_version: str,
    rule_ids: list[str],
    window_ts: int,
) -> str:
    """
    事故 ID 内容寻址：相同 (execution_id + contract_version + 排序后的失败规则集合 +
    窗口起点) 必得同一 ID——同一次失败批次不会产生第二份事故。
    前缀 inc- 与规则候选的 copilot_ 区分，也区别于 ⑦ 缓存键（纯 hash）。
    """
    sorted_rules = sorted(rule_ids)
    raw = (
        f"{execution_id}|{contract_version}|"
        + ",".join(sorted_rules)
        + f"|{window_ts}"
    )
    return INCIDENT_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# 2. 解析 Kestra 执行日志（结构化镜像输入）
# --------------------------------------------------------------------------- #
def parse_execution_log(log: dict) -> dict:
    """
    解析 Kestra 执行日志。生产由 Kestra execution API 提供；演示用
    sample_execution_log.json。返回规范化结构，log_lines 为字符串列表（每行一条
    任务日志），供异常证据阶段按关键字抽取。
    """
    return {
        "execution_id": log.get("execution_id", "unknown-exec"),
        "namespace": log.get("namespace", ""),
        "flow_id": log.get("flow_id", ""),
        "started_at": log.get("started_at", ""),
        "ended_at": log.get("ended_at", ""),
        "status": log.get("status", ""),
        "tasks": log.get("tasks", []),
        "log_lines": log.get("log_lines", []),
    }


def relevant_log_lines(log: dict, rule_ids: list[str],
                       keywords: Optional[list[str]] = None) -> list[str]:
    """
    从 Kestra 日志中确定性抽取与本次事故相关的行：命中失败规则字段名或通用异常关键字。
    不调模型，纯字符串匹配。
    """
    kws = list(keywords or [])
    for rid in rule_ids:
        parts = rid.split(".")
        if len(parts) == 3:
            kws.append(parts[1])  # erp_transactions.amount.q0 -> amount
    kws = [k for k in kws if k]
    out: list[str] = []
    for line in log.get("log_lines", []):
        low = line.lower()
        if any(k.lower() in low for k in kws):
            out.append(line)
    return out


# --------------------------------------------------------------------------- #
# 3. 主流程：失败批次 + 日志 → 四节事故报告
# --------------------------------------------------------------------------- #
def build_incident_report(
    execution_id: str,
    check_results: list[dict],
    execution_log: dict,
    yaml_path: str,
    prompt_version: str,
    model_version: str,
    explainer=None,
    cache=None,
    locate: Optional[Callable] = None,
    operator: str = "unknown",
    emit_window_seconds: int = EMIT_WINDOW_SECONDS_DEFAULT,
    now: Optional[float] = None,
) -> dict:
    """
    聚合一次执行的失败批次为结构化事故报告。

    参数：
      execution_id   ：Kestra 执行 ID（事故归属）
      check_results  ：规范化检查结果 [{rule_id, actual_count, passed}]
      execution_log  ：parse_execution_log 的形态（dict）
      yaml_path      ：契约文件，供 extract_rules / 读 contract_version
      locate         ：输入 Rule 返回定位行；None 时 offline（仅类别级指引）
      operator       ：触发人，记入跨切面审计

    返回：四节报告 dict（含 incident_id / emit 决策 / 诚实边界标记）。
    """
    if extract_rules is None:
        raise RuntimeError("未能导入 failure_explainer，请在本项目目录运行。")
    import yaml  # 仅运行时需要

    doc = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    contract_version = doc.get("info", {}).get("version", "unknown")
    rules = extract_rules(yaml_path)
    categories = classify_failures(rules, check_results, contract_version)

    # incident_id：内容寻址 + 时间窗口
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    window_ts = int(now // emit_window_seconds) * emit_window_seconds
    incident_id = make_incident_id(
        execution_id, contract_version, [c.rule_id for c in categories], window_ts
    )

    # ① 已确认事实（确定性，无模型）
    confirmed_facts = {
        "execution_id": execution_id,
        "contract_version": contract_version,
        "total_failures_in_input": len(check_results),
        "explained_categories": len(categories),
        "categories": [
            {
                "rule_id": c.rule_id,
                "field": c.rule_id.split(".")[1]
                if len(c.rule_id.split(".")) == 3 else c.rule_id,
                "error_signature": c.error_signature,
                "actual_count": c.actual_count,
                "must_be": c.must_be,
            }
            for c in categories
        ],
    }

    # ② 异常证据（失败规则 + 定位交易 + 相关 Kestra 日志行）
    located_rows: list[dict] = []
    if generate_repair_orders is not None:
        # 离线（locate=None）时仍产出「类别级」修复建议（located=False），
        # 由 generate_repair_orders 内部对每类别补一张类别级单；只有传入真实
        # locate 时才会带出已定位的具体交易。
        locate_fn = locate if locate is not None else (lambda rule: [])
        repair_report = generate_repair_orders(
            categories, rules, locate_fn, contract_version
        )
        located_rows = repair_report.get("orders", [])
    relevant_logs = relevant_log_lines(execution_log, [c.rule_id for c in categories])
    anomaly_evidence = {
        "failing_rules": [c.rule_id for c in categories],
        "located_transactions": [o for o in located_rows if o.get("located")],
        "category_level_guidance": [o for o in located_rows if not o.get("located")],
        "kestra_log_excerpt": relevant_logs[:20],
    }

    # ③ 潜在原因（直接复用 ⑦ explain_failures：确定性分类 + 五 key 缓存 + 一类一次）
    explainer = explainer or DeterministicExplainer()
    cache = cache or ExplanationCache()
    fe_report = explain_failures(
        rules, check_results, contract_version,
        prompt_version, model_version, explainer, cache,
    )
    potential_causes = [
        {
            "rule_id": o["rule_id"],
            "explanation": o["explanation"],
            "source": o["source"],
            "cache_hit": o["cache_hit"],
        }
        for o in fe_report["outcomes"]
    ]

    # ④ 修复建议（确定性 REPAIR_GUIDANCE + 定位，来自 E 的修复单）
    repair_suggestions = [
        {
            "failure_rule": o.get("failure_rule"),
            "transaction_id": o.get("transaction_id"),
            "source_request": o.get("source_request"),
            "requester": o.get("requester"),
            "reason": o.get("reason"),
            "suggestion": o.get("suggestion"),
            "located": o.get("located", False),
        }
        for o in located_rows
    ]

    # 复用 F：同一事故在窗口内只发一次（进程内单例，跨调用共享）
    emit_decision: Optional[dict] = None
    emit_brief: Optional[dict] = None
    if AlertDeduplicator is not None:
        dedup = get_dedup(emit_window_seconds)
        emit_decision = dedup.emit(execution_id, incident_id, now=now)
        if emit_decision["emit"]:
            emit_brief = build_brief(
                execution_id, incident_id,
                emit_decision["suppressed_count"] + 1,
                emit_decision["window_start"], emit_window_seconds,
            ) if build_brief is not None else None

    # 跨切面审计：把事故事件记入同一审计日志（串联治理链路），PII 已脱敏
    if log_llm_call is not None:
        failing_summary = mask_pii(
            "失败规则：" + ",".join([c.rule_id for c in categories]) or "无"
        )
        log_llm_call(
            raw=failing_summary,
            model=model_version,
            prompt_version=prompt_version,
            output=f"INCIDENT: {incident_id} emit={emit_decision['emit'] if emit_decision else 'n/a'}",
            operator=operator,
            extra={"incident_id": incident_id, "execution_id": execution_id},
        )

    return {
        "incident_id": incident_id,
        "execution_id": execution_id,
        "contract_version": contract_version,
        "prompt_version": prompt_version,
        "model_version": model_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "confirmed_facts": confirmed_facts,
        "anomaly_evidence": anomaly_evidence,
        "potential_causes": potential_causes,
        "repair_suggestions": repair_suggestions,
        "emit": emit_decision,
        "emit_brief": emit_brief,
        "boundary": {
            "llm_mode": "deterministic-baseline"
            if explainer.source == "deterministic"
            else "llm-needs-fetcher-or-manual-text",
            "kestra_log_source": "structured-mirror-input(simulated in demo)",
            "locate_mode": "offline" if locate is None else "postgres-or-injected",
            "note": "演示未直连 LLM；定位经契约视图再 JOIN 源表；同一次失败批次 incident_id 幂等。",
        },
    }


# --------------------------------------------------------------------------- #
# 4. CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Incident Copilot：一次执行失败批次 → 结构化事故报告"
    )
    ap.add_argument("--yaml", default="financial_data_contract.yaml")
    ap.add_argument("--results", required=True,
                    help="规范化检查结果 JSON：[{rule_id, actual_count, passed}]")
    ap.add_argument("--execution-log", required=True,
                    help="Kestra 执行日志 JSON（结构化镜像）")
    ap.add_argument("--execution-id", default=None,
                    help="覆盖日志中的 execution_id（演示用）")
    ap.add_argument("--prompt-version", default="inc-v1")
    ap.add_argument("--model-version", default="deterministic-baseline")
    ap.add_argument("--explainer", choices=["deterministic", "llm"],
                    default="deterministic")
    ap.add_argument("--manual-text", default=None,
                    help="llm 模式下回填的网页端解释（每类别同文本，demo 简化）")
    ap.add_argument("--db", action="store_true",
                    help="连 PG 实际定位（需连接配置环境变量）")
    ap.add_argument("--operator", default="unknown")
    ap.add_argument("--emit-window", type=int, default=EMIT_WINDOW_SECONDS_DEFAULT)
    ap.add_argument("-o", "--out", default="incident_report.json")
    args = ap.parse_args()

    if extract_rules is None:
        raise RuntimeError("未能导入 failure_explainer，请在本项目目录运行。")

    check_results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    raw_log = json.loads(Path(args.execution_log).read_text(encoding="utf-8"))
    log = parse_execution_log(raw_log)
    execution_id = args.execution_id or log["execution_id"]

    # 解释器
    if args.explainer == "llm":
        explainer = LLMExplainer(args.prompt_version, args.model_version)
        if args.manual_text:

            def patched(cat):  # type: ignore
                return explainer.explain(cat, manual_text=args.manual_text)

            explainer.explain = patched  # type: ignore
    else:
        explainer = DeterministicExplainer()

    # 定位器：生产连 PG，否则 offline
    locate = None
    if args.db:
        if generate_repair_orders is None:
            raise RuntimeError("未能导入 repair_order，无法连库定位。")
        import importlib
        erp = importlib.import_module("erp_app_v6")
        from repair_order import make_postgres_locator

        locate = make_postgres_locator(erp.get_connection)
    # offline 时 locate 保持 None → 仅类别级指引

    report = build_incident_report(
        execution_id=execution_id,
        check_results=check_results,
        execution_log=log,
        yaml_path=args.yaml,
        prompt_version=args.prompt_version,
        model_version=args.model_version,
        explainer=explainer,
        locate=locate,
        operator=args.operator,
        emit_window_seconds=args.emit_window,
    )

    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 终端取证摘要
    cf = report["confirmed_facts"]
    print(f"INCIDENT_ID     : {report['incident_id']}")
    print(f"EXECUTION_ID    : {execution_id}")
    print(f"CONTRACT_VERSION: {report['contract_version']}")
    print(f"CATEGORIES      : {cf['explained_categories']}")
    print(f"LOCATED_ROWS    : {len(report['anomaly_evidence']['located_transactions'])}")
    print(f"CAUSES          : {len(report['potential_causes'])}")
    print(f"REPAIRS         : {len(report['repair_suggestions'])}")
    if report["emit"]:
        print(f"EMIT            : {report['emit']['emit']} "
              f"(suppressed={report['emit']['suppressed_count']})")
    print(f"WROTE: {args.out}")


if __name__ == "__main__":
    main()
