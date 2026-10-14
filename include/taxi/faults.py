"""Fault injection for demos: corrupt a source batch the way a bad upstream file would, so the
pipeline's defenses can be shown failing safely. Activated per month by the `taxi_fault` Airflow
Variable (`make demo-bad-month`), never by default.

    shift_pickups   half the trips dated a year early        -> quality gate: pickup_in_month (error)
    bad_zones       5% of pickup zone ids set to 999          -> quality gate: zone_ids_valid (error)
    missing_column  the pickup zone column is absent          -> schema contract (load fails, no retry)
"""
import logging

import pyarrow as pa
import pyarrow.compute as pc

log = logging.getLogger(__name__)
KINDS = ("shift_pickups", "bad_zones", "missing_column")


def _col(table: pa.Table, lower: str) -> str:
    return next(n for n in table.column_names if n.lower() == lower)


def corrupt(table: pa.Table, kind: str) -> pa.Table:
    if kind not in KINDS:
        raise ValueError(f"unknown fault {kind!r}; choose from {KINDS}")
    log.warning("FAULT INJECTION ACTIVE: %s on %d rows", kind, len(table))
    every_other = pa.array([i % 2 == 0 for i in range(len(table))])
    if kind == "shift_pickups":
        year = pa.scalar(365 * 86_400_000_000, pa.duration("us"))
        for lower in ("tpep_pickup_datetime", "tpep_dropoff_datetime"):
            name = _col(table, lower)
            col = table[name]
            shifted = pc.if_else(every_other, pc.subtract(col, year), col)
            table = table.set_column(table.column_names.index(name), name, shifted)
        return table
    if kind == "bad_zones":
        name = _col(table, "pulocationid")
        one_in_20 = pa.array([i % 20 == 0 for i in range(len(table))])
        col = pc.if_else(one_in_20, pa.scalar(999, table[name].type), table[name])
        return table.set_column(table.column_names.index(name), name, col)
    return table.drop_columns([_col(table, "pulocationid")])
