"""
E（结构化修复单）实证测试：内存 SQLite 镜像 erp_transactions 视图 + journal_entries，
注入真实脏数据驱动真实 FAIL，验证「确定性定位 + 固定 JSON 模板」。

运行：
    python test_repair_order.py
（使用具备 pyyaml + sqlite3 的解释器，例如系统 Python 3.12.4）
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from failure_explainer import extract_rules, classify_failures
from repair_order import (
    extract_predicate,
    build_locate_sql,
    build_repair_order,
    generate_repair_orders,
)

YAML = "financial_data_contract.yaml"


def build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    # 契约视图 erp_transactions：含契约 18 字段（此处只建定位需要的列）
    cur.execute(
        """
        CREATE TABLE erp_transactions (
            transaction_id TEXT PRIMARY KEY,
            amount NUMERIC,
            manual_entry_flag INTEGER,
            approval_level INTEGER,
            is_round_amount INTEGER,
            high_value_flag INTEGER,
            posting_hour INTEGER,
            posting_dayofweek INTEGER,
            same_preparer_approver_flag INTEGER,
            missing_support_flag INTEGER,
            approval_below_expected_flag INTEGER,
            near_approval_threshold_flag INTEGER,
            manual_after_hours_flag INTEGER
        )
        """
    )
    # 源表 journal_entries：含定位需要的 transaction_id / request_id / preparer_id
    cur.execute(
        """
        CREATE TABLE journal_entries (
            transaction_id TEXT PRIMARY KEY,
            request_id TEXT,
            preparer_id TEXT
        )
        """
    )
    # 干净基线行
    cur.execute(
        "INSERT INTO erp_transactions (transaction_id, amount, missing_support_flag) "
        "VALUES ('TRX00001', 1000, 0)"
    )
    cur.execute(
        "INSERT INTO journal_entries (transaction_id, request_id, preparer_id) "
        "VALUES ('TRX00001', 'REQ00001', 'E001')"
    )
    # 脏行 1：amount 超 500 万（与 D 实证同口径 TRX10024）
    cur.execute(
        "INSERT INTO erp_transactions (transaction_id, amount, missing_support_flag) "
        "VALUES ('TRX10024', 6000000, 0)"
    )
    cur.execute(
        "INSERT INTO journal_entries (transaction_id, request_id, preparer_id) "
        "VALUES ('TRX10024', 'REQ10024', 'E023')"
    )
    # 脏行 2：missing_support_flag=1（另一类别）
    cur.execute(
        "INSERT INTO erp_transactions (transaction_id, amount, missing_support_flag) "
        "VALUES ('TRX10025', 2000, 1)"
    )
    cur.execute(
        "INSERT INTO journal_entries (transaction_id, request_id, preparer_id) "
        "VALUES ('TRX10025', 'REQ10025', 'E024')"
    )
    conn.commit()
    return conn


def make_sqlite_locator(conn: sqlite3.Connection):
    def locate(rule):
        sql = build_locate_sql(rule)
        cur = conn.cursor()
        cur.execute(sql)
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]
    return locate


def test_predicate_extraction():
    rules = extract_rules(YAML)
    by_id = {r.rule_id: r for r in rules}
    # amount 规则：谓词应去掉 FROM 与 SELECT，仅保留 WHERE 之后
    amt = by_id["erp_transactions.amount.q0"]
    pred = extract_predicate(amt.query)
    assert "ABS(amount) > 5000000" in pred, pred
    assert "SELECT" not in pred and "FROM" not in pred, pred
    # missing_support_flag 规则
    msf = by_id["erp_transactions.missing_support_flag.q0"]
    pred2 = extract_predicate(msf.query)
    assert "missing_support_flag <> 0" in pred2, pred2
    print("[PASS] predicate extraction")


def test_locate_and_template():
    conn = build_db()
    rules = extract_rules(YAML)
    locate = make_sqlite_locator(conn)

    # 仅 amount 失败
    check_results = [{"rule_id": "erp_transactions.amount.q0",
                      "actual_count": 1, "passed": False}]
    categories = classify_failures(rules, check_results, "1.0.0")
    report = generate_repair_orders(categories, rules, locate, "1.0.0")

    assert report["total_categories"] == 1, report
    assert report["located_rows"] == 1, report
    order = report["orders"][0]
    assert order["transaction_id"] == "TRX10024", order
    assert order["source_request"] == "REQ10024", order
    assert order["requester"] == "E023", order
    assert order["failure_rule"] == "amount", order
    assert order["located"] is True, order
    assert "500 万" in order["reason"], order
    assert order["suggestion"].startswith("核实"), order
    print("[PASS] locate(amount) ->", json.dumps(order, ensure_ascii=False))


def test_two_categories():
    conn = build_db()
    rules = extract_rules(YAML)
    locate = make_sqlite_locator(conn)
    check_results = [
        {"rule_id": "erp_transactions.amount.q0", "actual_count": 1, "passed": False},
        {"rule_id": "erp_transactions.missing_support_flag.q0", "actual_count": 1, "passed": False},
    ]
    categories = classify_failures(rules, check_results, "1.0.0")
    report = generate_repair_orders(categories, rules, locate, "1.0.0")
    assert report["total_categories"] == 2, report
    assert report["located_rows"] == 2, report
    by_rule = {o["failure_rule"]: o for o in report["orders"]}
    assert by_rule["amount"]["transaction_id"] == "TRX10024"
    assert by_rule["missing_support_flag"]["transaction_id"] == "TRX10025"
    assert "缺少支持性凭证" in by_rule["missing_support_flag"]["reason"], by_rule["missing_support_flag"]
    print("[PASS] two categories located; missing_support TRX =",
          by_rule["missing_support_flag"]["transaction_id"])


def test_offline_no_db():
    rules = extract_rules(YAML)
    check_results = [{"rule_id": "erp_transactions.amount.q0",
                      "actual_count": 1, "passed": False}]
    categories = classify_failures(rules, check_results, "1.0.0")
    report = generate_repair_orders(categories, rules, lambda rule: [], "1.0.0")
    assert report["located_rows"] == 0, report
    order = report["orders"][0]
    assert order["located"] is False, order
    assert order["transaction_id"] is None, order
    assert order["failure_rule"] == "amount"
    print("[PASS] offline (no db) -> located=False template")


def test_unknown_rule_graceful():
    rules = extract_rules(YAML)
    check_results = [{"rule_id": "erp_transactions.unknown_field.q0",
                      "actual_count": 3, "passed": False}]
    categories = classify_failures(rules, check_results, "1.0.0")
    report = generate_repair_orders(categories, rules, lambda rule: [], "1.0.0")
    order = report["orders"][0]
    assert order["failure_rule"] == "unknown_field", order
    assert order["located"] is False, order
    print("[PASS] unknown rule -> graceful category-level order")


def dump_sample():
    """导出一个定位成功的样例修复单，作为交付证据。"""
    conn = build_db()
    rules = extract_rules(YAML)
    locate = make_sqlite_locator(conn)
    check_results = [
        {"rule_id": "erp_transactions.amount.q0", "actual_count": 1, "passed": False},
        {"rule_id": "erp_transactions.missing_support_flag.q0", "actual_count": 1, "passed": False},
    ]
    categories = classify_failures(rules, check_results, "1.0.0")
    report = generate_repair_orders(categories, rules, locate, "1.0.0")
    report["execution_id"] = "E-demo-001"
    report["_note"] = (
        "本样例由内存 SQLite（镜像 erp_transactions 视图 + journal_entries）注入真实脏数据驱动，"
        "验证确定性定位与固定模板；生产路径 same 代码由 Postgres 执行 build_locate_sql。"
    )
    Path("repair_orders_sample.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[DUMP] wrote repair_orders_sample.json")


if __name__ == "__main__":
    test_predicate_extraction()
    test_locate_and_template()
    test_two_categories()
    test_offline_no_db()
    test_unknown_rule_graceful()
    dump_sample()
    print("\nALL E TESTS PASSED")
