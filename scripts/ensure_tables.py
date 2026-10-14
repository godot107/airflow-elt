"""Create the raw and audit tables if missing (normally the first load does this). Used before dbt unit
tests on a fresh warehouse, e.g. in CI. Runs inside the Airflow image."""
from airflow.providers.postgres.hooks.postgres import PostgresHook

from taxi import config, load

conn = PostgresHook(postgres_conn_id=config.WAREHOUSE_CONN_ID).get_conn()
with conn.cursor() as cur:
    cur.execute(load.DDL)
conn.commit()
conn.close()
print("raw and audit tables ready")
