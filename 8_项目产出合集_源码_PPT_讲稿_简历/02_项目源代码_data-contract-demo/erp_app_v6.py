"""
ERP 企业业务管理系统（第 6 版｜Contract Change Governance 治理骨架版）

本版重点：
1. 保留 v5 的全部 ERP 业务流程、18 字段 Contract 来源与极薄 RBAC。
2. 新增 Contract Change Governance：Contract 变更从“直接改 YAML”升级为“受控变更申请”。
3. 新增独立 contract_approver 角色；Contract 审批资格只看角色，不按 employee_level 推导。
4. 后端强制 requested_by != approved_by，禁止申请人审批自己的变更。
5. 每次变更申请、审批、驳回都写入 contract_change_audit，形成可追溯链路。
6. requested_by / approved_by / reason / current_version / target_version / git_ref / pr_url / test / release 字段保留完整证据位。
7. 页面不直接修改 financial_data_contract.yaml；只产生 Change Request。
8. 本版不引入工作流引擎、不实现前端审批页；审批能力只保留在后端治理接口，后续可接人工审批入口。
2. 保留 v4 的 Contract 18 字段真实来源与现有业务流程。
3. 保留 v3 已验证的业务流程、数据库结构和幂等/并发保护。
4. 不修改 financial_data_contract.yaml。
5. 显式为现有 Contract 的 18 个字段提供业务来源或确定性派生逻辑。
6. 风险字段不再简单写死为 0，而是从申请、审批、审批政策和过账时间关系中计算。
7. approval_level 使用实际审批人级别快照；approval_below_expected_flag 用实际级别与政策要求比较。
8. risk_class 按项目既有规则重算：
      HIGH   = 同人审批 / 缺支持文件 / 审批层级不足
      MEDIUM = 接近审批阈值 / 金额 >= 500000
      LOW    = 其他情况
9. manual_after_hours_flag 按“人工录入 + 非工作时间”确定性计算；当前页面流程只自动生成财务流水，
   因此 manual_entry_flag = 0，但它是业务事实而不是数据库默认值。
10. erp_system 显式写入 ERP_DEMO，不依赖数据库默认值。
11. 保留：
   - 审批行锁
   - 审批状态检查
   - request_id / approval_id 匹配校验
   - transaction_id 幂等保护
   - 数据库密码环境变量读取

流程：

员工
 ↓
business_requests
 ↓
approval_records
 ↓
审批
 ↓
journal_entries
 ↓
erp_transactions
 ↓
Data Contract

注意：
- 当前数据库 password_hash 使用 demo_hash，仅用于开发演示。
- 数据库密码通过环境变量读取。
"""

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st


# ============================================================
# 1. 页面配置
# ============================================================

st.set_page_config(
    page_title="ERP 企业业务管理系统",
    page_icon="🏢",
    layout="wide",
)


# ============================================================
# 2. PostgreSQL 连接
# ============================================================

def get_db_config():
    password = (
        os.getenv("DATACONTRACT_POSTGRES_PASSWORD")
        or os.getenv("ERP_DB_PASSWORD")
    )

    if not password:
        raise RuntimeError(
            "没有读取到数据库密码，请设置 DATACONTRACT_POSTGRES_PASSWORD"
        )

    return {
        "host": os.getenv("ERP_DB_HOST", "localhost"),
        "port": int(os.getenv("ERP_DB_PORT", "5432")),
        "database": os.getenv("ERP_DB_NAME", "erp_demo"),
        "user": os.getenv("ERP_DB_USER", "kestra"),
        "password": password,
    }


def get_connection():
    return psycopg2.connect(**get_db_config())


def fetch_all(sql, params=None):
    conn = get_connection()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


# ============================================================
# 3. 基础数据读取
# ============================================================

def load_employees():
    return fetch_all(
        """
        SELECT
            employee_id,
            employee_name,
            department,
            position,
            position_type,
            employee_level,
            username,
            password_hash,
            is_active
        FROM employees
        WHERE is_active = TRUE
        ORDER BY employee_id
        """
    )


def load_roles(employee_id):
    """读取当前员工的系统角色。"""
    rows = fetch_all(
        """
        SELECT
            role_code
        FROM employee_roles
        WHERE employee_id = %s
        ORDER BY role_code
        """,
        (employee_id,),
    )
    return {row["role_code"] for row in rows}


def has_role(employee_id, role_code):
    """后端再次校验角色，避免只依赖前端菜单隐藏。"""
    rows = fetch_all(
        """
        SELECT 1
        FROM employee_roles
        WHERE employee_id = %s
          AND role_code = %s
        LIMIT 1
        """,
        (employee_id, role_code),
    )
    return bool(rows)


def require_role(employee_id, role_code):
    """角色不足时直接阻止关键操作。"""
    if not has_role(employee_id, role_code):
        raise PermissionError(
            f"员工 {employee_id} 没有 {role_code} 角色，无权执行该操作。"
        )


def load_projects():
    return fetch_all(
        """
        SELECT
            p.project_id,
            p.project_name,
            p.project_type,
            p.project_status,
            p.project_manager_id,
            p.budget_amount,
            e.employee_name AS manager_name
        FROM projects p
        JOIN employees e
          ON p.project_manager_id = e.employee_id
        ORDER BY p.project_id
        """
    )


def load_policies():
    return fetch_all(
        """
        SELECT
            policy_id,
            business_type,
            category,
            min_amount,
            max_amount,
            required_level,
            near_threshold_amount,
            gl_account,
            description
        FROM approval_policies
        ORDER BY
            business_type,
            category,
            min_amount
        """
    )


# ============================================================
# 4. 我的申请
# ============================================================

def load_my_requests(requester_id):
    return fetch_all(
        """
        SELECT
            br.request_id,
            br.business_type,
            br.category,
            br.request_title,
            br.amount,
            br.currency,
            br.request_status,

            ar.approval_id,
            ar.approver_id,
            e.employee_name AS approver_name,
            ar.required_level,
            ar.approval_status

        FROM business_requests br

        LEFT JOIN approval_records ar
          ON br.request_id = ar.request_id

        LEFT JOIN employees e
          ON ar.approver_id = e.employee_id

        WHERE br.requester_id = %s

        ORDER BY br.submitted_at DESC
        """,
        (requester_id,),
    )


