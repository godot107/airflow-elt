"""DAG integrity: both DAGs parse, and the operational settings the README promises are actually set."""
import pytest
from airflow.dag_processing.dagbag import DagBag


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder="/opt/airflow/dags")   # examples are off in this deployment


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}
    assert {"taxi_ingest", "taxi_transform", "taxi_housekeeping"} <= set(dagbag.dag_ids)


def test_ingest_shape_and_safety(dagbag):
    dag = dagbag.get_dag("taxi_ingest")
    assert [t.task_id for t in dag.topological_sort()] == ["wait_for_file", "download", "load_raw", "quality_gate",
                                                           "remove_download"]
    assert dag.get_task("remove_download").upstream_task_ids == {"download", "quality_gate"}
    assert dag.catchup is False
    assert dag.get_task("load_raw").pool == "warehouse_load"
    assert dag.get_task("wait_for_file").mode == "reschedule"
    assert dag.get_task("quality_gate").retries == 0
    assert [a.name for a in dag.get_task("quality_gate").outlets] == ["raw_yellow_trips"]
    for t in dag.tasks:
        assert t.on_failure_callback


def test_transform_is_data_aware_and_tests_follow_models(dagbag):
    dag = dagbag.get_dag("taxi_transform")
    assert "raw_yellow_trips" in str(dag.timetable.asset_condition)
    ids = {t.task_id for t in dag.tasks}
    assert "dbt.fct_trips.run" in ids and "dbt.fct_trips.test" in ids
    assert dag.get_task("dbt.fct_trips.test").downstream_task_ids >= {"dbt.mart_daily_zone.run"}


def test_housekeeping_is_weekly(dagbag):
    dag = dagbag.get_dag("taxi_housekeeping")
    assert {t.task_id for t in dag.tasks} == {"prune_downloads", "prune_logs"}
    assert dag.timetable.expression in ("@weekly", "0 0 * * 0")
