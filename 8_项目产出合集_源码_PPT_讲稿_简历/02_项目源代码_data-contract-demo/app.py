import json
import os
import subprocess
from datetime import datetime

import pandas as pd
import psycopg2
import streamlit as st


# ============================================================
# 1. 页面配置
# ============================================================

st.set_page_config(
    page_title="ERP 财务数据质量监控平台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# 2. 页面样式
# ============================================================

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1500px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    .section-title {
        font-size: 1.15rem;
        font-weight: 700;
        color: #1f2937;
        margin-top: 1.4rem;
        margin-bottom: 0.8rem;
    }

    .dashboard-header {
        padding: 0.4rem 0 1.2rem 0;
    }

    .dashboard-title {
        font-size: 2.1rem;
        font-weight: 800;
        color: #111827;
        margin-bottom: 0.2rem;
    }

    .dashboard-subtitle {
        color: #6b7280;
        font-size: 0.95rem;
    }

    .status-box {
        border-radius: 12px;
        padding: 18px 20px;
        border: 1px solid #dbeafe;
        background: #f8fbff;
    }

    .status-pass {
        color: #15803d;
        font-size: 1.45rem;
        font-weight: 800;
    }

    .status-fail {
        color: #dc2626;
        font-size: 1.45rem;
        font-weight: 800;
    }

    .status-description {
        color: #6b7280;
        margin-top: 4px;
        font-size: 0.85rem;
    }

    .risk-badge-low {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        background: #ecfdf3;
        color: #15803d;
        font-weight: 700;
        font-size: 0.8rem;
    }

    .risk-badge-medium {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        background: #fff7ed;
        color: #c2410c;
        font-weight: 700;
        font-size: 0.8rem;
    }

    .risk-badge-high {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        background: #fef2f2;
        color: #dc2626;
        font-weight: 700;
        font-size: 0.8rem;
    }

    .footer {
        color: #9ca3af;
        font-size: 0.75rem;
        text-align: center;
        padding-top: 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 3. 数据库配置
# ============================================================

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "erp_demo"

DB_USER = os.getenv(
    "DATACONTRACT_POSTGRES_USERNAME",
    "kestra",
)

DB_PASSWORD = os.getenv(
    "DATACONTRACT_POSTGRES_PASSWORD",
)

REPORT_FILE = "datacontract_report_postgres.json"
CONTRACT_FILE = "financial_data_contract.yaml"


# ============================================================
# 4. 数据库连接
# ============================================================

def get_connection():
    """连接 PostgreSQL。"""

    if not DB_PASSWORD:
        st.error(
            "❌ 未找到 DATACONTRACT_POSTGRES_PASSWORD 环境变量。"
        )
        st.stop()

    try:
        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
    except Exception as exc:
        st.error(f"❌ PostgreSQL 连接失败：{exc}")
        st.stop()


# ============================================================
# 5. 执行当前 Data Contract
# ============================================================

def run_data_contract():
    """
    直接调用当前项目中的 Data Contract。

    这样 Dashboard 不再依赖旧的 55 checks 报告。
    每次点击“刷新 Contract”时都会重新生成最新 JSON。
    """

    env = os.environ.copy()

    # 解决 Windows / Python 输出编码问题
    env["PYTHONUTF8"] = "1"

    result = subprocess.run(
        [
            "datacontract",
            "ci",
            CONTRACT_FILE,
            "--output",
            REPORT_FILE,
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    return result


# ============================================================
# 6. 读取 Contract 报告
# ============================================================

def load_contract_report():

    if not os.path.exists(REPORT_FILE):
        return None

    try:
        with open(
            REPORT_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    except Exception as exc:
        st.error(
            f"❌ 无法读取 Data Contract 报告：{exc}"
        )
        return None


# ============================================================
# 7. 第一次打开页面时自动运行一次 Contract
# ============================================================

if "contract_initialized" not in st.session_state:

    with st.spinner("正在执行 Data Contract 检查，请稍候……"):

        contract_process = run_data_contract()

    st.session_state.contract_initialized = True

    if contract_process.returncode != 0:
        st.session_state.contract_error = contract_process.stderr
    else:
        st.session_state.contract_error = None


# ============================================================
# 8. 页面标题
# ============================================================

st.markdown(
    """
    <div class="dashboard-header">
        <div class="dashboard-title">
            📊 ERP 财务数据质量监控平台
        </div>

        <div class="dashboard-subtitle">
            PostgreSQL + Data Contract + Kestra ·
            ERP 财务数据质量与内控风险监控
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 9. 左侧系统信息
# ============================================================

with st.sidebar:

    st.markdown("## ⚙️ 系统信息")

    st.write("**数据源**")
    st.code(
        "PostgreSQL / erp_demo",
        language="text",
    )

    st.write("**数据接口**")
    st.code(
        "public.erp_transactions",
        language="text",
    )

    st.write("**Data Contract**")
    st.code(
        "erp-accounting-risk-contract",
        language="text",
    )

    st.write("**自动化调度**")
    st.code(
        "Kestra · 每日 06:00",
        language="text",
    )

    st.markdown("---")

    if st.button(
        "🔄 刷新数据库数据",
        use_container_width=True,
    ):
        st.rerun()

    if st.button(
        "🛡️ 重新执行 Data Contract",
        use_container_width=True,
    ):

        with st.spinner(
            "正在重新执行 72 项 Data Contract 检查……"
        ):

            process = run_data_contract()

        if process.returncode == 0:

            st.success(
                "✅ Data Contract 执行成功"
            )

        else:

            st.error(
                "❌ Data Contract 执行失败"
            )

            error_text = (
                process.stderr
                or process.stdout
            )

            st.code(
                error_text[-5000:],
                language="text",
            )


# ============================================================
# 10. 获取数据库数据
# ============================================================

conn = get_connection()


# ---------- 核心指标 ----------

summary_sql = """
    SELECT
        COUNT(*) AS total_transactions,
        COALESCE(SUM(amount), 0) AS total_amount,
        COALESCE(AVG(amount), 0) AS average_amount,
        COALESCE(MAX(amount), 0) AS max_amount
    FROM erp_transactions
"""

summary_df = pd.read_sql(
    summary_sql,
    conn,
)

summary = summary_df.iloc[0]


# ---------- 风险分布 ----------

risk_sql = """
    SELECT
        risk_class,
        COUNT(*) AS transaction_count
    FROM erp_transactions
    GROUP BY risk_class
    ORDER BY risk_class
"""

risk_df = pd.read_sql(
    risk_sql,
    conn,
)


# ---------- 内控风险 ----------

control_sql = """
    SELECT
        COUNT(*) FILTER (
            WHERE same_preparer_approver_flag <> 0
        ) AS same_preparer_approver,

        COUNT(*) FILTER (
            WHERE missing_support_flag <> 0
        ) AS missing_support,

        COUNT(*) FILTER (
            WHERE approval_below_expected_flag <> 0
        ) AS approval_below,

        COUNT(*) FILTER (
            WHERE near_approval_threshold_flag <> 0
        ) AS near_threshold,

        COUNT(*) FILTER (
            WHERE ABS(amount) > 5000000
        ) AS amount_over_limit
    FROM erp_transactions
"""

control_df = pd.read_sql(
    control_sql,
    conn,
)

control = control_df.iloc[0]


# ---------- 最近交易 ----------

recent_sql = """
    SELECT
        transaction_id,
        posting_datetime,
        amount,
        currency,
        gl_account,
        approval_level,
        risk_class
    FROM erp_transactions
    ORDER BY posting_datetime DESC
    LIMIT 15
"""

recent_df = pd.read_sql(
    recent_sql,
    conn,
)

conn.close()


# ============================================================
# 11. 核心指标
# ============================================================

st.markdown(
    '<div class="section-title">📌 核心运营指标</div>',
    unsafe_allow_html=True,
)

k1, k2, k3, k4 = st.columns(4)

k1.metric(
    "📋 交易总数",
    f"{int(summary['total_transactions']):,}",
    help="ERP 核心交易记录总数",
)

k2.metric(
    "💰 交易金额总额",
    f"¥{float(summary['total_amount']):,.0f}",
)

k3.metric(
    "📊 平均交易金额",
    f"¥{float(summary['average_amount']):,.0f}",
)

k4.metric(
    "🔝 最大交易金额",
    f"¥{float(summary['max_amount']):,.0f}",
)


# ============================================================
# 12. 风险等级 + 财务内控
# ============================================================

left_col, right_col = st.columns([1.15, 1])


# ============================================================
# 左侧：风险等级
# ============================================================

with left_col:

    st.markdown(
        '<div class="section-title">🚦 风险等级分布</div>',
        unsafe_allow_html=True,
    )

    risk_map = {
        "LOW": 0,
        "MEDIUM": 0,
        "HIGH": 0,
    }

    for _, row in risk_df.iterrows():

        key = str(
            row["risk_class"]
        ).upper()

        if key in risk_map:
            risk_map[key] = int(
                row["transaction_count"]
            )

    total_transactions = int(
        summary["total_transactions"]
    )

    if total_transactions == 0:

        st.info("暂无交易数据。")

    else:

        risk_labels = {
            "LOW": "低风险",
            "MEDIUM": "中风险",
            "HIGH": "高风险",
        }

        for risk_key in [
            "LOW",
            "MEDIUM",
            "HIGH",
        ]:

            count = risk_map[risk_key]

            percent = (
                count
                / total_transactions
                * 100
            )

            label = risk_labels[risk_key]

            col_a, col_b = st.columns(
                [4, 1]
            )

            with col_a:
                st.write(
                    f"**{label}**"
                )

                st.progress(
                    min(
                        count
                        / total_transactions,
                        1.0,
                    )
                )

            with col_b:
                st.metric(
                    label="",
                    value=f"{count:,}",
                    delta=f"{percent:.1f}%",
                )


# ============================================================
# 右侧：财务内控
# ============================================================

with right_col:

    st.markdown(
        '<div class="section-title">🛡️ 财务内控风险监控</div>',
        unsafe_allow_html=True,
    )

    controls = [
        (
            "制单人与审批人相同",
            int(
                control[
                    "same_preparer_approver"
                ]
            ),
        ),
        (
            "缺少支持性文件",
            int(
                control[
                    "missing_support"
                ]
            ),
        ),
        (
            "审批层级低于要求",
            int(
                control[
                    "approval_below"
                ]
            ),
        ),
        (
            "接近审批阈值",
            int(
                control[
                    "near_threshold"
                ]
            ),
        ),
        (
            "金额超过 500 万",
            int(
                control[
                    "amount_over_limit"
                ]
            ),
        ),
    ]

    for name, value in controls:

        if value == 0:

            st.success(
                f"✅ {name}：正常",
                icon="✅",
            )

        else:

            st.error(
                f"❌ {name}：发现 {value} 条异常",
                icon="❌",
            )


# ============================================================
# 13. Data Contract 健康状态
# ============================================================

st.markdown("---")

st.markdown(
    '<div class="section-title">🛡️ Data Contract 健康状态</div>',
    unsafe_allow_html=True,
)

report = load_contract_report()

if report is None:

    st.warning(
        "⚠️ 当前没有可用的 Data Contract 执行报告。"
    )

else:

    contract_result = str(
        report.get(
            "result",
            "unknown",
        )
    ).lower()

    checks = (
        report.get("checks")
        or report.get("results")
        or []
    )

    passed_checks = sum(
        1
        for item in checks
        if str(
            item.get("result", "")
        ).lower() == "passed"
    )

    failed_checks = sum(
        1
        for item in checks
        if str(
            item.get("result", "")
        ).lower() == "failed"
    )

    total_checks = len(checks)

    cli_version = report.get(
        "datacontractCliVersion",
        "-",
    )

    timestamp_end = report.get(
        "timestampEnd",
        "-",
    )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "检查项总数",
        f"{total_checks}",
    )

    c2.metric(
        "通过",
        f"{passed_checks}",
    )

    c3.metric(
        "失败",
        f"{failed_checks}",
    )

    if contract_result == "passed":

        c4.success(
            "✅ PASS"
        )

    else:

        c4.error(
            "❌ FAIL"
        )

    st.caption(
        f"Data Contract CLI：{cli_version}　"
        f"最近执行：{timestamp_end}"
    )


# ============================================================
# 14. Data Contract 检查明细
# ============================================================

st.markdown(
    '<div class="section-title">📋 Data Contract 检查明细</div>',
    unsafe_allow_html=True,
)


def translate_category(value):
    """检查大类中文化。"""

    mapping = {
        "schema": "结构检查",
        "quality": "业务质量检查",
        "completeness": "完整性检查",
        "conformity": "规范性检查",
        "uniqueness": "唯一性检查",
    }

    return mapping.get(
        str(value).lower(),
        str(value),
    )


def translate_check_type(value):
    """检查类型中文化。"""

    mapping = {
        "field_is_present": "字段存在性",
        "field_physical_type": "字段类型",
        "field_required": "非空检查",
        "field_unique": "唯一性检查",
        "field_max_length": "最大长度检查",
        "field_quality_sql": "业务 SQL 规则",
    }

    return mapping.get(
        str(value),
        str(value),
    )


def chinese_field_name(field):
    """字段名称中文化。"""

    mapping = {
        "transaction_id": "交易编号",
        "erp_system": "ERP 系统",
        "posting_datetime": "过账时间",
        "amount": "交易金额",
        "currency": "币种",
        "gl_account": "总账科目",
        "manual_entry_flag": "手工录入标志",
        "risk_class": "风险等级",
        "approval_level": "审批层级",
        "is_round_amount": "整数金额标志",
        "high_value_flag": "高价值交易标志",
        "posting_hour": "过账小时",
        "posting_dayofweek": "过账星期",
        "same_preparer_approver_flag": "制单审批人相同标志",
        "missing_support_flag": "缺少支持文件标志",
        "approval_below_expected_flag": "审批层级不足标志",
        "near_approval_threshold_flag": "接近审批阈值标志",
        "manual_after_hours_flag": "非工作时间手工录入标志",
    }

    return mapping.get(
        field,
        field if field else "—",
    )


def build_chinese_check_name(item):
    """
    生成更容易看懂的中文检查名称。
    """

    original_name = str(
        item.get(
            "name",
            "",
        )
    )

    field = item.get(
        "field"
    )

    field_name = chinese_field_name(
        field
    )

    check_type = str(
        item.get(
            "type",
            "",
        )
    )

    # 当前版本自定义 SQL 规则已经带有中文名称，
    # 直接保留。
    if (
        check_type
        == "field_quality_sql"
        and original_name
        != "Quality Check"
    ):
        return original_name

    if check_type == "field_is_present":
        return f"{field_name}字段必须存在"

    if check_type == "field_physical_type":
        return f"{field_name}字段类型正确"

    if check_type == "field_required":
        return f"{field_name}不得为空"

    if check_type == "field_unique":
        return f"{field_name}必须唯一"

    if check_type == "field_max_length":
        return f"{field_name}长度符合要求"

    return original_name or "未命名检查"


if checks:

    rows = []

    for item in checks:

        result = str(
            item.get(
                "result",
                "",
            )
        ).lower()

        rows.append(
            {
                "检查类别": translate_category(
                    item.get(
                        "category",
                        "",
                    )
                ),
                "检查类型": translate_check_type(
                    item.get(
                        "type",
                        "",
                    )
                ),
                "字段": chinese_field_name(
                    item.get(
                        "field",
                    )
                ),
                "检查内容": build_chinese_check_name(
                    item
                ),
                "结果": (
                    "✅ 通过"
                    if result == "passed"
                    else "❌ 失败"
                ),
            }
        )

    detail_df = pd.DataFrame(
        rows
    )

    # ---------- 分类 Tab ----------

    tab_all, tab_schema, tab_quality = st.tabs(
        [
            "全部检查",
            "结构检查",
            "业务质量检查",
        ]
    )

    with tab_all:

        st.dataframe(
            detail_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "检查类别": st.column_config.TextColumn(
                    "检查类别",
                    width="small",
                ),
                "检查类型": st.column_config.TextColumn(
                    "检查类型",
                    width="medium",
                ),
                "字段": st.column_config.TextColumn(
                    "字段",
                    width="medium",
                ),
                "检查内容": st.column_config.TextColumn(
                    "检查内容",
                    width="large",
                ),
                "结果": st.column_config.TextColumn(
                    "结果",
                    width="small",
                ),
            },
        )

    with tab_schema:

        schema_df = detail_df[
            detail_df["检查类别"] == "结构检查"
        ]

        st.dataframe(
            schema_df,
            use_container_width=True,
            hide_index=True,
        )

    with tab_quality:

        quality_df = detail_df[
            detail_df["检查类别"] == "业务质量检查"
        ]

        st.dataframe(
            quality_df,
            use_container_width=True,
            hide_index=True,
        )

else:

    st.info(
        "当前没有检查明细。"
    )


# ============================================================
# 15. 最近交易
# ============================================================

st.markdown(
    '<div class="section-title">🧾 最近交易</div>',
    unsafe_allow_html=True,
)

if not recent_df.empty:

    display_df = recent_df.copy()

    display_df[
        "posting_datetime"
    ] = pd.to_datetime(
        display_df[
            "posting_datetime"
        ]
    ).dt.strftime(
        "%Y-%m-%d %H:%M"
    )

    display_df["amount"] = (
        display_df["amount"]
        .astype(float)
        .map(
            lambda x: f"¥{x:,.2f}"
        )
    )

    display_df[
        "risk_class"
    ] = display_df[
        "risk_class"
    ].map(
        {
            "LOW": "低风险",
            "MEDIUM": "中风险",
            "HIGH": "高风险",
        }
    )

    display_df.columns = [
        "交易编号",
        "过账时间",
        "金额",
        "币种",
        "总账科目",
        "审批层级",
        "风险等级",
    ]

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
    )

else:

    st.info(
        "暂无交易数据。"
    )


# ============================================================
# 16. 页脚
# ============================================================

st.markdown(
    """
    <div class="footer">
        ERP Financial Data Quality Platform ·
        PostgreSQL · Data Contract · Kestra · Pytest · Streamlit
    </div>
    """,
    unsafe_allow_html=True,
)