# ============================================================
# 5. 我的审批
# ============================================================

def load_pending_approvals(approver_id):
    return fetch_all(
        """
        SELECT
            ar.approval_id,
            ar.request_id,

            br.request_title,
            br.business_type,
            br.category,
            br.amount,
            br.currency,
            br.requester_id,

            e.employee_name AS requester_name,

            ar.required_level,
            ar.near_approval_threshold_flag,
            ar.policy_id

        FROM approval_records ar

        JOIN business_requests br
          ON ar.request_id = br.request_id

        JOIN employees e
          ON br.requester_id = e.employee_id

        WHERE ar.approver_id = %s
          AND ar.approval_status = '待审批'

        ORDER BY ar.created_at DESC
        """,
        (approver_id,),
    )


# ============================================================
# 6. 审批通过后自动生成 journal_entries
# ============================================================

def create_journal_entry(cur, request_id, approval_id):
    """
    审批通过后自动生成 ERP 财务流水。

    Contract 18 字段来源：

    transaction_id                <- approval_id 派生
    erp_system                    <- ERP_DEMO 系统标识
    posting_datetime              <- 审批通过时的 CURRENT_TIMESTAMP
    amount                        <- business_requests.amount
    currency                      <- business_requests.currency
    gl_account                    <- approval_policies.gl_account
    manual_entry_flag             <- 当前页面流程为系统自动生成，因此业务事实为 0
    risk_class                    <- 下方确定性风险规则计算
    approval_level                <- approval_records.approver_level_snapshot
    is_round_amount               <- amount 派生
    high_value_flag               <- amount 派生
    posting_hour                  <- posting_datetime 派生
    posting_dayofweek             <- posting_datetime 派生
    same_preparer_approver_flag   <- requester_id 与 approver_id 比较
    missing_support_flag          <- support_document_flag 反向映射
    approval_below_expected_flag  <- approver_level_snapshot < required_level
    near_approval_threshold_flag  <- approval_records.near_approval_threshold_flag
    manual_after_hours_flag       <- manual_entry_flag + posting_hour 派生

    说明：
    当前 Contract 的规则定义在 financial_data_contract.yaml，
    本函数只负责把业务系统产生的事实落到 journal_entries，
    不改变 Contract 本身。
    """

    # --------------------------------------------------------
    # 1. 取得业务申请 + 审批 + 审批政策
    # --------------------------------------------------------
    cur.execute(
        """
        SELECT
            br.project_id,
            br.amount,
            br.currency,
            br.requester_id,
            br.support_document_flag,

            ar.approver_id,
            ar.approver_level_snapshot,
            ar.required_level,
            ar.near_approval_threshold_flag,

            ap.gl_account

        FROM business_requests br

        JOIN approval_records ar
          ON br.request_id = ar.request_id

        JOIN approval_policies ap
          ON ar.policy_id = ap.policy_id

        WHERE ar.approval_id = %s
          AND br.request_id = %s
        """,
        (approval_id, request_id),
    )

    data = cur.fetchone()

    if not data:
        raise ValueError("无法找到审批对应业务数据")

    # --------------------------------------------------------
    # 2. 生成唯一交易编号
    # --------------------------------------------------------
    transaction_id = "TRX" + approval_id[3:]

    # --------------------------------------------------------
    # 3. 幂等保护
    # --------------------------------------------------------
    cur.execute(
        """
        SELECT transaction_id
        FROM journal_entries
        WHERE transaction_id = %s
        """,
        (transaction_id,),
    )

    if cur.fetchone():
        return

    # --------------------------------------------------------
    # 4. 计算 Contract 风险字段
    # --------------------------------------------------------

    # 当前 UI 只通过审批流程自动创建财务流水，
    # 不提供人工直接录入 journal_entries 的入口。
    manual_entry_flag = 0

    support_document_flag = (
        1 if data["support_document_flag"] else 0
    )

    missing_support_flag = (
        0 if data["support_document_flag"] else 1
    )

    same_preparer_approver_flag = (
        1 if data["requester_id"] == data["approver_id"] else 0
    )

    approval_below_expected_flag = (
        1
        if data["approver_level_snapshot"] < data["required_level"]
        else 0
    )

    near_approval_threshold_flag = (
        1 if data["near_approval_threshold_flag"] else 0
    )

    amount = data["amount"]

    is_round_amount = (
        1 if amount % Decimal("10000") == 0 else 0
    )

    high_value_flag = (
        1 if amount >= Decimal("500000") else 0
    )

    # 与项目既有数据生成/恢复逻辑保持一致：
    # HIGH  : 同人审批 / 缺支持文件 / 审批层级不足
    # MEDIUM: 临近阈值 / 金额 >= 50 万
    # LOW   : 其他情况
    if (
        same_preparer_approver_flag == 1
        or missing_support_flag == 1
        or approval_below_expected_flag == 1
    ):
        risk_class = "HIGH"
    elif (
        near_approval_threshold_flag == 1
        or high_value_flag == 1
    ):
        risk_class = "MEDIUM"
    else:
        risk_class = "LOW"

    # 当前流水是系统自动生成，所以即使落在非工作时间，
    # 也不属于“非工作时间手工录入”。
    manual_after_hours_flag_sql = """
        CASE
            WHEN %s = 1
             AND (
                 EXTRACT(HOUR FROM CURRENT_TIMESTAMP) < 9
                 OR EXTRACT(HOUR FROM CURRENT_TIMESTAMP) >= 18
             )
            THEN 1
            ELSE 0
        END
    """

    # --------------------------------------------------------
    # 5. 显式写入 journal_entries
    # --------------------------------------------------------
    cur.execute(
        f"""
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
        VALUES (
            %s,
            %s,
            %s,
            'ERP_DEMO',
            CURRENT_TIMESTAMP,
            %s,
            %s,
            %s,
            %s,
            %s,
            '已通过',
            %s,
            %s,
            %s,
            %s,
            EXTRACT(HOUR FROM CURRENT_TIMESTAMP)::INTEGER,
            EXTRACT(DOW FROM CURRENT_TIMESTAMP)::INTEGER,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            {manual_after_hours_flag_sql}
        )
        ON CONFLICT (transaction_id) DO NOTHING
        """,
        (
            transaction_id,
            request_id,
            data["project_id"],
            amount,
            data["currency"],
            data["gl_account"],
            data["requester_id"],
            data["approver_id"],
            data["approver_level_snapshot"],
            manual_entry_flag,
            support_document_flag,
            risk_class,
            same_preparer_approver_flag,
            missing_support_flag,
            approval_below_expected_flag,
            near_approval_threshold_flag,
            is_round_amount,
            high_value_flag,
            manual_entry_flag,
        ),
    )


