"""Reloading a month replaces it: the idempotency the backfill story depends on. Needs the warehouse."""
import os

import pyarrow.parquet as pq
import pytest

from taxi import config, load

pytestmark = pytest.mark.skipif("AIRFLOW_CONN_WAREHOUSE" not in os.environ, reason="no warehouse")
MONTH = "1999-01"                       # a month no real load will ever use


@pytest.fixture
def conn():
    from airflow.providers.postgres.hooks.postgres import PostgresHook
    c = PostgresHook(postgres_conn_id=config.WAREHOUSE_CONN_ID).get_conn()     # the same driver the DAG gets
    yield c
    c.rollback()                        # a failed test may leave the transaction aborted
    with c.cursor() as cur:
        cur.execute(f"delete from {config.RAW_TABLE} where source_month = %s", (f"{MONTH}-01",))
    c.commit()
    c.close()


def test_reload_replaces_the_month(conn, tmp_path):
    from tests.test_contract import tlc_batch
    path = tmp_path / "m.parquet"
    pq.write_table(tlc_batch(n=1000), path)
    assert load.load_month(conn, path, MONTH, batch_rows=300) == 1000      # 4 COPY batches
    pq.write_table(tlc_batch(n=10), path)                                   # a "corrected" file
    load.load_month(conn, path, MONTH)
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {config.RAW_TABLE} where source_month = %s", (f"{MONTH}-01",))
        assert cur.fetchone()[0] == 10


def test_ddl_adds_new_contract_columns_to_an_existing_table(conn):
    """Contract evolution, on a throwaway table shaped like one created before cbd_congestion_fee existed."""
    table = "raw.pytest_contract_evolution"
    with conn.cursor() as cur:
        cur.execute(f"drop table if exists {table}")
        cur.execute(f"create table {table} (vendorid integer, source_month date not null, "
                    "loaded_at timestamptz not null default now())")
        cur.execute(load.ddl(table))
        cur.execute("select column_name, data_type from information_schema.columns "
                    "where table_schema = 'raw' and table_name = 'pytest_contract_evolution'")
        columns = dict(cur.fetchall())
        cur.execute(f"drop table {table}")
    conn.commit()
    assert set(config.COLUMNS) <= set(columns)
    assert columns["cbd_congestion_fee"] == "numeric"


def test_fault_reaches_the_table_and_the_gate_catches_it(conn, tmp_path):
    from taxi import quality
    from tests.test_contract import tlc_batch
    path = tmp_path / "m.parquet"
    pq.write_table(tlc_batch(n=100), path)
    load.load_month(conn, path, MONTH, fault="bad_zones")
    with pytest.raises(quality.DataQualityError, match="zone_ids_valid"):
        quality.check(conn, MONTH, "1970-01-01T00:00:00", "1970-01-02T00:00:00", run_id="pytest")
    with conn.cursor() as cur:
        cur.execute(f"delete from {config.AUDIT_TABLE} where run_id = 'pytest'")
    conn.commit()
