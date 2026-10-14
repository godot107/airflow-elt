"""Load: one month of raw trips into Postgres, replacing that month in a single transaction.

Re-running a month (a retry, a backfill, a corrected file) leaves exactly one copy of it: delete and COPY
commit together or not at all.
"""
import io
import logging
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from taxi import config, faults

log = logging.getLogger(__name__)
ARROW_TYPES = {"integer": pa.int32(), "timestamp": pa.timestamp("us"), "double precision": pa.float64(),
               "text": pa.string()}

def ddl(table: str = config.RAW_TABLE) -> str:
    """Create the raw and audit tables if missing. Contract evolution: a column added to config.COLUMNS is
    added to an existing table too (NULL for months loaded before it existed)."""
    add_columns = "\n".join(f"alter table {table} add column if not exists {c} {t};" for c, t in config.COLUMNS.items())
    return f"""
create schema if not exists raw;
create schema if not exists audit;
create table if not exists {table} (
    {", ".join(f"{c} {t}" for c, t in config.COLUMNS.items())},
    source_month date not null,
    loaded_at timestamptz not null default now()
);
{add_columns}
create index if not exists {table.split(".")[-1]}_source_month on {table} (source_month);
create table if not exists {config.AUDIT_TABLE} (
    run_id text, source_month date, rule text, value double precision, op text, threshold double precision,
    severity text, passed boolean, checked_at timestamptz default now()
);
"""


DDL = ddl()


class ContractError(ValueError):
    """The source file breaks the raw contract. A data problem: retrying won't fix it."""


def conform(batch: pa.RecordBatch | pa.Table, month: str) -> tuple[pa.Table, list[str]]:
    """Map a TLC batch onto the raw contract: case-insensitive names, contract order and types, NULL for
    missing columns. Returns the table and the source columns the contract doesn't know about."""
    by_lower = {name.lower(): name for name in batch.schema.names}
    missing = [c for c in config.REQUIRED if c not in by_lower]
    if missing:
        raise ContractError(f"{month}: required columns missing from source: {missing}")
    cols = {}
    for c, sql_type in config.COLUMNS.items():
        target = ARROW_TYPES.get(sql_type, pa.float64())        # numeric(10,2) travels as float64, Postgres rounds
        cols[c] = batch.column(by_lower[c]).cast(target) if c in by_lower else pa.nulls(len(batch), target)
    cols["source_month"] = pa.array([f"{month}-01"] * len(batch), pa.string())
    extras = sorted(set(by_lower) - set(config.COLUMNS))
    return pa.table(cols), extras


def _copy(cur, sql: str, buf: io.BytesIO) -> None:
    """COPY FROM STDIN on either driver: the Postgres provider 7.x hook hands out psycopg 3 connections."""
    if hasattr(cur, "copy"):                     # psycopg 3
        with cur.copy(sql) as cp:
            cp.write(buf.getvalue())
    else:                                        # psycopg2
        buf.seek(0)
        cur.copy_expert(sql, buf)


def load_month(conn, path: Path, month: str, batch_rows: int = 250_000, fault: str | None = None) -> int:
    """Stream the parquet file in batches (constant memory) into one COPY per batch, inside one transaction.
    `fault` corrupts each source batch first (demo only, see taxi/faults.py)."""
    f = pq.ParquetFile(path)
    columns = [*config.COLUMNS, "source_month"]
    copy_sql = f"copy {config.RAW_TABLE} ({', '.join(columns)}) from stdin with (format csv)"
    rows, extras = 0, set()
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute(f"delete from {config.RAW_TABLE} where source_month = %s", (f"{month}-01",))
        replaced = cur.rowcount
        for batch in f.iter_batches(batch_size=batch_rows):
            if fault:
                batch = faults.corrupt(pa.Table.from_batches([batch]), fault)
            table, extra = conform(batch, month)
            extras.update(extra)
            buf = io.BytesIO()
            pacsv.write_csv(table, buf, pacsv.WriteOptions(include_header=False))
            _copy(cur, copy_sql, buf)
            rows += len(table)
    conn.commit()
    if extras:
        log.warning("%s: source columns outside the contract, not loaded: %s", month, sorted(extras))
    log.info("%s: loaded %d rows (replaced %d)", month, rows, replaced)
    return rows