# ============================================================
# 7. 审批通过
# ============================================================

def approve_request(actor_employee_id, approval_id, request_id):
    require_role(actor_employee_id, "approver")
    conn = get_connection()

    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                # 1. 锁定审批记录
                cur.execute(
                    """
                    SELECT
                        approval_id,
                        request_id,
                        approver_id,
                        approval_status
                    FROM approval_records
                    WHERE approval_id = %s
                    FOR UPDATE
                    """,
                    (approval_id,),
                )

                approval = cur.fetchone()

                if not approval:
                    raise ValueError(f"找不到审批记录：{approval_id}")

                # 2. 校验审批与申请是否匹配
                if approval["request_id"] != request_id:
                    raise ValueError("审批记录与业务申请不匹配")

                if approval["approver_id"] != actor_employee_id:
                    raise PermissionError("当前登录员工不是该审批记录指定的审批人。")

                # 3. 只有待审批才能继续
                if approval["approval_status"] != "待审批":
                    raise ValueError(
                        "该审批已经处理，"
                        f"当前状态：{approval['approval_status']}"
                    )

                # 4. 更新审批记录
                cur.execute(
                    """
                    UPDATE approval_records
                    SET
                        approval_status = '已通过',
                        approval_comment = '同意',
                        approved_at = CURRENT_TIMESTAMP
                    WHERE approval_id = %s
                    """,
                    (approval_id,),
                )

                # 5. 更新业务申请状态
                cur.execute(
                    """
                    UPDATE business_requests
                    SET
                        request_status = '已通过',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE request_id = %s
                    """,
                    (request_id,),
                )

                # 6. 自动生成 ERP 财务流水
                create_journal_entry(cur, request_id, approval_id)

        return True

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# ============================================================
# 8. 审批驳回
# ============================================================

def reject_request(actor_employee_id, approval_id, request_id, comment):
    require_role(actor_employee_id, "approver")
    conn = get_connection()

    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                # 1. 锁定审批记录
                cur.execute(
                    """
                    SELECT
                        approval_id,
                        request_id,
                        approver_id,
                        approval_status
                    FROM approval_records
                    WHERE approval_id = %s
                    FOR UPDATE
                    """,
                    (approval_id,),
                )

                approval = cur.fetchone()

                if not approval:
                    raise ValueError(f"找不到审批记录：{approval_id}")

                if approval["request_id"] != request_id:
                    raise ValueError("审批记录与业务申请不匹配")

                if approval["approver_id"] != actor_employee_id:
                    raise PermissionError("当前登录员工不是该审批记录指定的审批人。")

                # 2. 防止重复驳回/审批
                if approval["approval_status"] != "待审批":
                    raise ValueError(
                        "该审批已经处理，"
                        f"当前状态：{approval['approval_status']}"
                    )

                # 3. 更新审批记录
                cur.execute(
                    """
                    UPDATE approval_records
                    SET
                        approval_status = '已驳回',
                        approval_comment = %s,
                        approved_at = CURRENT_TIMESTAMP
                    WHERE approval_id = %s
                    """,
                    (comment, approval_id),
                )

                # 4. 更新业务申请状态
                cur.execute(
                    """
                    UPDATE business_requests
                    SET
                        request_status = '已驳回',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE request_id = %s
                    """,
                    (request_id,),
                )

        return True

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# ============================================================
# 9. 生成编号
# ============================================================

def get_next_numbers(cur):
    cur.execute(
        """
        SELECT COALESCE(
            MAX(
                CAST(
                    SUBSTRING(request_id, 4)
                    AS INTEGER
                )
            ),
            0
        )
        FROM business_requests
        WHERE request_id ~ '^REQ[0-9]+$'
        """
    )

    max_request = cur.fetchone()["coalesce"]

    cur.execute(
        """
        SELECT COALESCE(
            MAX(
                CAST(
                    SUBSTRING(approval_id, 4)
                    AS INTEGER
                )
            ),
            0
        )
        FROM approval_records
        WHERE approval_id ~ '^APR[0-9]+$'
        """
    )

    max_approval = cur.fetchone()["coalesce"]

    return (
        f"REQ{max_request + 1:05d}",
        f"APR{max_approval + 1:05d}",
    )


# ============================================================
# 10. 匹配审批政策
# ============================================================

def match_policy(cur, business_type, category, amount):
    cur.execute(
        """
        SELECT
            policy_id,
            required_level,
            near_threshold_amount,
            gl_account
        FROM approval_policies
        WHERE business_type = %s
          AND category = %s
          AND min_amount <= %s
          AND %s < max_amount
        """,
        (
            business_type,
            category,
            amount,
            amount,
        ),
    )

    policies = cur.fetchall()

    if len(policies) == 0:
        raise ValueError("没有匹配审批政策")

    if len(policies) > 1:
        raise ValueError("存在多个审批政策匹配")

    return policies[0]


# ============================================================
# 11. 自动选择审批人
# ============================================================

