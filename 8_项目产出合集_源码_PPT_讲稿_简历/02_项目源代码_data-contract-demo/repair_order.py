"""
Day 5 失败解释增强：结构化修复单（repair_order）

设计约束（第六卷 5.1 / 第七卷补写范畴）：
  1. 契约失败时，由「确定性 SQL 定位 + 固定模板」生成 JSON 修复单。
  2. LLM 不参与此步：reason / suggestion 来自确定性字段映射，不调模型。
  3. 定位 SQL 从契约 quality 规则的 query 中确定性抽取 WHERE 谓词，改造为：
        SELECT t.transaction_id, j.request_id, j.preparer_id
        FROM (SELECT transaction_id FROM erp_transactions WHERE <谓词>) t
        JOIN journal_entries j ON t.transaction_id = j.transaction_id
     先在原契约视图内用谓词筛出 transaction_id（视图列名与契约一致、无歧义），
     再回 JOIN journal_entries 取源申请与责任人——避免在底层表上重述视图派生逻辑。
  4. 固定模板字段（第六卷 5.1 样例）：
        transaction_id / source_request / requester / failure_rule / reason / suggestion
  5. 不做可视化图、工单系统、组织流转、复杂状态机、事故大屏、知识库、图谱。

本模块与 failure_explainer 解耦：消费其产出的 Category（已确定类别），
负责把「类别」落到「具体可定位的修复单」。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable, Optional

# 复用第七卷 ⑦ 的确定性分类结果，避免重复实现
try:
    from failure_explainer import extract_rules, classify_failures, Category, Rule
except ImportError:  # pragma: no cover
    extract_rules = classify_failures = Category = Rule = None  # type: ignore


# --------------------------------------------------------------------------- #
# 0. 契约字段 → 确定性修复指引（LLM 不参与）
# --------------------------------------------------------------------------- #
# key = 契约字段名（即 rule.field）；value = (reason, suggestion)。
REPAIR_GUIDANCE: dict[str, tuple[str, str]] = {
    "amount": (
        "交易金额绝对值超过契约约定的 500 万上限",
        "核实该笔交易金额是否录入错误或超出授权额度，修正后重新执行契约检查",
    ),
    "manual_entry_flag": (
        "手工录入标志取值不在合法集合 {0, 1} 内",
        "修正 manual_entry_flag 为 0 或 1 后重新检查",
    ),
    "approval_level": (
        "审批层级取值不在合法集合 {1, 2, 3, 4} 内",
        "核对审批人级别快照，修正 approval_level 为 1-4 后重新检查",
    ),
    "is_round_amount": (
        "整数金额标志取值不在合法集合 {0, 1} 内",
        "修正 is_round_amount 为 0 或 1 后重新检查",
    ),
    "high_value_flag": (
        "高价值交易标志取值不在合法集合 {0, 1} 内",
        "修正 high_value_flag 为 0 或 1 后重新检查",
    ),
    "posting_hour": (
        "过账小时取值不在合法区间 [0, 23] 内",
        "核对过账时间，修正 posting_hour 为 0-23 后重新检查",
    ),
    "posting_dayofweek": (
        "过账星期取值不在合法区间 [0, 6] 内",
        "核对过账日期，修正 posting_dayofweek 为 0-6 后重新检查",
    ),
    "same_preparer_approver_flag": (
        "存在制单人与审批人相同的记录（契约要求为 0）",
        "调整审批分配，使制单人与审批人不同后重新检查",
    ),
    "missing_support_flag": (
        "存在缺少支持性凭证的记录（契约要求为 0）",
        "补充支持性凭证后重新检查",
    ),
    "approval_below_expected_flag": (
        "存在审批层级低于政策要求的记录（契约要求为 0）",
        "核对审批层级与政策要求，修正后重新检查",
    ),
    "near_approval_threshold_flag": (
        "存在接近审批阈值的记录（契约要求为 0）",
        "核对是否需升级审批或补充材料后重新检查",
    ),
    "manual_after_hours_flag": (
        "非工作时间手工录入标志取值不在合法集合 {0, 1} 内",
        "修正 manual_after_hours_flag 为 0 或 1 后重新检查",
    ),
}


# --------------------------------------------------------------------------- #
# 1. 从契约 quality.query 确定性抽取 WHERE 谓词
# --------------------------------------------------------------------------- #
_PREDICATE_RE = re.compile(
    r"SELECT\s+COUNT\s*\(\s*\*\s*\)\s+FROM\s+\w+\s+WHERE\s+(.*)",
    re.IGNORECASE | re.DOTALL,
)


def extract_predicate(query: str) -> str:
    """
    从 quality 规则的 query（形如 `SELECT COUNT(*) FROM erp_transactions WHERE ...`）
    中确定性抽取 WHERE 之后的谓词。无 WHERE 时返回 `1=1`（整表计数规则）。
    """
    if not query:
        return "1=1"
    m = _PREDICATE_RE.search(query)
    if not m:
        return "1=1"
    return m.group(1).strip()


# --------------------------------------------------------------------------- #
# 2. 构造确定性定位 SQL（视图内筛 transaction_id → 回 JOIN 取责任人）
# --------------------------------------------------------------------------- #
def build_locate_sql(rule: "Rule", model_table: str = "erp_transactions",
                     source_table: str = "journal_entries") -> str:
    """
    定位 SQL：先在契约视图内用谓词筛出 transaction_id（列名与契约一致、无歧义），
    再 JOIN 源表取 source_request(request_id) 与 requester(preparer_id)。
    """
    predicate = extract_predicate(rule.query)
    return (
        f"SELECT t.transaction_id, j.request_id, j.preparer_id\n"
        f"FROM (\n"
        f"  SELECT transaction_id\n"
        f"  FROM {model_table}\n"
        f"  WHERE {predicate}\n"
        f") t\n"
        f"JOIN {source_table} j ON t.transaction_id = j.transaction_id"
    )


# --------------------------------------------------------------------------- #
# 3. 固定模板修复单
# --------------------------------------------------------------------------- #
def build_repair_order(
    failure_rule: str,
    transaction_id: Optional[str],
    source_request: Optional[str],
    requester: Optional[str],
    located: bool,
    actual_count: int = -1,
) -> dict:
    """
    固定模板修复单（第六卷 5.1 样例字段）。reason / suggestion 来自确定性映射，
    不依赖 LLM。located=False 表示未连库、仅给出可执行的定位 SQL 与类别级指引。
    """
    reason, suggestion = REPAIR_GUIDANCE.get(
        failure_rule,
        ("该字段违反契约约束", "核实该字段取值并修正后重新执行契约检查"),
    )
    order = {
        "failure_rule": failure_rule,
        "transaction_id": transaction_id,
        "source_request": source_request,
        "requester": requester,
        "reason": reason,
        "suggestion": suggestion,
        "located": located,
    }
    if actual_count != -1:
        order["actual_count"] = actual_count
    return order


# --------------------------------------------------------------------------- #
# 4. 主流程：类别 → 定位 → 修复单
# --------------------------------------------------------------------------- #
def generate_repair_orders(
    categories: list,
    rules: list,
    locate: Callable[["Rule"], list[tuple]],
    contract_version: str = "unknown",
) -> dict:
    """
    categories: failure_explainer.classify_failures 的产出（已确定类别）
    rules      : failure_explainer.extract_rules 的产出
    locate     : 输入一条 Rule，返回 [(transaction_id, request_id, preparer_id), ...]
                 生产环境由 Postgres 执行 build_locate_sql 得到；测试可注入内存结果。

    返回结构：{contract_version, total_categories, located_rows, orders:[...]}
    """
    rule_by_id = {r.rule_id: r for r in rules}
    orders: list[dict] = []
    located_rows = 0

    for cat in categories:
        rule = rule_by_id.get(cat.rule_id)
        failure_rule = cat.rule_id.split(".")[1] if rule is None else rule.field
        if rule is None:
            # 不在契约清单内的类别：仍给类别级指引（不定位具体行，避免静默丢弃）
            orders.append(
                build_repair_order(
                    failure_rule, None, None, None,
                    located=False, actual_count=cat.actual_count,
                )
            )
            continue

        rows = locate(rule) or []
        located_rows += len(rows)
        for tid, req, prep in rows:
            orders.append(
                build_repair_order(
                    failure_rule, tid, req, prep,
                    located=True, actual_count=cat.actual_count,
                )
            )
        if not rows:
            # 类别已知但库中暂无命中行（例如规则 FAIL 来自仿真输入）：
            # 仍产出一张「类别级」修复单，标注未定位，供操作员手工核。
            orders.append(
                build_repair_order(
                    failure_rule, None, None, None,
                    located=False, actual_count=cat.actual_count,
                )
            )

    return {
        "contract_version": contract_version,
        "total_categories": len(categories),
        "located_rows": located_rows,
        "orders": orders,
    }


# --------------------------------------------------------------------------- #
# 5. 生产定位器：Postgres 执行 build_locate_sql
# --------------------------------------------------------------------------- #
def make_postgres_locator(conn_factory, model_table="erp_transactions",
                         source_table="journal_entries"):
    """
    返回一个 locate(rule) -> list[tuple]，由 Postgres 执行定位 SQL。
    conn_factory：无参返回 psycopg2 连接的工厂（注入式，避免本模块硬依赖连接细节）。
    """
    def locate(rule: "Rule") -> list[tuple]:
        sql = build_locate_sql(rule, model_table, source_table)
        conn = conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                return [(r[0], r[1], r[2]) for r in cur.fetchall()]
        finally:
            conn.close()
    return locate


# --------------------------------------------------------------------------- #
# 6. CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="结构化修复单：确定性定位 + 固定模板")
    ap.add_argument("--yaml", default="financial_data_contract.yaml")
    ap.add_argument("--results", required=True,
                    help="规范化检查结果 JSON：[{rule_id, actual_count, passed}]")
    ap.add_argument("--execution-id", default="manual-run")
    ap.add_argument("--db", action="store_true",
                    help="连接 Postgres 实际执行定位（需环境变量提供连接配置）")
    ap.add_argument("--model-table", default="erp_transactions")
    ap.add_argument("--source-table", default="journal_entries")
    ap.add_argument("-o", "--out", default="repair_orders.json")
    args = ap.parse_args()

    if extract_rules is None:
        raise RuntimeError("未能导入 failure_explainer，请在本项目目录运行。")

    import yaml  # 仅 CLI 需要

    rules = extract_rules(args.yaml)
    doc = yaml.safe_load(Path(args.yaml).read_text(encoding="utf-8"))
    contract_version = doc.get("info", {}).get("version", "unknown")
    check_results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    categories = classify_failures(rules, check_results, contract_version)

    if args.db:
        # 生产路径：复用 erp_app_v6 的连接工厂；此处延迟导入以隔离 streamlit 副作用
        import importlib
        erp = importlib.import_module("erp_app_v6")
        locate = make_postgres_locator(
            erp.get_connection, args.model_table, args.source_table
        )
    else:
        # 离线/文档路径：不连库，仅给出定位 SQL 与类别级指引
        def locate(rule):  # type: ignore
            return []

    report = generate_repair_orders(categories, rules, locate, contract_version)
    report["execution_id"] = args.execution_id
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"CONTRACT_VERSION : {contract_version}")
    print(f"EXECUTION_ID     : {args.execution_id}")
    print(f"CATEGORIES       : {report['total_categories']}")
    print(f"LOCATED_ROWS     : {report['located_rows']}")
    print(f"DB_MODE          : {'postgres' if args.db else 'offline'}")
    print(f"WROTE: {args.out}")


if __name__ == "__main__":
    main()
