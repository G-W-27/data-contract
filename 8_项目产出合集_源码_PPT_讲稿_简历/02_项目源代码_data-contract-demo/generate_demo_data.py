"""
ERP Demo Data Generator

用途：
1. 从 PostgreSQL 读取已有员工、项目、审批规则
2. 生成正常的业务申请 business_requests
3. 根据审批规则生成 approval_records
4. 根据业务申请和审批结果生成 journal_entries
5. 最终让 erp_transactions View 自动获得大量测试数据

当前版本只生成“正常数据”。
异常数据注入放到下一步单独处理。

运行示例：
python generate_demo_data.py --count 10000
"""

import argparse
import os
import random
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values


# ============================================================
# 1. 基础配置
# ============================================================

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "erp_demo"

# 用户名和密码优先从环境变量读取。
# 这样不会把数据库密码直接写进 Python 文件。
DB_USER = os.getenv("DATACONTRACT_POSTGRES_USERNAME", "kestra")
DB_PASSWORD = os.getenv("DATACONTRACT_POSTGRES_PASSWORD")

# 固定随机种子：
# 每次使用相同配置时，随机逻辑具有可重复性。
RANDOM_SEED = 20260923

# 生成数据的起始时间
BASE_DATETIME = datetime(2026, 9, 1, 8, 0, 0)


# ============================================================
# 2. 数据库连接
# ============================================================

def get_connection():
    """创建 PostgreSQL 数据库连接。"""

    if not DB_PASSWORD:
        raise RuntimeError(
            "没有找到 DATACONTRACT_POSTGRES_PASSWORD 环境变量。\n"
            "请先在 PowerShell 中设置数据库密码，然后重新运行脚本。"
        )

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


# ============================================================
# 3. 读取已有基础数据
# ============================================================

def load_employees(conn):
    """
    读取员工主表。

    返回：
        [
            {
                "employee_id": ...,
                "employee_level": ...
            },
            ...
        ]
    """

    sql = """
        SELECT employee_id, employee_level
        FROM employees
        WHERE is_active = TRUE
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()

    employees = [
        {
            "employee_id": row[0],
            "employee_level": row[1],
        }
        for row in rows
    ]

    if not employees:
        raise RuntimeError("employees 表没有可用员工。")

    return employees


def load_projects(conn):
    """读取项目主表。"""

    sql = """
        SELECT project_id
        FROM projects
        WHERE project_status <> '已终止'
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()

    projects = [row[0] for row in rows]

    if not projects:
        raise RuntimeError("projects 表没有可用项目。")

    return projects


def load_policies(conn):
    """
    读取审批政策。

    每条 policy 都包含：
    business_type       业务类型
    category            业务类别
    min_amount          金额下限
    max_amount          金额上限
    required_level      要求审批级别
    near_threshold      接近审批阈值
    gl_account          总账科目
    """

    sql = """
        SELECT
            policy_id,
            business_type,
            category,
            min_amount,
            max_amount,
            required_level,
            near_threshold_amount,
            gl_account
        FROM approval_policies
        ORDER BY policy_id
    """

    with conn.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()

    policies = []

    for row in rows:
        policies.append(
            {
                "policy_id": row[0],
                "business_type": row[1],
                "category": row[2],
                "min_amount": Decimal(str(row[3])),
                "max_amount": Decimal(str(row[4])),
                "required_level": int(row[5]),
                "near_threshold_amount": Decimal(str(row[6])),
                "gl_account": row[7],
            }
        )

    if not policies:
        raise RuntimeError("approval_policies 表没有规则。")

    return policies


# ============================================================
# 4. 选择审批人
# ============================================================

def choose_approver(employees, requester_id, required_level):
    """
    选择满足审批层级要求、且与制单人不同的审批人。

    优先选择：
        employee_level == required_level

    如果没有，再选择：
        employee_level >= required_level
    """

    exact_candidates = [
        employee
        for employee in employees
        if employee["employee_id"] != requester_id
        and employee["employee_level"] == required_level
    ]

    if exact_candidates:
        return random.choice(exact_candidates)

    higher_candidates = [
        employee
        for employee in employees
        if employee["employee_id"] != requester_id
        and employee["employee_level"] >= required_level
    ]

    if higher_candidates:
        return random.choice(higher_candidates)

    raise RuntimeError(
        f"找不到能够审批 level={required_level} "
        f"且不同于 requester={requester_id} 的员工。"
    )


