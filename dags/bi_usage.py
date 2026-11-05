"""
### bi_usage — measure BI adoption with the same pipeline as the data

Daily: copy Superset's usage log (dashboard views, chart loads, chart edits) into `raw.bi_usage_events`,
then dbt builds `mart_bi_adoption` (active viewers and makers, views, and how much of what people load is
certified). Part of the optional BI add-on (`make bi-up`); when Superset is not running the run is skipped,
not failed.
"""
import logging
from datetime import timedelta

import pendulum
from airflow.exceptions import AirflowSkipException
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import dag, task
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import TestBehavior
from cosmos.profiles import PostgresUserPasswordProfileMapping

from bi import usage
from taxi import config
from taxi.alerts import on_failure

log = logging.getLogger(__name__)


@dag(
    dag_id="bi_usage",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2), "on_failure_callback": on_failure},
    tags=["bi", "adoption", "dbt"],
    doc_md=__doc__,
)
def bi_usage():
    @task
    def sync_usage_log() -> int:
        try:
            superset = PostgresHook(postgres_conn_id=usage.SUPERSET_CONN_ID).get_conn()
        except Exception as exc:  # noqa: BLE001 -- any connection failure means the add-on is down
            raise AirflowSkipException(f"Superset metadata DB unreachable (BI add-on not running?): {exc}") from exc
        warehouse = PostgresHook(postgres_conn_id=config.WAREHOUSE_CONN_ID).get_conn()
        try:
            inserted = usage.sync(warehouse, superset)
        finally:
            warehouse.close()
            superset.close()
        log.info("inserted %s usage events", inserted)
        return inserted

    adoption = DbtTaskGroup(
        group_id="dbt_adoption",
        project_config=ProjectConfig("/opt/airflow/dbt/taxi", install_dbt_deps=False),
        profile_config=ProfileConfig(
            profile_name="taxi", target_name="dev",
            profile_mapping=PostgresUserPasswordProfileMapping(conn_id=config.WAREHOUSE_CONN_ID,
                                                               profile_args={"schema": "analytics"})),
        execution_config=ExecutionConfig(dbt_executable_path="/home/airflow/dbt-venv/bin/dbt"),
        render_config=RenderConfig(select=["tag:bi"], test_behavior=TestBehavior.AFTER_EACH),
    )

    sync_usage_log() >> adoption


bi_usage()
