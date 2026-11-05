"""Prove the semantic layer and the hand-written marts agree.

The point of a semantic layer is one definition per metric. This script asks MetricFlow for metrics by
name, recomputes the same numbers from the marts (and fct_trips for the card tip rate, which the mart only
stores per day and zone), and fails if any value differs beyond floating-point noise.

Run from the repo root with the stack up:  make semantic-check
"""
import csv
import io
import os
import subprocess
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = ROOT / "dbt" / "taxi"
MF = ROOT / ".venv-mf" / "bin" / "mf"
REL_TOL = 1e-9


def mf_query(metrics: str, group_by: str) -> dict[tuple, dict[str, float]]:
    out = subprocess.run(
        [str(MF), "query", "--metrics", metrics, "--group-by", group_by, "--csv", "/dev/stdout", "--quiet"],
        cwd=DBT_DIR, check=True, capture_output=True, text=True,
        env={**os.environ, "DBT_TARGET": "host"},
    ).stdout
    rows = list(csv.DictReader(io.StringIO(out[out.index(group_by.split(",")[0]):])))
    keys = group_by.split(",")
    def key(r: dict) -> tuple:
        return tuple(r[k][:10] if k.startswith("metric_time") else r[k] for k in keys)  # dates: drop the time

    return {key(r): {m: float(r[m]) for m in metrics.split(",")} for r in rows}


def sql(query: str) -> list[tuple]:
    with psycopg2.connect(host="localhost", port=5433, dbname="warehouse", user="warehouse",
                          password=os.environ["WAREHOUSE_PASSWORD"]) as conn, conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def compare(name: str, semantic: dict, expected: dict) -> int:
    failures = 0
    if semantic.keys() != expected.keys():
        print(f"FAIL {name}: groups differ ({len(semantic)} semantic vs {len(expected)} mart)")
        return 1
    for key, exp in expected.items():
        for metric, value in exp.items():
            got = semantic[key][metric]
            if abs(got - value) > REL_TOL * max(1.0, abs(value)):
                print(f"FAIL {name} {key} {metric}: semantic {got} vs mart {value}")
                failures += 1
    n_metrics = len(next(iter(expected.values())))
    print(f"{'ok  ' if not failures else 'FAIL'} {name}: {len(expected)} groups x {n_metrics} metrics")
    return failures


def main() -> int:
    failures = 0

    # trips + revenue by month and pickup borough vs mart_daily_zone
    semantic = mf_query("trips,revenue", "metric_time__month,pickup_zone__borough")
    mart = {
        (str(m)[:10], b): {"trips": float(t), "revenue": float(r)}
        for m, b, t, r in sql("""
            select date_trunc('month', pickup_date)::date, borough, sum(trips), sum(revenue)
            from marts.mart_daily_zone group by 1, 2""")
    }
    failures += compare("trips, revenue by month x borough (mart_daily_zone)", semantic, mart)

    # card tip rate by month vs fct_trips (same rule as mart_daily_zone: card trips only)
    semantic = mf_query("card_tip_rate,revenue_per_trip", "metric_time__month")
    fct = {
        (str(m)[:10],): {"card_tip_rate": float(c), "revenue_per_trip": float(r)}
        for m, c, r in sql("""
            select date_trunc('month', pickup_date)::date,
                   sum(tip_amount) filter (where payment_type = 1)
                   / sum(fare_amount) filter (where payment_type = 1),
                   avg(total_amount)
            from marts.fct_trips group by 1""")
    }
    failures += compare("card_tip_rate, revenue_per_trip by month (fct_trips)", semantic, fct)

    # data-quality kept share vs mart_data_quality
    semantic = mf_query("kept_share", "metric_time__month")
    dq = {
        (str(m)[:10],): {"kept_share": 1 - float(e)}
        for m, e in sql("select source_month, excluded_share from marts.mart_data_quality")
    }
    failures += compare("kept_share by month (mart_data_quality)", semantic, dq)

    print("PASS: semantic layer matches the marts" if not failures else f"{failures} mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