# ============================================================
# 5. 生成安全金额
# ============================================================

def generate_safe_amount(policy):
    """
    在审批规则的安全区域生成金额。

    要求：
    1. 大于 min_amount
    2. 小于 near_threshold_amount
    3. 不进入“接近审批阈值”区域
    4. 不超过 500 万

    这样生成的数据可以保证：
        near_approval_threshold_flag = 0
    """

    min_amount = policy["min_amount"]
    near_threshold = policy["near_threshold_amount"]

    # 留出 1000 元安全边界。
    lower = min_amount + Decimal("1000")
    upper = near_threshold - Decimal("1000")

    # 当前审批规则均能满足这个条件。
    if lower >= upper:
        raise RuntimeError(
            f"审批规则 {policy['policy_id']} 没有足够的安全金额区间。"
        )

    # 防止高于 Data Contract 的 500 万金额限制。
    upper = min(upper, Decimal("4990000"))

    lower_int = int(lower)
    upper_int = int(upper)

    amount_int = random.randint(lower_int, upper_int)

    # 财务金额保留两位小数。
    return Decimal(amount_int).quantize(Decimal("0.01"))


# ============================================================
# 6. 生成正常过账时间
# ============================================================

def generate_posting_datetime(index):
    """
    生成工作日、工作时间内的过账时间。

    目的：
    让正常数据中的 posting_hour / posting_dayofweek
    自动保持合理。
    """

    # 通过 index 让数据分布到不同日期。
    days_offset = index // 500

    current_date = BASE_DATETIME + timedelta(days=days_offset)

    # 如果落在周末，顺延到周一。
    while current_date.weekday() >= 5:
        current_date += timedelta(days=1)

    # 8:00 - 17:59
    hour = random.randint(8, 17)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)

    return current_date.replace(
        hour=hour,
        minute=minute,
        second=second,
        microsecond=0,
    )


# ============================================================
# 7. 生成标题
# ============================================================

def generate_title(business_type, category, index):
    """生成业务申请标题。"""

    return f"{business_type}-{category}-模拟申请-{index}"


# ============================================================
# 8. 生成正文
# ============================================================

def generate_description(business_type, category):
    """生成业务申请说明。"""

    if business_type == "采购":
        return f"企业日常采购业务，申请类别为{category}。"

    if business_type == "研发":
        return f"研发项目相关费用申请，费用类别为{category}。"

    if business_type == "销售":
        return f"销售业务相关费用申请，费用类别为{category}。"

    return f"{business_type}业务费用申请，类别为{category}。"


# ============================================================
# 9. 主数据生成逻辑
# ============================================================

