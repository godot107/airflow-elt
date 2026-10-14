"""
### taxi_ingest — extract and load one month of NYC yellow-taxi trips

Each run owns one **data interval** (a calendar month): wait until TLC publishes the file, download it,
replace that month in `raw.yellow_trips`, then run the data-quality gate. Only a month that passes the gate
updates the `raw_yellow_trips` asset, which is what triggers `taxi_transform`.

* **Idempotent:** rerunning a month replaces it (delete + COPY in one transaction).
* **Backfill:** `airflow backfill create --dag-id taxi_ingest --from-date 2024-01-01 --to-date 2024-06-30`
* **Late data:** the sensor reschedules itself (frees its worker slot) for up to 75 days, since TLC lags ~2 months.
"""
from datetime import datetime, timedelta

import pendulum
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import PokeReturnValue, dag, task
from airflow.timetables.interval import CronDataIntervalTimetable

from taxi import config, extract, load, quality
from taxi.alerts import on_failure
from taxi.assets import RAW_TRIPS


@dag(
    dag_id="taxi_ingest",
    schedule=CronDataIntervalTimetable("0 0 1 * *", timezone="UTC"),   # interval = the previous month
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,                       # history arrives through explicit backfills, not on unpause
    max_active_runs=3,
    default_args={"retries": 3, "retry_delay": timedelta(minutes=1), "retry_exponential_backoff": True,
                  "on_failure_callback": on_failure},
    tags=["taxi", "elt", "extract-load"],
    doc_md=__doc__,
)
def taxi_ingest():
    @task.sensor(poke_interval=6 * 3600, timeout=75 * 86400, mode="reschedule")
    def wait_for_file(data_interval_start: datetime = None) -> PokeReturnValue:
        month = data_interval_start.strftime("%Y-%m")
        return PokeReturnValue(is_done=extract.remote_size(month) is not None, xcom_value=month)

    @task
    def download(month: str) -> str:
        return str(extract.download(month))

    @task(pool="warehouse_load")         # at most 2 concurrent bulk loads, whatever the backfill width
    def load_raw(month: str, path: str) -> int:
        conn = PostgresHook(postgres_conn_id=config.WAREHOUSE_CONN_ID).get_conn()
        try:
            return load.load_month(conn, path, month)
        finally:
            conn.close()

    @task(outlets=[RAW_TRIPS], retries=0)  # a failed rule is a data problem, not a transient one
    def quality_gate(month: str, rows: int, data_interval_start: datetime = None,
                     data_interval_end: datetime = None, run_id: str = None) -> dict:
        conn = PostgresHook(postgres_conn_id=config.WAREHOUSE_CONN_ID).get_conn()
        try:
            results = quality.check(conn, month, data_interval_start.isoformat(), data_interval_end.isoformat(),
                                    run_id)
        finally:
            conn.close()
        for r in results:
            print(r)
        return {"month": month, "rows": rows, "warnings": [r.rule for r in results if not r.passed]}

    month = wait_for_file()
    rows = load_raw(month, download(month))
    quality_gate(month, rows)


taxi_ingest()
