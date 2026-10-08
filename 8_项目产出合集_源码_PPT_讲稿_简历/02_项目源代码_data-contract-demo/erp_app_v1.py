"""
ERP 企业业务系统（第 1 版）
目标：
1. 从 PostgreSQL employees 动态读取员工账号
2. 登录后查看本人信息
3. 从 approval_policies / projects 动态读取业务选项
4. 提交业务申请，写入 business_requests
5. 按金额 + 业务类型 + 业务类别匹配审批规则
6. 自动选择一名满足 required_level 且不是申请人的审批人
7. 生成 approval_records

注意：
- 当前项目的 employees.password_hash 演示数据是字面量 "demo_hash"，
  本版因此只实现“演示登录”，不是生产级密码认证。
- 数据库密码不写进代码，沿用项目已有的环境变量
  DATACONTRACT_POSTGRES_PASSWORD。
- journal_entries / 审批通过后的自动记账，本版先不做，下一步再接。
"""

import os
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
    """读取数据库连接配置，绝不把密码硬编码在代码里。"""
    password = (
        os.getenv("DATACONTRACT_POSTGRES_PASSWORD")
        or os.getenv("ERP_DB_PASSWORD")
    )

    if not password:
        raise RuntimeError(
            "没有读取到数据库密码。请先设置 "
            "DATACONTRACT_POSTGRES_PASSWORD 环境变量。"
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
    """查询多行记录。"""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


# ============================================================
# 3. 数据读取：员工 / 项目 / 审批规则
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
        ORDER BY business_type, category, min_amount
        """
    )


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
            br.submitted_at,
            ar.approval_id,
            ar.approver_id,
            e.employee_name AS approver_name,
            ar.required_level,
            ar.approver_level_snapshot,
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
# 4. 生成下一笔业务编号
# ============================================================

def get_next_numbers(cur):
    """
    按项目现有命名方式继续生成：
    request_id    -> REQ00001
    approval_id   -> APR00001
    """
    cur.execute(
        """
        SELECT COALESCE(
            MAX(CAST(SUBSTRING(request_id FROM 4) AS INTEGER)), 0
        )
        FROM business_requests
        WHERE request_id ~ '^REQ[0-9]+$'
        """
    )
    max_request_number = list(cur.fetchone().values())[0]

    cur.execute(
        """
        SELECT COALESCE(
            MAX(CAST(SUBSTRING(approval_id FROM 4) AS INTEGER)), 0
        )
        FROM approval_records
        WHERE approval_id ~ '^APR[0-9]+$'
        """
    )
    max_approval_number = list(cur.fetchone().values())[0]

    next_request_number = max_request_number + 1
    next_approval_number = max_approval_number + 1

    return (
        f"REQ{next_request_number:05d}",
        f"APR{next_approval_number:05d}",
    )


# ============================================================
# 5. 审批规则匹配
# ============================================================

def match_policy(cur, business_type, category, amount):
    """
    金额区间采用项目现有口径：
    min_amount <= amount < max_amount
    """
    cur.execute(
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
        WHERE business_type = %s
          AND category = %s
          AND min_amount <= %s
          AND %s < max_amount
        ORDER BY min_amount
        """,
        (business_type, category, amount, amount),
    )
    policies = cur.fetchall()

    if len(policies) == 0:
        raise ValueError(
            "没有找到匹配的审批政策。请检查："
            "业务类型、业务类别、金额是否落在已有政策区间内。"
        )

    if len(policies) > 1:
        raise ValueError(
            f"发现 {len(policies)} 条同时命中的审批政策，"
            "说明审批金额区间存在重叠，需要先修正 approval_policies。"
        )

    return policies[0]


def choose_approver(cur, requester_id, required_level):
    """
    按项目既定逻辑：
    找 active 员工，级别 >= required_level，且不能是申请人。
    优先选择“刚好够级”的人，再按 employee_id 稳定排序。
    """
    cur.execute(
        """
        SELECT
            employee_id,
            employee_name,
            employee_level,
            department,
            position
        FROM employees
        WHERE is_active = TRUE
          AND employee_id <> %s
          AND employee_level >= %s
        ORDER BY employee_level ASC, employee_id ASC
        LIMIT 1
        """,
        (requester_id, required_level),
    )

    approver = cur.fetchone()

    if not approver:
        raise ValueError(
            f"找不到级别 >= {required_level} 且不是申请人的可用审批人。"
        )

    return approver


