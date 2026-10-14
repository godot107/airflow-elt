"""
### taxi_transform — dbt staging and marts, triggered by data, not by a clock

Runs whenever `taxi_ingest` publishes a month that passed its quality gate (the `raw_yellow_trips` asset).
Cosmos renders the dbt project as Airflow tasks, one per seed and model with its tests right after it, so a
failed test stops everything downstream of that model and shows up in the graph by name.

`fct_trips` is incremental: it rebuilds only the months whose raw rows were (re)loaded since its last run.
"""
from datetime import timedelta

import pendulum
from airflow.sdk import dag
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import TestBehavior, TestIndirectSelection
from cosmos.profiles import PostgresUserPasswordProfileMapping

from taxi import config
from taxi.alerts import on_failure
from taxi.assets import RAW_TRIPS

DBT_PROJECT = "/opt/airflow/dbt/taxi"


@dag(
    dag_id="taxi_transform",
    schedule=[RAW_TRIPS],
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,                   # dbt runs never overlap; queued asset events fold into the next run
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2), "on_failure_callback": on_failure},
    tags=["taxi", "elt", "dbt"],
    doc_md=__doc__,
)
def taxi_transform():
    DbtTaskGroup(
        group_id="dbt",
        project_config=ProjectConfig(DBT_PROJECT, install_dbt_deps=False),   # no dbt packages
        profile_config=ProfileConfig(
            profile_name="taxi", target_name="dev",
            profile_mapping=PostgresUserPasswordProfileMapping(conn_id=config.WAREHOUSE_CONN_ID,
                                                               profile_args={"schema": "analytics"})),
        # "buildable": a test that spans two models (mart reconciles to fact) runs after the later one,
        # not with whichever parent dbt selects first.
        execution_config=ExecutionConfig(dbt_executable_path="/home/airflow/dbt-venv/bin/dbt",
                                         test_indirect_selection=TestIndirectSelection.BUILDABLE),
        render_config=RenderConfig(test_behavior=TestBehavior.AFTER_EACH),
    )


taxi_transform()