def generate_data(conn, count):
    """生成业务申请、审批记录和财务交易。"""

    print("=== 1. 读取已有基础数据 ===")

    employees = load_employees(conn)
    projects = load_projects(conn)
    policies = load_policies(conn)

    print(f"员工数量：{len(employees)}")
    print(f"项目数量：{len(projects)}")
    print(f"审批规则数量：{len(policies)}")

    # --------------------------------------------------------
    # 找到当前最大 request_id 数字
    # --------------------------------------------------------

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT request_id
            FROM business_requests
            WHERE request_id LIKE 'REQ%%'
            """
        )

        existing_ids = [row[0] for row in cursor.fetchall()]

    max_number = 0

    for request_id in existing_ids:
        try:
            number = int(request_id.replace("REQ", ""))
            max_number = max(max_number, number)
        except ValueError:
            continue

    start_number = max_number + 1

    print(f"已有最大 Request 编号：{max_number}")
    print(f"本次生成起始编号：REQ{start_number:05d}")

    # --------------------------------------------------------
    # 准备三张表的批量数据
    # --------------------------------------------------------

    request_rows = []
    approval_rows = []
    journal_rows = []

    print("=== 2. 开始生成数据 ===")

    for i in range(count):

        request_number = start_number + i

        request_id = f"REQ{request_number:05d}"
        transaction_id = f"TXN-{request_id}"
        approval_id = f"APR{request_number:05d}"

        # 随机选择审批政策。
        policy = random.choice(policies)

        # 随机选择制单员工。
        requester = random.choice(employees)

        requester_id = requester["employee_id"]

        # 找到满足审批要求的审批人。
        approver = choose_approver(
            employees,
            requester_id,
            policy["required_level"],
        )

        approver_id = approver["employee_id"]
        approver_level = approver["employee_level"]

        # 随机选择项目。
        project_id = random.choice(projects)

        # 在安全区域生成金额。
        amount = generate_safe_amount(policy)

        # 正常数据全部有支持性文件。
        support_document_flag = True

        # 生成提交时间。
        submitted_at = generate_posting_datetime(i)

        # 审批时间在提交后 10-120 分钟。
        approved_at = submitted_at + timedelta(
            minutes=random.randint(10, 120)
        )

        # ----------------------------------------------------
        # 业务申请
        # ----------------------------------------------------

        request_rows.append(
            (
                request_id,
                policy["business_type"],
                policy["category"],
                requester_id,
                project_id,
                generate_title(
                    policy["business_type"],
                    policy["category"],
                    request_number,
                ),
                generate_description(
                    policy["business_type"],
                    policy["category"],
                ),
                amount,
                "CNY",
                support_document_flag,
                "已通过",
                submitted_at,
                approved_at,
            )
        )

        # ----------------------------------------------------
        # 审批记录
        # ----------------------------------------------------

        approval_rows.append(
            (
                approval_id,
                request_id,
                1,
                policy["policy_id"],
                approver_id,
                approver_level,
                policy["required_level"],
                "已通过",
                "系统模拟审批通过",
                False,  # same_preparer_approver_flag：制单人与审批人不同
                False,  # approval_below_expected_flag：审批层级没有低于要求
                False,  # near_approval_threshold_flag：金额没有接近审批阈值
                approved_at,
                submitted_at,
            )
        )

        # ----------------------------------------------------
        # 计算财务风险字段
        # ----------------------------------------------------

        is_round_amount = (
            1 if amount % Decimal("10000") == 0 else 0
        )

        high_value_flag = 1 if amount >= Decimal("500000") else 0

        # 当前正常数据不制造任何高风险异常。
        # 如果金额达到 50 万，按当前项目逻辑记为 MEDIUM。
        if high_value_flag == 1:
            risk_class = "MEDIUM"
        else:
            risk_class = "LOW"

        posting_datetime = approved_at

        posting_hour = posting_datetime.hour
        posting_dayofweek = posting_datetime.weekday()

        # ----------------------------------------------------
        # 财务分录
        # ----------------------------------------------------

        journal_rows.append(
            (
                transaction_id,
                request_id,
                project_id,
                "ERP_DEMO",
                posting_datetime,
                amount,
                "CNY",
                policy["gl_account"],
                requester_id,
                approver_id,
                "已通过",
                policy["required_level"],
                0,  # manual_entry_flag
                1,  # supporting_document_flag
                risk_class,
                posting_hour,
                posting_dayofweek,
                0,  # same_preparer_approver_flag
                0,  # missing_support_flag
                0,  # approval_below_expected_flag
                0,  # near_approval_threshold_flag
                is_round_amount,
                high_value_flag,
                0,  # manual_after_hours_flag
            )
        )

    print(f"业务申请待写入：{len(request_rows)}")
    print(f"审批记录待写入：{len(approval_rows)}")
    print(f"财务分录待写入：{len(journal_rows)}")

    # ========================================================
    # 10. 批量写入 PostgreSQL
    # ========================================================

    print("=== 3. 开始写入 PostgreSQL ===")

    try:
        with conn.cursor() as cursor:

            # ------------------------------------------------
            # business_requests
            # ------------------------------------------------

            request_sql = """
                INSERT INTO business_requests (
                    request_id,
                    business_type,
                    category,
                    requester_id,
                    project_id,
                    request_title,
                    request_description,
                    amount,
                    currency,
                    support_document_flag,
                    request_status,
                    submitted_at,
                    updated_at
                )
                VALUES %s
            """

            execute_values(
                cursor,
                request_sql,
                request_rows,
                page_size=1000,
            )

            print("business_requests 写入完成。")

            # ------------------------------------------------
            # approval_records
            # ------------------------------------------------

            approval_sql = """
                INSERT INTO approval_records (
                    approval_id,
                    request_id,
                    approval_sequence,
                    policy_id,
                    approver_id,
                    approver_level_snapshot,
                    required_level,
                    approval_status,
                    approval_comment,
                    same_preparer_approver_flag,
                    approval_below_expected_flag,
                    near_approval_threshold_flag,
                    approved_at,
                    created_at
                )
                VALUES %s
            """

            execute_values(
                cursor,
                approval_sql,
                approval_rows,
                page_size=1000,
            )

            print("approval_records 写入完成。")

            # ------------------------------------------------
            # journal_entries
            # ------------------------------------------------

            journal_sql = """
                INSERT INTO journal_entries (
                    transaction_id,
                    request_id,
                    project_id,
                    erp_system,
                    posting_datetime,
                    amount,
                    currency,
                    gl_account,
                    preparer_id,
                    approver_id,
                    workflow_status,
                    approval_level,
                    manual_entry_flag,
                    supporting_document_flag,
                    risk_class,
                    posting_hour,
                    posting_dayofweek,
                    same_preparer_approver_flag,
                    missing_support_flag,
                    approval_below_expected_flag,
                    near_approval_threshold_flag,
                    is_round_amount,
                    high_value_flag,
                    manual_after_hours_flag
                )
                VALUES %s
            """

            execute_values(
                cursor,
                journal_sql,
                journal_rows,
                page_size=1000,
            )

            print("journal_entries 写入完成。")

        # 所有三张表成功后统一提交。
        conn.commit()

    except Exception:
        # 任意一步失败，整个批次回滚。
        conn.rollback()
        raise

    print("=== 4. 数据库事务提交成功 ===")


# ============================================================
# 11. 数据验证
# ============================================================

def verify_data(conn, count):
    """检查生成后的数据数量和 Contract 风险字段。"""

    print("=== 5. 验证生成结果 ===")

    with conn.cursor() as cursor:

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM business_requests
            WHERE request_id LIKE 'REQ%%'
            """
        )
        request_count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM journal_entries
            WHERE transaction_id LIKE 'TXN-REQ%%'
            """
        )
        journal_count = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM erp_transactions
            """
        )
        view_count = cursor.fetchone()[0]

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

    print(f"business_requests 总数：{request_count}")
    print(f"journal_entries 总数：{journal_count}")
    print(f"erp_transactions 总数：{view_count}")

    print()
    print("Contract 风险字段检查：")
    print(f"制单审批人相同：{same_preparer}")
    print(f"缺少支持性文件：{missing_support}")
    print(f"审批层级不足：{approval_below}")
    print(f"接近审批阈值：{near_threshold}")
    print(f"金额超过 500 万：{amount_over_limit}")

    if (
        same_preparer == 0
        and missing_support == 0
        and approval_below == 0
        and near_threshold == 0
        and amount_over_limit == 0
    ):
        print()
        print("✅ 本批次生成的数据符合当前 Contract 业务规则。")
    else:
        print()
        print("⚠️ 发现异常，请先不要执行 Contract。")


# ============================================================
# 12. 程序入口
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="生成 ERP Demo 正常业务数据"
    )

    parser.add_argument(
        "--count",
        type=int,
        default=10000,
        help="生成多少条业务交易，默认 10000",
    )

    args = parser.parse_args()

    if args.count <= 0:
        raise ValueError("--count 必须大于 0。")

    # 固定随机种子。
    random.seed(RANDOM_SEED)

    print("=" * 60)
    print("ERP Demo Data Generator")
    print("=" * 60)
    print(f"目标生成数量：{args.count}")
    print(f"数据库：{DB_NAME}")
    print(f"数据库主机：{DB_HOST}:{DB_PORT}")
    print()

    conn = None

    try:
        conn = get_connection()

        print("✅ PostgreSQL 连接成功。")
        print()

        generate_data(conn, args.count)

        print()

        verify_data(conn, args.count)

        print()
        print("=" * 60)
        print("✅ 数据生成完成")
        print("=" * 60)

    except Exception as exc:
        print()
        print("=" * 60)
        print("❌ 数据生成失败")
        print("=" * 60)
        print(str(exc))
        raise

    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()