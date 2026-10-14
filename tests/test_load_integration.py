"""Reloading a month replaces it: the idempotency the backfill story depends on. Needs the warehouse."""
import os

import pyarrow as pa
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
