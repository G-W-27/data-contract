"""
ERP 企业业务管理系统（第 2 版）

新增：
1. 员工登录
2. 业务申请
3. 我的申请
4. 我的审批 ⭐
5. 审批通过自动生成 journal_entries

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


注意：
- 当前数据库 password_hash 使用 demo_hash，仅用于开发演示。
- 数据库密码通过环境变量读取。
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
# 2. PostgreSQL连接
# ============================================================

def get_db_config():

    password = (
        os.getenv("DATACONTRACT_POSTGRES_PASSWORD")
        or os.getenv("ERP_DB_PASSWORD")
    )

    if not password:
        raise RuntimeError(
            "没有读取到数据库密码，请设置 "
            "DATACONTRACT_POSTGRES_PASSWORD"
        )

    return {
        "host": os.getenv(
            "ERP_DB_HOST",
            "localhost"
        ),
        "port": int(
            os.getenv(
                "ERP_DB_PORT",
                "5432"
            )
        ),
        "database": os.getenv(
            "ERP_DB_NAME",
            "erp_demo"
        ),
        "user": os.getenv(
            "ERP_DB_USER",
            "kestra"
        ),
        "password": password,
    }


def get_connection():

    return psycopg2.connect(
        **get_db_config()
    )


def fetch_all(sql, params=None):

    conn = get_connection()

    try:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                sql,
                params or ()
            )

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
          ON p.project_manager_id=e.employee_id
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
        ORDER BY business_type,
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
        ON br.request_id=ar.request_id

        LEFT JOIN employees e
        ON ar.approver_id=e.employee_id

        WHERE br.requester_id=%s

        ORDER BY br.submitted_at DESC
        """,
        (
            requester_id,
        )
    )



