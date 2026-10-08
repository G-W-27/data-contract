import os

import pandas as pd
import psycopg2


def get_connection():

    return psycopg2.connect(

        host="localhost",

        port=5432,

        database="erp_demo",

        user="kestra",

        password=os.getenv(
            "DATACONTRACT_POSTGRES_PASSWORD"
        )

    )



def export_journal():

    conn=get_connection()


    sql="""

    SELECT

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


    FROM journal_entries


    ORDER BY posting_datetime

    """



    df=pd.read_sql(

        sql,

        conn

    )


    conn.close()



    df.to_parquet(

        "financial_data.parquet",

        index=False

    )


    print(
        f"导出完成，共{len(df)}条"
    )



if __name__=="__main__":

    export_journal()