# ============================================================
# 6. 写入业务申请 + 审批记录
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
    conn = get_connection()

    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 防止两个并发提交同时拿到同一个最大 REQ 编号。
                cur.execute(
                    "LOCK TABLE business_requests IN SHARE ROW EXCLUSIVE MODE"
                )

                policy = match_policy(
                    cur,
                    business_type,
                    category,
                    amount,
                )

                approver = choose_approver(
                    cur,
                    requester_id,
                    policy["required_level"],
                )

                request_id, approval_id = get_next_numbers(cur)

                same_person = requester_id == approver["employee_id"]
                below_expected = (
                    approver["employee_level"] < policy["required_level"]
                )
                near_threshold = (
                    amount >= policy["near_threshold_amount"]
                )

                # 1) 业务申请
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
                        support_document_flag,
                        request_status
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '待审批'
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

                # 2) 审批记录
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
                        same_preparer_approver_flag,
                        approval_below_expected_flag,
                        near_approval_threshold_flag
                    )
                    VALUES (
                        %s, %s, 1, %s, %s, %s, %s, '待审批',
                        %s, %s, %s
                    )
                    """,
                    (
                        approval_id,
                        request_id,
                        policy["policy_id"],
                        approver["employee_id"],
                        approver["employee_level"],
                        policy["required_level"],
                        same_person,
                        below_expected,
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

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# 7. 登录
# ============================================================

def render_login(employees):
    st.title("ERP 🏢 企业业务管理系统")
    st.caption("第一版：员工登录 + 业务申请")

    employee_map = {
        f"{e['employee_id']} - {e['employee_name']} - "
        f"{e['department']} - {e['position']}": e
        for e in employees
    }

    selected_label = st.selectbox(
        "员工账号",
        options=list(employee_map.keys()),
    )

    password = st.text_input(
        "密码",
        type="password",
        help="当前项目数据库里的 password_hash 是演示占位值 demo_hash。",
    )

    st.warning(
        "当前为开发演示登录：已有员工记录使用的是 password_hash = "
        "\"demo_hash\"。因此本版只用于把业务前台链路跑通，"
        "还不是生产级密码认证。"
    )

    if st.button("登录", type="primary", use_container_width=True):
        employee = employee_map[selected_label]

        # 诚实保持与当前数据库种子一致：
        # 当前 employee.password_hash 存的就是 demo_hash。
        if password != employee["password_hash"]:
            st.error("密码不正确。当前演示库请使用员工记录中的演示占位密码。")
            return

        st.session_state["logged_in"] = True
        st.session_state["employee"] = dict(employee)
        st.rerun()


# ============================================================
# 8. 页面：我的信息
# ============================================================

def page_my_info(employee):
    st.subheader("👤 我的信息")

    c1, c2, c3 = st.columns(3)
    c1.metric("员工编号", employee["employee_id"])
    c2.metric("员工级别", employee["employee_level"])
    c3.metric("状态", "在职" if employee["is_active"] else "停用")

    st.write(
        {
            "姓名": employee["employee_name"],
            "部门": employee["department"],
            "职位": employee["position"],
            "岗位类型": employee["position_type"],
            "登录账号": employee["username"],
        }
    )


# ============================================================
# 9. 页面：新建申请
# ============================================================

def page_new_request(employee, projects, policies):
    st.subheader("📝 新建业务申请")

    business_types = sorted(
        {p["business_type"] for p in policies}
    )

    if not business_types:
        st.error("approval_policies 没有可用规则，暂时无法创建申请。")
        return

    business_type = st.selectbox(
        "业务类型 *",
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
        "业务类别 *",
        categories,
    )

    project_options = {
        f"{p['project_id']} - {p['project_name']} - "
        f"{p['manager_name']} - {p['project_status']}": p
        for p in projects
    }

    if not project_options:
        st.error("projects 没有可用项目。")
        return

    selected_project = st.selectbox(
        "关联项目 *",
        options=list(project_options.keys()),
    )
    project = project_options[selected_project]

    st.divider()

    # 系统自动信息
    c1, c2, c3 = st.columns(3)
    c1.text_input("申请人", employee["employee_name"], disabled=True)
    c2.text_input("申请状态", "待审批", disabled=True)
    c3.text_input("申请编号", "提交时自动生成", disabled=True)

    request_title = st.text_input(
        "申请标题 *",
        placeholder="例如：GPU 服务器采购申请",
    )

    request_description = st.text_area(
        "申请说明",
        placeholder="请说明申请用途、业务背景和必要性。",
        height=140,
    )

    amount_text = st.text_input(
        "金额 *",
        placeholder="例如：180000.00",
    )

    # 当前 schema 没有 currency dictionary 表。
    # 为了不凭空发明一套币种主数据，这一版用现有业务数据中出现过的币种。
    existing_currencies = fetch_all(
        """
        SELECT DISTINCT currency
        FROM business_requests
        WHERE currency IS NOT NULL
        ORDER BY currency
        """
    )
    currencies = [x["currency"] for x in existing_currencies]
    if "CNY" not in currencies:
        currencies.insert(0, "CNY")

    currency = st.selectbox(
        "币种 *",
        currencies,
    )

    support_document_flag = st.checkbox(
        "是否有支持性凭证",
        value=False,
    )

    # 实时提示当前金额会命中哪条制度
    preview_policy = None
    try:
        amount_preview = Decimal(amount_text)
        for p in policies:
            if (
                p["business_type"] == business_type
                and p["category"] == category
                and p["min_amount"] <= amount_preview < p["max_amount"]
            ):
                preview_policy = p
                break
    except (InvalidOperation, ValueError):
        pass

    if preview_policy:
        st.info(
            f"系统审批规则提示：当前金额对应 "
            f"{preview_policy['required_level']} 级审批；"
            f"政策编号 {preview_policy['policy_id']}。"
        )

    if st.button(
        "提交申请",
        type="primary",
        use_container_width=True,
    ):
        if not request_title.strip():
            st.error("申请标题不能为空。")
            return

        try:
            amount = Decimal(amount_text).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            st.error("金额必须是合法数字，例如 180000.00。")
            return

        if amount <= 0:
            st.error("金额必须大于 0。")
            return

        try:
            result = create_request(
                requester_id=employee["employee_id"],
                business_type=business_type,
                category=category,
                project_id=project["project_id"],
                request_title=request_title.strip(),
                request_description=request_description.strip(),
                amount=amount,
                currency=currency,
                support_document_flag=support_document_flag,
            )
        except Exception as exc:
            st.error(f"提交失败：{type(exc).__name__}: {repr(exc)}")
            return

        st.success(
            f"申请已提交：{result['request_id']}；"
            f"审批记录：{result['approval_id']}"
        )

        st.write(
            {
                "匹配审批政策": result["policy_id"],
                "要求级别": result["required_level"],
                "审批人": (
                    f"{result['approver_id']} - "
                    f"{result['approver_name']} - "
                    f"{result['approver_level']}级"
                ),
                "临近阈值标志": result["near_threshold"],
            }
        )


# ============================================================
# 10. 页面：我的申请
# ============================================================

def page_my_requests(employee):
    st.subheader("📋 我的申请")

    rows = load_my_requests(employee["employee_id"])

    if not rows:
        st.info("你还没有提交过业务申请。")
        return

    display_rows = []

    for row in rows:
        display_rows.append(
            {
                "申请编号": row["request_id"],
                "业务类型": row["business_type"],
                "业务类别": row["category"],
                "申请标题": row["request_title"],
                "金额": row["amount"],
                "币种": row["currency"],
                "申请状态": row["request_status"],
                "审批人": (
                    f"{row['approver_id']} - {row['approver_name']}"
                    if row["approver_id"]
                    else "未生成"
                ),
                "审批状态": row["approval_status"] or "",
                "要求级别": row["required_level"],
            }
        )

    st.dataframe(
        display_rows,
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# 11. 主页面
# ============================================================

def main():
    try:
        employees = load_employees()
        projects = load_projects()
        policies = load_policies()
    except Exception as exc:
        st.error("无法连接 ERP PostgreSQL。")
        st.code(str(exc))
        st.info(
            "请先确认 Docker / PostgreSQL 已启动，并且当前终端环境里已经有 "
            "DATACONTRACT_POSTGRES_PASSWORD。"
        )
        st.stop()

    if not employees:
        st.error("employees 表没有 active 员工，无法登录。")
        st.stop()

    if not st.session_state.get("logged_in"):
        render_login(employees)
        return

    employee = st.session_state["employee"]

    with st.sidebar:
        st.title("ERP 🏢")
        st.write(f"👋 {employee['employee_name']}")
        st.caption(
            f"{employee['department']} · "
            f"{employee['position']} · "
            f"{employee['employee_level']}级"
        )

        page = st.radio(
            "功能",
            ["首页", "我的信息", "新建申请", "我的申请"],
        )

        if st.button("退出登录", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    if page == "首页":
        st.title(f"👋 欢迎回来，{employee['employee_name']}")
        st.write("这里是 ERP 业务前台第 1 版。")
        st.info(
            "当前已经具备：员工身份读取、动态业务选项、"
            "业务申请写库、审批政策匹配、审批人自动路由。"
        )

    elif page == "我的信息":
        page_my_info(employee)

    elif page == "新建申请":
        page_new_request(employee, projects, policies)

    elif page == "我的申请":
        page_my_requests(employee)


if __name__ == "__main__":
    main()
