"""環境の動作確認用サンプル DAG（本書の考え方をひとまとめにした最小の例）。

この DAG は次の3点を確認します。

1. Airflow が dags/ の Python を読み込み、スケジュールどおりに実行できること
2. Connection「warehouse」経由で分析用データベースに書き込めること
3. 同じ対象を何度実行しても結果が増えない（冪等である）こと

Session 02 以降で、ここに出てくる要素を1つずつ丁寧に扱っていきます。
いまは「動いた」ことだけ確認できれば十分です。
"""

from __future__ import annotations

import pendulum
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import dag, task

DAG_ID = "hello_pipeline"

# 接続情報はコードに書かず、Connection ID だけを参照する。
# 認証情報をソースコードに残さないのは、規模に関わらず最初から守るべき作法です。
WAREHOUSE_CONN_ID = "warehouse"


@dag(
    dag_id=DAG_ID,
    description="環境の動作確認用サンプル（1日1回・冪等な記録）",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Tokyo"),
    catchup=False,  # 過去分をまとめて実行しない（起動直後の大量実行を防ぐ）
    is_paused_upon_creation=False,  # このサンプルだけは最初から動かして成功を確認する
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": pendulum.duration(seconds=30)},
    tags=["lab", "getting-started"],
)
def hello_pipeline() -> None:
    @task
    def show_schedule_context(logical_date=None, data_interval_start=None, data_interval_end=None) -> str:
        """この実行が「いつの分」を担当しているのかを表示する。

        Airflow のタスクは「実行した瞬間」ではなく「担当する時点・期間」を基準に
        動きます。この感覚が cron との一番大きな違いで、Session 03 の中心テーマです。
        """
        print(f"logical_date        : {logical_date}")
        print(f"data_interval_start : {data_interval_start}")
        print(f"data_interval_end   : {data_interval_end}")
        return str(logical_date)

    @task
    def record_healthcheck(logical_date=None, dag_run=None) -> int:
        """分析用データベースへ、この実行が担当する時点の記録を1行だけ残す。

        DELETE してから INSERT するので、何度実行しても行が増えません
        （delete-insert による冪等化。Session 05 で詳しく扱います）。
        """
        from airflow import __version__ as airflow_version

        # 手動トリガの DAG Run では logical_date が None になる（Airflow 3 の仕様）。
        # 対象時点が決まらないと冪等な書き込みができないので、実際の起動時刻で代用する。
        # 日付を指定して手動実行したいときは -l で明示する（Session 03 で扱います）:
        #   airflow dags trigger hello_pipeline -l 2026-01-02T00:00:00+09:00
        target_date = logical_date if logical_date is not None else dag_run.run_after

        hook = PostgresHook(postgres_conn_id=WAREHOUSE_CONN_ID)
        with hook.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM raw.lab_healthcheck WHERE dag_id = %s AND logical_date = %s",
                    (DAG_ID, target_date),
                )
                cur.execute(
                    """
                    INSERT INTO raw.lab_healthcheck (dag_id, logical_date, airflow_version)
                    VALUES (%s, %s, %s)
                    """,
                    (DAG_ID, target_date, airflow_version),
                )
                cur.execute("SELECT count(*) FROM raw.lab_healthcheck WHERE dag_id = %s", (DAG_ID,))
                total = int(cur.fetchone()[0])
            conn.commit()

        print(f"raw.lab_healthcheck の {DAG_ID} の行数: {total}")
        return total

    show_schedule_context() >> record_healthcheck()


hello_pipeline()