# ============================================================
# 5. ⭐ 我的审批
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

        ON ar.request_id=br.request_id


        JOIN employees e

        ON br.requester_id=e.employee_id


        WHERE ar.approver_id=%s

        AND ar.approval_status='待审批'


        ORDER BY ar.created_at DESC

        """,
        (
            approver_id,
        )
    )



# ============================================================
# 6. 自动生成journal_entries
# ============================================================


def create_journal_entry(
        cur,
        request_id,
        approval_id
):

    """
    审批通过后自动生成ERP流水
    """


    cur.execute(
        """
        SELECT

            br.project_id,
            br.amount,
            br.currency,
            br.requester_id,

            ar.approver_id,
            ar.required_level,
            ar.near_approval_threshold_flag,

            ap.gl_account


        FROM business_requests br


        JOIN approval_records ar

        ON br.request_id=ar.request_id


        JOIN approval_policies ap

        ON ar.policy_id=ap.policy_id


        WHERE ar.approval_id=%s

        """,
        (
            approval_id,
        )
    )


    data = cur.fetchone()


    if not data:

        raise ValueError(
            "无法找到审批对应业务数据"
        )


    transaction_id = (
        "TRX"
        +
        approval_id[3:]
    )


    cur.execute(
        """
        INSERT INTO journal_entries
        (

            transaction_id,

            request_id,

            project_id,

            posting_datetime,

            amount,

            currency,

            gl_account,

            preparer_id,

            approver_id,

            workflow_status,

            approval_level,

            risk_class,

            posting_hour,

            posting_dayofweek,

            near_approval_threshold_flag

        )


        VALUES

        (

            %s,

            %s,

            %s,

            CURRENT_TIMESTAMP,

            %s,

            %s,

            %s,

            %s,

            %s,

            '已通过',

            %s,

            '普通',

            EXTRACT(HOUR FROM CURRENT_TIMESTAMP),

            EXTRACT(DOW FROM CURRENT_TIMESTAMP),

            %s

        )

        """,

        (

            transaction_id,

            request_id,

            data["project_id"],

            data["amount"],

            data["currency"],

            data["gl_account"],

            data["requester_id"],

            data["approver_id"],

            data["required_level"],

            1
            if data["near_approval_threshold_flag"]
            else 0,

        )

    )



# ============================================================
# 7. 审批通过
# ============================================================


def approve_request(
        approval_id,
        request_id
):

    conn = get_connection()

    try:

        with conn:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:


                # 更新审批记录

                cur.execute(
                    """
                    UPDATE approval_records

                    SET

                    approval_status='已通过',

                    approval_comment='同意',

                    approved_at=CURRENT_TIMESTAMP


                    WHERE approval_id=%s

                    """,
                    (
                        approval_id,
                    )
                )



                # 更新申请状态

                cur.execute(
                    """
                    UPDATE business_requests

                    SET

                    request_status='已通过',

                    updated_at=CURRENT_TIMESTAMP


                    WHERE request_id=%s

                    """,
                    (
                        request_id,
                    )
                )



                # 自动记账

                create_journal_entry(
                    cur,
                    request_id,
                    approval_id
                )


        return True


    except Exception:

        conn.rollback()

        raise


    finally:

        conn.close()




# ============================================================
# 8. 审批驳回
# ============================================================


def reject_request(
        approval_id,
        request_id,
        comment
):

    conn = get_connection()

    try:

        with conn:

            with conn.cursor() as cur:


                cur.execute(
                    """
                    UPDATE approval_records

                    SET

                    approval_status='已驳回',

                    approval_comment=%s,

                    approved_at=CURRENT_TIMESTAMP


                    WHERE approval_id=%s

                    """,
                    (
                        comment,
                        approval_id
                    )
                )



                cur.execute(
                    """
                    UPDATE business_requests

                    SET

                    request_status='已驳回',

                    updated_at=CURRENT_TIMESTAMP


                    WHERE request_id=%s

                    """,
                    (
                        request_id,
                    )
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
                    SUBSTRING(request_id,4)
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
                    SUBSTRING(approval_id,4)
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
        f"APR{max_approval + 1:05d}"
    )




# ============================================================
# 10. 匹配审批政策
# ============================================================


def match_policy(
        cur,
        business_type,
        category,
        amount
):

    cur.execute(
        """
        SELECT

            policy_id,

            required_level,

            near_threshold_amount,

            gl_account


        FROM approval_policies


        WHERE business_type=%s

        AND category=%s

        AND min_amount <= %s

        AND %s < max_amount


        """,
        (
            business_type,
            category,
            amount,
            amount
        )
    )


    policies = cur.fetchall()


    if len(policies)==0:

        raise ValueError(
            "没有匹配审批政策"
        )


    if len(policies)>1:

        raise ValueError(
            "存在多个审批政策匹配"
        )


    return policies[0]





# ============================================================
# 11. 自动选择审批人
# ============================================================


def choose_approver(
        cur,
        requester_id,
        required_level
):

    cur.execute(
        """
        SELECT

            employee_id,

            employee_name,

            employee_level


        FROM employees


        WHERE is_active=TRUE

        AND employee_id<>%s

        AND employee_level >= %s


        ORDER BY

            employee_level ASC,

            employee_id ASC


        LIMIT 1

        """,
        (
            requester_id,
            required_level
        )
    )


    result = cur.fetchone()


    if not result:

        raise ValueError(
            "没有找到审批人"
        )


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
        support_document_flag
):


    conn=get_connection()


    try:


        with conn:


            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:



                cur.execute(
                    """
                    LOCK TABLE business_requests
                    IN SHARE ROW EXCLUSIVE MODE
                    """
                )



                policy = match_policy(
                    cur,
                    business_type,
                    category,
                    amount
                )



                approver = choose_approver(
                    cur,
                    requester_id,
                    policy["required_level"]
                )



                request_id, approval_id = (
                    get_next_numbers(cur)
                )



                near_threshold = (

                    amount >=
                    policy["near_threshold_amount"]

                )



                # 写入申请

                cur.execute(
                    """
                    INSERT INTO business_requests
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

                    support_document_flag

                    )

                    VALUES

                    (

                    %s,%s,%s,%s,%s,

                    %s,%s,%s,%s,%s

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

                    support_document_flag

                    )
                )




                # 写审批记录

                cur.execute(
                    """
                    INSERT INTO approval_records
                    (

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


                    VALUES

                    (

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

                    near_threshold

                    )

                )



                return {

                    "request_id":request_id,

                    "approval_id":approval_id,

                    "policy_id":policy["policy_id"],

                    "required_level":
                        policy["required_level"],

                    "approver_id":
                        approver["employee_id"],

                    "approver_name":
                        approver["employee_name"],

                    "approver_level":
                        approver["employee_level"],

                    "near_threshold":
                        near_threshold

                }



    finally:

        conn.close()





# ============================================================
# 13. 登录页面
# ============================================================


def render_login(employees):


    st.title(
        "ERP 🏢 企业业务管理系统"
    )


    employee_map = {

        f"{e['employee_id']} - "
        f"{e['employee_name']} - "
        f"{e['department']} - "
        f"{e['position']}":

        e

        for e in employees

    }



    selected = st.selectbox(

        "员工账号",

        list(employee_map.keys())

    )



    password = st.text_input(

        "密码",

        type="password"

    )



    st.warning(
        """
        当前为开发演示登录：

        数据库 password_hash =
        demo_hash

        仅用于业务流程测试。
        """
    )



    if st.button(
        "登录",
        type="primary"
    ):


        employee = employee_map[selected]


        if password != employee["password_hash"]:

            st.error(
                "密码错误"
            )

            return



        st.session_state.logged_in=True

        st.session_state.employee=dict(employee)


        st.rerun()




# ============================================================
# 14. 我的信息
# ============================================================


def page_my_info(employee):


    st.subheader(
        "👤 我的信息"
    )


    st.write(

        {

        "姓名":
            employee["employee_name"],

        "部门":
            employee["department"],

        "职位":
            employee["position"],

        "级别":
            employee["employee_level"],

        "账号":
            employee["username"]

        }

    )





# ============================================================
# 15. 我的申请
# ============================================================


def page_my_requests(employee):


    st.subheader(
        "📋 我的申请"
    )


    rows = load_my_requests(
        employee["employee_id"]
    )


    if not rows:

        st.info(
            "暂无申请"
        )

        return



    st.dataframe(

        rows,

        use_container_width=True

    )




# ============================================================
# 16. 新建申请页面
# ============================================================


def page_new_request(
        employee,
        projects,
        policies
):

    st.subheader(
        "📝 新建业务申请"
    )


    business_types = sorted(
        {
            p["business_type"]
            for p in policies
        }
    )


    business_type = st.selectbox(
        "业务类型",
        business_types
    )


    categories = sorted(
        {
            p["category"]
            for p in policies
            if p["business_type"]
            ==
            business_type
        }
    )


    category = st.selectbox(
        "业务类别",
        categories
    )


    project_map = {

        f"{p['project_id']} - "
        f"{p['project_name']}":

        p

        for p in projects

    }


    project_label = st.selectbox(

        "关联项目",

        list(project_map.keys())

    )


    project = project_map[project_label]



    title = st.text_input(
        "申请标题"
    )


    description = st.text_area(
        "申请说明"
    )


    amount_text = st.text_input(
        "金额"
    )



    currency = st.selectbox(
        "币种",
        [
            "CNY"
        ]
    )


    support_document = st.checkbox(
        "是否有支持性凭证"
    )



    if st.button(
        "提交申请",
        type="primary"
    ):


        try:

            amount = Decimal(
                amount_text
            )

        except:

            st.error(
                "金额格式错误"
            )

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

                support_document

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
# 17. ⭐ 我的审批页面
# ============================================================


def page_my_approval(employee):


    st.subheader(
        "📋 我的审批"
    )


    approvals = load_pending_approvals(
        employee["employee_id"]
    )



    if not approvals:

        st.info(
            "暂无待审批事项"
        )

        return



    for item in approvals:


        st.divider()



        st.subheader(

            item["request_title"]

        )


        st.write(

            f"""

            申请人：

            {item['requester_name']}



            业务：

            {item['business_type']}

            -

            {item['category']}



            金额：

            {item['amount']}
            {item['currency']}



            审批等级：

            {item['required_level']}级


            """

        )



        if item[
            "near_approval_threshold_flag"
        ]:

            st.warning(
                "⚠ 临近审批阈值"
            )



        comment = st.text_input(

            "审批意见",

            key=item["approval_id"]

        )



        col1,col2 = st.columns(2)



        with col1:


            if st.button(

                "✅ 通过",

                key=
                "pass_"
                +
                item["approval_id"]

            ):


                approve_request(

                    item["approval_id"],

                    item["request_id"]

                )


                st.success(

                    "审批通过，已生成财务流水"

                )


                st.rerun()



        with col2:


            if st.button(

                "❌ 驳回",

                key=
                "reject_"
                +
                item["approval_id"]

            ):


                reject_request(

                    item["approval_id"],

                    item["request_id"],

                    comment

                )


                st.warning(

                    "已驳回"

                )


                st.rerun()






# ============================================================
# 18. 主程序
# ============================================================


def main():


    try:


        employees = load_employees()

        projects = load_projects()

        policies = load_policies()



    except Exception as e:


        st.error(
            "数据库连接失败"
        )

        st.code(
            str(e)
        )

        st.stop()




    if not st.session_state.get(
        "logged_in"
    ):


        render_login(
            employees
        )

        return




    employee = st.session_state.employee




    with st.sidebar:


        st.title(
            "ERP 🏢"
        )


        st.write(

            employee["employee_name"]

        )


        page = st.radio(

            "功能",

            [

                "首页",

                "我的信息",

                "新建申请",

                "我的申请",

                "我的审批"

            ]

        )



        if st.button(
            "退出登录"
        ):


            st.session_state.clear()

            st.rerun()





    if page=="首页":


        st.title(

            "ERP 企业业务管理系统"

        )


        st.info(

            """

            当前版本：

            ✔ 员工登录

            ✔ 业务申请

            ✔ 审批流

            ✔ 自动生成 journal_entries


            """

        )



    elif page=="我的信息":


        page_my_info(
            employee
        )



    elif page=="新建申请":


        page_new_request(

            employee,

            projects,

            policies

        )



    elif page=="我的申请":


        page_my_requests(

            employee

        )



    elif page=="我的审批":


        page_my_approval(

            employee

        )




if __name__=="__main__":

    main()