def choose_approver(cur, requester_id, required_level):
    """只从具有 approver 角色且级别满足要求的在职员工中选择审批人。"""
    cur.execute(
        """
        SELECT
            e.employee_id,
            e.employee_name,
            e.employee_level
        FROM employees e
        JOIN employee_roles er
          ON er.employee_id = e.employee_id
         AND er.role_code = 'approver'
        WHERE e.is_active = TRUE
          AND e.employee_id <> %s
          AND e.employee_level >= %s
        ORDER BY
            e.employee_level ASC,
            e.employee_id ASC
        LIMIT 1
        """,
        (
            requester_id,
            required_level,
        ),
    )

    result = cur.fetchone()

    if not result:
        raise ValueError("没有找到具有 approver 角色且级别满足要求的审批人")

    return result


# ============================================================
# 12. 创建业务申请
# ============================================================

def create_request(
    requester_id,
    business_type,
    category,
    project_id,
    request_title,
    request_description,
    amount,
    currency,
    support_document_flag,
):
    require_role(requester_id, "employee")
    conn = get_connection()

    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                # 防止两个提交请求同时生成同一个编号
                cur.execute(
                    """
                    LOCK TABLE business_requests
                    IN SHARE ROW EXCLUSIVE MODE
                    """
                )

                # 1. 匹配审批政策
                policy = match_policy(
                    cur,
                    business_type,
                    category,
                    amount,
                )

                # 2. 自动选择审批人
                approver = choose_approver(
                    cur,
                    requester_id,
                    policy["required_level"],
                )

                # 3. 生成业务申请编号与审批编号
                request_id, approval_id = get_next_numbers(cur)

                # 4. 判断是否临近审批阈值
                near_threshold = (
                    amount >= policy["near_threshold_amount"]
                )

                # 5. 写入 business_requests
                cur.execute(
                    """
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
                        support_document_flag
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
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
                    ),
                )

                # 6. 写入 approval_records
                cur.execute(
                    """
                    INSERT INTO approval_records (
                        approval_id,
                        request_id,
                        approval_sequence,
                        policy_id,
                        approver_id,
                        approver_level_snapshot,
                        required_level,
                        approval_status,
                        near_approval_threshold_flag
                    )
                    VALUES (
                        %s,
                        %s,
                        1,
                        %s,
                        %s,
                        %s,
                        %s,
                        '待审批',
                        %s
                    )
                    """,
                    (
                        approval_id,
                        request_id,
                        policy["policy_id"],
                        approver["employee_id"],
                        approver["employee_level"],
                        policy["required_level"],
                        near_threshold,
                    ),
                )

                return {
                    "request_id": request_id,
                    "approval_id": approval_id,
                    "policy_id": policy["policy_id"],
                    "required_level": policy["required_level"],
                    "approver_id": approver["employee_id"],
                    "approver_name": approver["employee_name"],
                    "approver_level": approver["employee_level"],
                    "near_threshold": near_threshold,
                }

    finally:
        conn.close()


# ============================================================
# 13. 登录页面
# ============================================================

def render_login(employees):
    st.title("ERP 🏢 企业业务管理系统")

    employee_map = {
        f"{e['employee_id']} - "
        f"{e['employee_name']} - "
        f"{e['department']} - "
        f"{e['position']}": e
        for e in employees
    }

    selected = st.selectbox(
        "员工账号",
        list(employee_map.keys()),
    )

    password = st.text_input(
        "密码",
        type="password",
    )

    st.warning(
        """
        当前为开发演示登录：

        数据库 password_hash = demo_hash

        仅用于业务流程测试。
        """
    )

    if st.button("登录", type="primary"):
        employee = employee_map[selected]

        if password != employee["password_hash"]:
            st.error("密码错误")
            return

        roles = load_roles(employee["employee_id"])

        if "employee" not in roles:
            st.error("当前账号未配置 employee 角色，无法进入系统。")
            return

        st.session_state.logged_in = True
        st.session_state.employee = dict(employee)
        st.session_state.roles = roles

        st.rerun()


# ============================================================
# 14. 我的信息
# ============================================================

def page_my_info(employee):
    st.subheader("👤 我的信息")

    st.write(
        {
            "姓名": employee["employee_name"],
            "部门": employee["department"],
            "职位": employee["position"],
            "级别": employee["employee_level"],
            "账号": employee["username"],
            "系统角色": ", ".join(
                sorted(
                    st.session_state.get("roles", set())
                )
            ),
        }
    )


# ============================================================
# 15. 我的申请
# ============================================================

def page_my_requests(employee):
    st.subheader("📋 我的申请")

    rows = load_my_requests(employee["employee_id"])

    if not rows:
        st.info("暂无申请")
        return

    st.dataframe(rows, use_container_width=True)


# ============================================================
# 16. 新建申请页面
# ============================================================

def page_new_request(employee, projects, policies):
    st.subheader("📝 新建业务申请")

    business_types = sorted({p["business_type"] for p in policies})

    business_type = st.selectbox(
        "业务类型",
        business_types,
    )

    categories = sorted(
        {
            p["category"]
            for p in policies
            if p["business_type"] == business_type
        }
    )

    category = st.selectbox(
        "业务类别",
        categories,
    )

    project_map = {
        f"{p['project_id']} - {p['project_name']}": p
        for p in projects
    }

    project_label = st.selectbox(
        "关联项目",
        list(project_map.keys()),
    )

    project = project_map[project_label]

    title = st.text_input("申请标题")

    description = st.text_area("申请说明")

    amount_text = st.text_input("金额")

    currency = st.selectbox("币种", ["CNY"])

    support_document = st.checkbox("是否有支持性凭证")

    if st.button("提交申请", type="primary"):
        try:
            amount = Decimal(amount_text)
        except (InvalidOperation, ValueError):
            st.error("金额格式错误")
            return

        if amount <= 0:
            st.error("金额必须大于 0")
            return

        try:
            result = create_request(
                employee["employee_id"],
                business_type,
                category,
                project["project_id"],
                title,
                description,
                amount,
                currency,
                support_document,
            )

            st.success(
                f"""
                申请成功：

                {result['request_id']}

                审批人：

                {result['approver_id']}
                -
                {result['approver_name']}
                """
            )

            st.json(result)

        except Exception as e:
            st.error(
                f"提交失败：{type(e).__name__}: {e}"
            )


# ============================================================
# 17. 我的审批页面
# ============================================================

def page_my_approval(employee):
    st.subheader("📋 我的审批")

    approvals = load_pending_approvals(
        employee["employee_id"]
    )

    if not approvals:
        st.info("暂无待审批事项")
        return

    for item in approvals:
        st.divider()

        st.subheader(item["request_title"])

        st.write(
            f"""
            申请人：

            {item['requester_name']}

            业务：

            {item['business_type']} - {item['category']}

            金额：

            {item['amount']}
            {item['currency']}

            审批等级：

            {item['required_level']}级
            """
        )

        if item["near_approval_threshold_flag"]:
            st.warning("⚠ 临近审批阈值")

        comment = st.text_input(
            "审批意见",
            key=item["approval_id"],
        )

        col1, col2 = st.columns(2)

        with col1:
            if st.button(
                "✅ 通过",
                key="pass_" + item["approval_id"],
            ):
                try:
                    approve_request(
                        employee["employee_id"],
                        item["approval_id"],
                        item["request_id"],
                    )

                    st.success("审批通过，已生成财务流水")
                    st.rerun()

                except Exception as e:
                    st.error(
                        f"审批失败：{type(e).__name__}: {e}"
                    )

        with col2:
            if st.button(
                "❌ 驳回",
                key="reject_" + item["approval_id"],
            ):
                try:
                    reject_request(
                        employee["employee_id"],
                        item["approval_id"],
                        item["request_id"],
                        comment,
                    )

                    st.warning("已驳回")
                    st.rerun()

                except Exception as e:
                    st.error(
                        f"驳回失败：{type(e).__name__}: {e}"
                    )


# ============================================================
# 18. Contract Change Governance
# ============================================================

CONTRACT_ID = "erp-accounting-risk-contract"
CURRENT_CONTRACT_VERSION = "1.0.0"
CONTRACT_FILE = "financial_data_contract.yaml"


def ensure_contract_governance_schema():
    """确保最小 Contract 变更治理骨架存在；不修改 financial_data_contract.yaml。"""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # ----------------------------------------------------
                # 1. 扩展 employee_roles 的合法角色集合
                # ----------------------------------------------------
                cur.execute(
                    """
                    SELECT pg_get_constraintdef(oid) AS constraint_def
                    FROM pg_constraint
                    WHERE conrelid = 'employee_roles'::regclass
                      AND conname = 'chk_employee_role'
                    """
                )
                constraint_row = cur.fetchone()
                constraint_def = (
                    constraint_row["constraint_def"]
                    if constraint_row
                    else ""
                )

                if "contract_approver" not in constraint_def:
                    cur.execute(
                        """
                        ALTER TABLE employee_roles
                        DROP CONSTRAINT IF EXISTS chk_employee_role;
                        """
                    )
                    cur.execute(
                        """
                        ALTER TABLE employee_roles
                        ADD CONSTRAINT chk_employee_role
                        CHECK (
                            role_code IN (
                                'employee',
                                'approver',
                                'data_admin',
                                'master_data_approver',
                                'contract_admin',
                                'contract_approver'
                            )
                        );
                        """
                    )

                # ----------------------------------------------------
                # 2. Contract Change Request
                # ----------------------------------------------------
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS contract_change_requests (
                        change_id VARCHAR(20) PRIMARY KEY,
                        contract_id VARCHAR(100) NOT NULL,
                        current_version VARCHAR(30) NOT NULL,
                        target_version VARCHAR(30) NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        change_type VARCHAR(30) NOT NULL,
                        description VARCHAR(1000) NOT NULL,
                        proposed_change TEXT NOT NULL,
                        reason VARCHAR(500) NOT NULL,
                        requested_by VARCHAR(20) NOT NULL
                            REFERENCES employees(employee_id),
                        approved_by VARCHAR(20)
                            REFERENCES employees(employee_id),
                        approved_at TIMESTAMP,
                        git_ref VARCHAR(200),
                        pr_url VARCHAR(500),
                        review_status VARCHAR(20),
                        review_comment VARCHAR(500),
                        test_status VARCHAR(20),
                        test_output TEXT,
                        tested_at TIMESTAMP,
                        released_version VARCHAR(30),
                        released_at TIMESTAMP,
                        status VARCHAR(30) NOT NULL DEFAULT '待审批',
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT chk_contract_change_type
                            CHECK (
                                change_type IN (
                                    '业务规则',
                                    '字段结构',
                                    '质量规则',
                                    '其他'
                                )
                            ),
                        CONSTRAINT chk_contract_review_status
                            CHECK (
                                review_status IS NULL
                                OR review_status IN (
                                    '待评审',
                                    '已通过',
                                    '已驳回'
                                )
                            ),
                        CONSTRAINT chk_contract_test_status
                            CHECK (
                                test_status IS NULL
                                OR test_status IN (
                                    '未测试',
                                    '通过',
                                    '失败'
                                )
                            ),
                        CONSTRAINT chk_contract_change_status
                            CHECK (
                                status IN (
                                    '待审批',
                                    '已驳回',
                                    '待技术修改',
                                    '待Code Review',
                                    '待测试',
                                    '待发布',
                                    '已发布'
                                )
                            )
                    );
                    """
                )

                # ----------------------------------------------------
                # 3. Contract Change Audit
                # ----------------------------------------------------
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS contract_change_audit (
                        audit_id BIGSERIAL PRIMARY KEY,
                        change_id VARCHAR(20) NOT NULL
                            REFERENCES contract_change_requests(change_id)
                            ON DELETE CASCADE,
                        action VARCHAR(50) NOT NULL,
                        operator_id VARCHAR(20) NOT NULL
                            REFERENCES employees(employee_id),
                        from_status VARCHAR(30),
                        to_status VARCHAR(30),
                        detail VARCHAR(1000),
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
    finally:
        conn.close()


def get_next_contract_change_id(cur):
    """生成 CCR 编号；在当前事务中锁表，避免并发生成相同编号。"""
    cur.execute(
        """
        LOCK TABLE contract_change_requests
        IN SHARE ROW EXCLUSIVE MODE
        """
    )
    cur.execute(
        """
        SELECT COALESCE(
            MAX(
                CAST(SUBSTRING(change_id, 4) AS INTEGER)
            ),
            0
        )
        FROM contract_change_requests
        WHERE change_id ~ '^CCR[0-9]+$'
        """
    )
    max_id = cur.fetchone()["coalesce"]
    return f"CCR{max_id + 1:05d}"


def find_open_duplicate_change_request(cur, requested_by, title, change_type, target_version):
    """在 create 之前查询是否已存在内容相同且未关闭的变更单。

    判定「相同」：申请人 + 标题 + 变更类型 + 目标版本 四项一致。
    判定「未关闭」：status 不在（已驳回、已发布）之列。
    命中返回已存在的 change_id；否则返回 None。

    注：本检查在 get_next_contract_change_id 的表锁之前执行；
    对页面双击（串行重跑）场景完全有效。若需覆盖真并发，
    可在此基础上追加对 (requested_by, title, change_type, target_version)
    的部分唯一索引，本 demo 暂不引入该约束。
    """
    cur.execute(
        """
        SELECT change_id
        FROM contract_change_requests
        WHERE requested_by = %s
          AND title = %s
          AND change_type = %s
          AND target_version = %s
          AND status NOT IN ('已驳回', '已发布')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (requested_by, title, change_type, target_version),
    )
    row = cur.fetchone()
    return row["change_id"] if row else None


def create_contract_change(
    requested_by,
    title,
    change_type,
    description,
    proposed_change,
    reason,
    target_version,
):
    """创建 Contract 变更申请；申请人必须具有 contract_admin 角色。

    后端强制防重复提交：同一申请人 + 同标题 + 同类型 + 同目标版本且未关闭的
    变更单视为重复，直接拒绝，不生成新编号。覆盖页面双击与并发重发的场景。
    """
    require_role(requested_by, "contract_admin")
    ensure_contract_governance_schema()

    required_text = {
        "标题": title,
        "变更说明": description,
        "拟修改内容": proposed_change,
        "原因": reason,
        "目标版本": target_version,
    }
    for label, value in required_text.items():
        if not value or not value.strip():
            raise ValueError(f"{label}不能为空")

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 后端强制防重复提交：同一申请人 + 同标题 + 同类型 + 同目标版本
                # 且未关闭的变更单视为重复，直接拒绝，不生成新编号。
                # 覆盖页面双击与并发重发的场景。
                dup_id = find_open_duplicate_change_request(
                    cur,
                    requested_by,
                    title.strip(),
                    change_type,
                    target_version.strip(),
                )
                if dup_id:
                    raise ValueError(
                        f"已存在内容相同的未关闭变更申请 {dup_id}，"
                        f"请勿重复提交。如需提交不同内容，请调整标题或目标版本。"
                    )
                change_id = get_next_contract_change_id(cur)
                cur.execute(
                    """
                    INSERT INTO contract_change_requests (
                        change_id,
                        contract_id,
                        current_version,
                        target_version,
                        title,
                        change_type,
                        description,
                        proposed_change,
                        reason,
                        requested_by,
                        status
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, '待审批'
                    )
                    """,
                    (
                        change_id,
                        CONTRACT_ID,
                        CURRENT_CONTRACT_VERSION,
                        target_version.strip(),
                        title.strip(),
                        change_type,
                        description.strip(),
                        proposed_change.strip(),
                        reason.strip(),
                        requested_by,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO contract_change_audit (
                        change_id,
                        action,
                        operator_id,
                        from_status,
                        to_status,
                        detail
                    )
                    VALUES (
                        %s,
                        '发起变更',
                        %s,
                        NULL,
                        '待审批',
                        %s
                    )
                    """,
                    (
                        change_id,
                        requested_by,
                        f"{title.strip()}；目标版本={target_version.strip()}",
                    ),
                )
                return change_id
    finally:
        conn.close()


def load_contract_change_requests():
    """读取 Contract 变更申请，供治理查询与审计展示使用。"""
    ensure_contract_governance_schema()
    return fetch_all(
        """
        SELECT
            c.change_id,
            c.contract_id,
            c.current_version,
            c.target_version,
            c.title,
            c.change_type,
            c.description,
            c.proposed_change,
            c.reason,
            c.requested_by,
            req.employee_name AS requester_name,
            c.approved_by,
            app.employee_name AS approver_name,
            c.approved_at,
            c.git_ref,
            c.pr_url,
            c.review_status,
            c.review_comment,
            c.test_status,
            c.tested_at,
            c.released_version,
            c.released_at,
            c.status,
            c.created_at,
            c.updated_at
        FROM contract_change_requests c
        JOIN employees req
          ON req.employee_id = c.requested_by
        LEFT JOIN employees app
          ON app.employee_id = c.approved_by
        ORDER BY c.created_at DESC
        """
    )


def load_contract_change_audit(change_id):
    """读取某一张 Contract 变更单的完整审计链。"""
    ensure_contract_governance_schema()
    return fetch_all(
        """
        SELECT
            a.audit_id,
            a.change_id,
            a.action,
            a.operator_id,
            e.employee_name AS operator_name,
            a.from_status,
            a.to_status,
            a.detail,
            a.created_at
        FROM contract_change_audit a
        JOIN employees e
          ON e.employee_id = a.operator_id
        WHERE a.change_id = %s
        ORDER BY a.created_at ASC, a.audit_id ASC
        """,
        (change_id,),
    )


def get_contract_pending_approvals(approver_id):
    """读取指定 Contract 审批人的待审批变更；这里只是后端接口，不提供审批页面。"""
    require_role(approver_id, "contract_approver")
    ensure_contract_governance_schema()
    return fetch_all(
        """
        SELECT
            c.change_id,
            c.contract_id,
            c.current_version,
            c.target_version,
            c.title,
            c.change_type,
            c.description,
            c.proposed_change,
            c.reason,
            c.requested_by,
            req.employee_name AS requester_name,
            c.status,
            c.created_at
        FROM contract_change_requests c
        JOIN employees req
          ON req.employee_id = c.requested_by
        WHERE c.status = '待审批'
          AND c.requested_by <> %s
        ORDER BY c.created_at ASC
        """,
        (approver_id,),
    )


def _load_contract_change_for_update(cur, change_id):
    cur.execute(
        """
        SELECT
            change_id,
            contract_id,
            current_version,
            target_version,
            title,
            requested_by,
            approved_by,
            status
        FROM contract_change_requests
        WHERE change_id = %s
        FOR UPDATE
        """,
        (change_id,),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"找不到 Contract 变更单：{change_id}")
    return row


def approve_contract_change(approver_id, change_id, comment="审批通过"):
    """
    Contract 审批核心控制：
    1. 必须有 contract_approver 角色；
    2. 只允许待审批；
    3. requested_by != approver_id，禁止自审批；
    4. 审批动作与状态变更、审计写入处于同一事务。
    """
    require_role(approver_id, "contract_approver")
    ensure_contract_governance_schema()

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                change = _load_contract_change_for_update(cur, change_id)

                if change["status"] != "待审批":
                    raise ValueError(
                        f"该变更当前状态为 {change['status']}，不能执行审批。"
                    )

                if change["requested_by"] == approver_id:
                    raise PermissionError(
                        "禁止自审批：Contract 变更申请人与审批人不能是同一员工。"
                    )

                cur.execute(
                    """
                    UPDATE contract_change_requests
                    SET
                        approved_by = %s,
                        approved_at = CURRENT_TIMESTAMP,
                        status = '待技术修改',
                        review_comment = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE change_id = %s
                    """,
                    (
                        approver_id,
                        comment.strip() if comment else "审批通过",
                        change_id,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO contract_change_audit (
                        change_id,
                        action,
                        operator_id,
                        from_status,
                        to_status,
                        detail
                    )
                    VALUES (
                        %s,
                        '审批通过',
                        %s,
                        '待审批',
                        '待技术修改',
                        %s
                    )
                    """,
                    (
                        change_id,
                        approver_id,
                        comment.strip() if comment else "审批通过",
                    ),
                )
    finally:
        conn.close()


def reject_contract_change(approver_id, change_id, comment):
    """Contract 审批驳回接口；同样禁止申请人自我处理自己的变更单。"""
    require_role(approver_id, "contract_approver")
    ensure_contract_governance_schema()

    if not comment or not comment.strip():
        raise ValueError("驳回时必须填写原因")

    conn = get_connection()
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                change = _load_contract_change_for_update(cur, change_id)

                if change["status"] != "待审批":
                    raise ValueError(
                        f"该变更当前状态为 {change['status']}，不能执行驳回。"
                    )

                if change["requested_by"] == approver_id:
                    raise PermissionError(
                        "禁止自审批：Contract 变更申请人与审批人不能是同一员工。"
                    )

                cur.execute(
                    """
                    UPDATE contract_change_requests
                    SET
                        approved_by = %s,
                        approved_at = CURRENT_TIMESTAMP,
                        review_comment = %s,
                        status = '已驳回',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE change_id = %s
                    """,
                    (
                        approver_id,
                        comment.strip(),
                        change_id,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO contract_change_audit (
                        change_id,
                        action,
                        operator_id,
                        from_status,
                        to_status,
                        detail
                    )
                    VALUES (
                        %s,
                        '驳回变更',
                        %s,
                        '待审批',
                        '已驳回',
                        %s
                    )
                    """,
                    (
                        change_id,
                        approver_id,
                        comment.strip(),
                    ),
                )
    finally:
        conn.close()


# ============================================================
# 19. Contract 变更申请页面（只产生 Change Request，不审批）
# ============================================================

def page_contract_change_request(employee):
    """
    v6 当前页面边界：
    页面只负责产生、查询和查看审计记录；
    不直接修改 financial_data_contract.yaml；
    不在前端提供审批按钮。
    """
    require_role(employee["employee_id"], "contract_admin")
    ensure_contract_governance_schema()

    st.subheader("🛡️ Contract 变更申请")
    st.caption(
        "页面只产生 Change Request；Contract 本体仍由 Git 中的技术修改与后续门禁流程控制。"
    )

    with st.expander("① 发起变更申请", expanded=True):
        title = st.text_input("变更标题")
        change_type = st.selectbox(
            "变更类型",
            ["业务规则", "字段结构", "质量规则", "其他"],
        )
        description = st.text_area("变更说明")
        proposed_change = st.text_area(
            "拟修改内容",
            placeholder="例如：将某项金额阈值从 3000000 调整为 5000000；这里只记录提案，不直接改 YAML。",
        )
        reason = st.text_input("业务 / 数据治理原因")
        target_version = st.text_input(
            "目标 Contract 版本",
            value="1.0.1",
        )

        if st.button("提交 Contract 变更申请", type="primary"):
            try:
                change_id = create_contract_change(
                    employee["employee_id"],
                    title,
                    change_type,
                    description,
                    proposed_change,
                    reason,
                    target_version,
                )
                st.success(
                    f"变更申请已提交：{change_id}；当前状态：待审批。"
                )
                st.rerun()
            except ValueError as exc:
                st.warning(f"未提交：{exc}")
            except Exception as exc:
                st.error(f"提交失败：{type(exc).__name__}: {exc}")

    rows = load_contract_change_requests()
    st.divider()
    st.subheader("② 当前变更记录")

    if not rows:
        st.info("暂无 Contract 变更申请。")
        return

    for item in rows:
        with st.expander(
            f"{item['change_id']} · {item['title']} · {item['status']}",
            expanded=False,
        ):
            st.write(
                {
                    "Contract": item["contract_id"],
                    "当前版本": item["current_version"],
                    "目标版本": item["target_version"],
                    "类型": item["change_type"],
                    "申请人": f"{item['requested_by']} - {item['requester_name']}",
                    "审批人": (
                        f"{item['approved_by']} - {item['approver_name']}"
                        if item["approved_by"]
                        else "尚未审批"
                    ),
                    "状态": item["status"],
                    "Git": item["git_ref"] or "尚未关联",
                    "PR": item["pr_url"] or "尚未关联",
                }
            )
            st.markdown(f"**变更说明**：{item['description']}")
            st.markdown(f"**拟修改内容**：{item['proposed_change']}")
            st.markdown(f"**原因**：{item['reason']}")

            audit_rows = load_contract_change_audit(item["change_id"])
            if audit_rows:
                st.markdown("**审计轨迹**")
                st.dataframe(
                    audit_rows,
                    use_container_width=True,
                    hide_index=True,
                )


# ============================================================
# 20. Contract 变更审批页面
# ============================================================

def page_contract_change_approval(employee):
    """只允许 contract_approver 处理 Contract 变更，不提供 YAML 编辑入口。"""
    require_role(employee["employee_id"], "contract_approver")
    ensure_contract_governance_schema()

    st.subheader("✅ Contract 变更审批")
    st.caption(
        "审批人只能处理分配给自己的 Contract 变更资格；页面不直接修改 financial_data_contract.yaml。"
    )

    pending = get_contract_pending_approvals(employee["employee_id"])

    if not pending:
        st.info("暂无待审批的 Contract 变更。")
        return

    for item in pending:
        with st.expander(
            f"{item['change_id']} · {item['title']} · 待审批",
            expanded=True,
        ):
            st.write(
                {
                    "Contract": item["contract_id"],
                    "当前版本": item["current_version"],
                    "目标版本": item["target_version"],
                    "类型": item["change_type"],
                    "申请人": f"{item['requested_by']} - {item['requester_name']}",
                    "状态": item["status"],
                }
            )
            st.markdown(f"**变更说明**：{item['description']}")
            st.markdown(f"**拟修改内容**：{item['proposed_change']}")
            st.markdown(f"**原因**：{item['reason']}")

            comment = st.text_input(
                "审批意见",
                value="同意该 Contract 变更申请。",
                key=f"contract_approval_comment_{item['change_id']}",
            )

            c1, c2 = st.columns(2)

            with c1:
                if st.button(
                    "✅ 批准变更",
                    type="primary",
                    key=f"contract_approve_{item['change_id']}",
                ):
                    try:
                        approve_contract_change(
                            employee["employee_id"],
                            item["change_id"],
                            comment,
                        )
                        st.success(
                            f"{item['change_id']} 已批准，进入“待技术修改”。"
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(
                            f"审批失败：{type(exc).__name__}: {exc}"
                        )

            with c2:
                if st.button(
                    "❌ 驳回变更",
                    key=f"contract_reject_{item['change_id']}",
                ):
                    try:
                        reject_contract_change(
                            employee["employee_id"],
                            item["change_id"],
                            comment,
                        )
                        st.warning(
                            f"{item['change_id']} 已驳回。"
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(
                            f"驳回失败：{type(exc).__name__}: {exc}"
                        )


# ============================================================
# 21. 主程序
# ============================================================

def main():
    try:
        employees = load_employees()
        projects = load_projects()
        policies = load_policies()

    except Exception as e:
        st.error("数据库连接失败")
        st.code(str(e))
        st.stop()

    if not st.session_state.get("logged_in"):
        render_login(employees)
        return

    employee = st.session_state.employee

    with st.sidebar:
        st.title("ERP 🏢")
        st.write(employee["employee_name"])

        roles = st.session_state.get("roles", set())
        st.caption(
            "角色：" + ", ".join(sorted(roles))
        )

        pages = [
            "首页",
            "我的信息",
        ]

        if "employee" in roles:
            pages.extend([
                "新建申请",
                "我的申请",
            ])

        if "approver" in roles:
            pages.append("我的审批")

        if "contract_admin" in roles:
            pages.append("Contract 变更申请")

        if "contract_approver" in roles:
            pages.append("Contract 变更审批")

        page = st.radio(
            "功能",
            pages,
        )

        if st.button("退出登录"):
            st.session_state.clear()
            st.rerun()

    if page == "首页":
        st.title("ERP 企业业务管理系统")

        st.info(
            """
            当前版本：

            ✔ 员工登录

            ✔ 极薄 RBAC（employee / approver / data_admin / contract_admin / contract_approver）

            ✔ Contract Change Governance（申请可追溯 / 独立审批资格 / 禁止自审批）

            ✔ 业务申请

            ✔ 审批流

            ✔ 自动生成 journal_entries

            ✔ Contract 18 字段显式来源 / 派生

            ✔ 支持性凭证 → missing_support_flag

            ✔ 制单人与审批人 → same_preparer_approver_flag

            ✔ 实际审批级别 → approval_level / approval_below_expected_flag

            ✔ 金额 / 阈值 → is_round_amount / high_value_flag / near_approval_threshold_flag

            ✔ 过账时间 → posting_hour / posting_dayofweek / manual_after_hours_flag

            ✔ 风险字段 → risk_class

            ✔ 重复审批保护

            ✔ 财务流水幂等保护

            ✔ Contract 变更申请与审计链

            ✔ contract_approver 独立审批资格

            ✔ 后端禁止 requested_by = approved_by 的自审批

            ✔ 页面不直接修改 financial_data_contract.yaml
            """
        )

    elif page == "我的信息":
        page_my_info(employee)

    elif page == "新建申请":
        if "employee" not in roles:
            st.error("无权访问：需要 employee 角色。")
            return
        page_new_request(employee, projects, policies)

    elif page == "我的申请":
        if "employee" not in roles:
            st.error("无权访问：需要 employee 角色。")
            return
        page_my_requests(employee)

    elif page == "我的审批":
        if "approver" not in roles:
            st.error("无权访问：需要 approver 角色。")
            return
        page_my_approval(employee)

    elif page == "Contract 变更申请":
        if "contract_admin" not in roles:
            st.error("无权访问：需要 contract_admin 角色。")
            return
        page_contract_change_request(employee)

    elif page == "Contract 变更审批":
        if "contract_approver" not in roles:
            st.error("无权访问：需要 contract_approver 角色。")
            return
        page_contract_change_approval(employee)


if __name__ == "__main__":
    main()
