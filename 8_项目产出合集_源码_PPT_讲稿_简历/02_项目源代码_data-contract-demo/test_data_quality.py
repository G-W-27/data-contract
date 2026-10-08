import os
import subprocess

import psycopg2
import pytest


# ============================================================
# 数据库连接配置
# ============================================================

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "erp_demo"
DB_USER = os.getenv("DATACONTRACT_POSTGRES_USERNAME")

DB_PASSWORD = os.getenv("DATACONTRACT_POSTGRES_PASSWORD")


# ============================================================
# 数据库连接
# ============================================================

@pytest.fixture
def db_connection():
    """创建 PostgreSQL 测试连接。"""

    if not DB_USER:
        pytest.fail(
            "未设置 DATACONTRACT_POSTGRES_USERNAME 环境变量。"
        )

    if not DB_PASSWORD:
        pytest.fail(
            "未设置 DATACONTRACT_POSTGRES_PASSWORD 环境变量。"
        )

    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )

    yield conn

    conn.close()


# ============================================================
# 测试 1：数据库连接正常
# ============================================================

def test_database_connection(db_connection):
    """确认 Pytest 可以连接 ERP Demo 数据库。"""

    assert db_connection is not None


# ============================================================
# 测试 2：数据规模达到预期
# ============================================================

def test_transaction_volume(db_connection):
    """
    当前项目已经生成万级业务数据。

    这里要求：
    erp_transactions 至少有 10000 条记录。
    """

    with db_connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM erp_transactions
            """
        )

        count = cursor.fetchone()[0]

    assert count >= 10000, (
        f"erp_transactions 当前只有 {count} 条，"
        "未达到 10000 条最低测试规模。"
    )


# ============================================================
# 测试 3：核心字段全部存在
# ============================================================

def test_core_columns_exist(db_connection):
    """
    检查 Data Contract 依赖的 18 个核心字段是否存在。
    """

    expected_columns = {
        "transaction_id",
        "erp_system",
        "posting_datetime",
        "amount",
        "currency",
        "gl_account",
        "manual_entry_flag",
        "risk_class",
        "approval_level",
        "is_round_amount",
        "high_value_flag",
        "posting_hour",
        "posting_dayofweek",
        "same_preparer_approver_flag",
        "missing_support_flag",
        "approval_below_expected_flag",
        "near_approval_threshold_flag",
        "manual_after_hours_flag",
    }

    with db_connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'erp_transactions'
            """
        )

        actual_columns = {
            row[0]
            for row in cursor.fetchall()
        }

    missing_columns = expected_columns - actual_columns

    assert not missing_columns, (
        f"erp_transactions 缺少字段：{sorted(missing_columns)}"
    )


# ============================================================
# 测试 4：关键风险标志保持正常
# ============================================================

def test_risk_flags_clean(db_connection):
    """
    正常基线数据中，Contract 当前要求为 0 的风险标志
    不应该出现异常值。
    """

    with db_connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE same_preparer_approver_flag <> 0
                ),
                COUNT(*) FILTER (
                    WHERE missing_support_flag <> 0
                ),
                COUNT(*) FILTER (
                    WHERE approval_below_expected_flag <> 0
                ),
                COUNT(*) FILTER (
                    WHERE near_approval_threshold_flag <> 0
                ),
                COUNT(*) FILTER (
                    WHERE ABS(amount) > 5000000
                )
            FROM erp_transactions
            """
        )

        (
            same_preparer,
            missing_support,
            approval_below,
            near_threshold,
            amount_over_limit,
        ) = cursor.fetchone()

    assert same_preparer == 0, (
        f"发现 {same_preparer} 条制单人与审批人相同的记录。"
    )

    assert missing_support == 0, (
        f"发现 {missing_support} 条缺少支持文件的记录。"
    )

    assert approval_below == 0, (
        f"发现 {approval_below} 条审批层级不足的记录。"
    )

    assert near_threshold == 0, (
        f"发现 {near_threshold} 条接近审批阈值的记录。"
    )

    assert amount_over_limit == 0, (
        f"发现 {amount_over_limit} 条金额超过 500 万的记录。"
    )


# ============================================================
# 测试 5：Data Contract 本身通过
# ============================================================

def test_data_contract():
    """
    调用真实的 datacontract ci。

    这不是模拟测试，而是直接运行当前项目使用的
    financial_data_contract.yaml。
    """

    contract_file = "financial_data_contract.yaml"

    result = subprocess.run(
        [
            "datacontract",
            "ci",
            contract_file,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, (
        "Data Contract 执行失败。\n\n"
        f"STDOUT:\n{result.stdout}\n\n"
        f"STDERR:\n{result.stderr}"
    )

    assert "data contract is valid" in result.stdout.lower(), (
        "Data Contract 没有返回 valid 结果。\n\n"
        f"{result.stdout}"
    )