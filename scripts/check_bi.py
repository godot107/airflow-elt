"""Certify the BI add-on end to end (make bi-check). Fails loudly on any mismatch.

1. Three-way agreement: every metric served by Cube equals MetricFlow's and the hand-written marts'.
2. Row-level security: the analyst login sees only its borough, through both Cube APIs; no role = no data.
3. Rollups: dashboard-shaped queries are answered from the month x borough pre-aggregation (timed against
   the same aggregate run directly on Postgres).
4. Governance in Superset: datasets, metrics and the dashboard carry certification; demo viewers can open
   the certified dashboard but see no datasets, no database connections and no SQL Lab.
5. Adoption mart: built, and its KPIs are internally consistent.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import psycopg2
import requests

sys.path.insert(0, str(Path(__file__).parent))
from check_semantic_layer import mf_query, sql  # noqa: E402

CUBE = "http://localhost:4000/cubejs-api/v1/load"
SUPERSET = "http://localhost:8088"
REL_TOL = 1e-6  # Cube returns decimals as strings rounded to 9 places
failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {label}{(': ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def token(ctx: dict) -> str:
    def b64(b: bytes) -> bytes:
        return base64.urlsafe_b64encode(b).rstrip(b"=")
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({**ctx, "exp": int(time.time()) + 600}).encode())
    sig = b64(hmac.new(os.environ["CUBEJS_API_SECRET"].encode(), head + b"." + body, hashlib.sha256).digest())
    return (head + b"." + body + b"." + sig).decode()


def cube(query: dict, ctx: dict) -> dict:
    for _ in range(60):  # Cube answers "Continue wait" while a rollup builds
        r = requests.post(CUBE, json={"query": query}, headers={"Authorization": token(ctx)}, timeout=120)
        body = r.json()
        if body.get("error") != "Continue wait":
            return body
        time.sleep(2)
    raise TimeoutError(query)


def cube_rows(measures: list[str], dims: list[str], month: bool, ctx: dict) -> dict:
    q = {"measures": measures, "dimensions": dims, "limit": 50000}
    time_dim = "data_quality.source_month" if measures[0].startswith("data_quality") else "taxi_trips.pickup_date"
    if month:
        q["timeDimensions"] = [{"dimension": time_dim, "granularity": "month"}]
    out = {}
    for row in cube(q, ctx)["data"]:
        key = tuple(([row[f"{time_dim}.month"][:10]] if month else []) + [row[d] for d in dims])
        out[key] = {m.split(".")[1]: float(row[m]) for m in measures}
    return out


def close(a: dict, b: dict) -> tuple[bool, str]:
    if a.keys() != b.keys():
        return False, f"groups differ ({len(a)} vs {len(b)})"
    for key in a:
        for m, v in b[key].items():
            if abs(a[key][m] - v) > REL_TOL * max(1.0, abs(v)):
                return False, f"{key} {m}: {a[key][m]} vs {v}"
    return True, f"{len(a)} groups"


def three_way() -> None:
    admin = {"role": "admin"}
    c = cube_rows(["taxi_trips.trips", "taxi_trips.revenue"], ["pickup_zones.borough"], True, admin)
    m = mf_query("trips,revenue", "metric_time__month,pickup_zone__borough")
    marts = {(str(mo)[:10], b): {"trips": float(t), "revenue": float(r)} for mo, b, t, r in sql(
        "select date_trunc('month', pickup_date)::date, borough, sum(trips), sum(revenue) "
        "from marts.mart_daily_zone group by 1, 2")}
    for label, (a, b) in {"Cube = marts (trips, revenue by month x borough)": (c, marts),
                          "Cube = MetricFlow (same)": (c, m)}.items():
        check(*close(a, b)[:1], label, close(a, b)[1])

    c = cube_rows(["taxi_trips.card_tip_rate", "taxi_trips.revenue_per_trip", "taxi_trips.avg_fare",
                   "taxi_trips.avg_miles"], [], True, admin)
    m = mf_query("card_tip_rate,revenue_per_trip,avg_fare,avg_miles", "metric_time__month")
    ok, detail = close(c, m)
    check(ok, "Cube = MetricFlow (ratio metrics by month)", detail)

    c = cube_rows(["data_quality.kept_share"], [], True, admin)
    marts = {(str(mo)[:10],): {"kept_share": 1 - float(e)}
             for mo, e in sql("select source_month, excluded_share from marts.mart_data_quality")}
    ok, detail = close(c, marts)
    check(ok, "Cube = marts (kept_share by month)", detail)


def row_level_security() -> None:
    borough = os.environ["CUBE_SQL_ANALYST_BOROUGH"]
    analyst = {"role": "analyst", "borough": borough}
    q = ["taxi_trips.trips"]
    by_borough = cube_rows(q, ["pickup_zones.borough"], False, analyst)
    check(list(by_borough) == [(borough,)], "RLS (REST): analyst sees only its borough", str(list(by_borough)))
    admin_total = cube_rows(q, ["pickup_zones.borough"], False, {"role": "admin"})[(borough,)]["trips"]
    analyst_total = cube_rows(q, [], False, analyst)[()]["trips"]
    check(analyst_total == admin_total, "RLS (REST): analyst grand total = admin's borough total",
          f"{analyst_total:,.0f}")
    denied = cube({"measures": q}, {})
    check("Access denied" in str(denied.get("error")), "RLS: a token with no role is refused")

    conn = psycopg2.connect(host="localhost", port=15432, dbname="cube", user=os.environ["CUBE_SQL_ANALYST_USER"],
                            password=os.environ["CUBE_SQL_ANALYST_PASSWORD"])
    with conn, conn.cursor() as cur:
        cur.execute("select pickup_zones_borough, measure(trips) from taxi_operations group by 1")
        rows = cur.fetchall()
    check([r[0] for r in rows] == [borough], "RLS (SQL API, what Superset uses): analyst sees only its borough")


def rollups() -> None:
    q = {"measures": ["taxi_trips.trips", "taxi_trips.revenue_per_trip"], "dimensions": ["pickup_zones.borough"],
         "timeDimensions": [{"dimension": "taxi_trips.pickup_date", "granularity": "month"}]}
    cube(q, {"role": "admin"})  # warm: make sure the rollup is built
    times = []
    for i in range(5):
        # A filter that excludes nothing but changes each time defeats Cube's in-memory result cache, so
        # every timing is a real read of the rollup (borough is in the rollup, so it still matches).
        varied = {**q, "filters": [{"member": "pickup_zones.borough", "operator": "notEquals",
                                    "values": [f"no-such-borough-{time.time_ns()}-{i}"]}]}
        t0 = time.perf_counter()
        body = cube(varied, {"role": "admin"})
        times.append(time.perf_counter() - t0)
    cube_s = sorted(times)[2]  # median of 5
    used = list((body.get("usedPreAggregations") or {}).values())
    check(any(u.get("preAggregationId") == "taxi_trips.month_borough" for u in used),
          "Rollup: month x borough query served from the month_borough pre-aggregation")
    t0 = time.perf_counter()
    sql("select date_trunc('month', t.pickup_date), z.borough, count(*), sum(t.total_amount) / count(*) "
        "from marts.fct_trips as t join marts.dim_zones as z on z.zone_id = t.pickup_zone_id group by 1, 2")
    pg_s = time.perf_counter() - t0
    print(f"     timing: Postgres scan of fct_trips {pg_s:.2f} s vs Cube rollup {cube_s * 1000:.0f} ms (median of 5)")


def superset_governance() -> None:
    s = requests.Session()
    login = s.post(f"{SUPERSET}/api/v1/security/login", json={
        "username": "admin", "password": os.environ["SUPERSET_ADMIN_PASSWORD"], "provider": "db"}).json()
    s.headers["Authorization"] = f"Bearer {login['access_token']}"
    for table in ("taxi_operations", "data_health"):
        q = f"(filters:!((col:table_name,opr:eq,value:'{table}')))"
        ds_id = s.get(f"{SUPERSET}/api/v1/dataset/", params={"q": q}).json()["result"][0]["id"]
        ds = s.get(f"{SUPERSET}/api/v1/dataset/{ds_id}").json()["result"]
        certified = "certification" in json.loads(ds.get("extra") or "{}")
        metrics_ok = all("certification" in json.loads(m.get("extra") or "{}") for m in ds["metrics"])
        check(certified and metrics_ok, f"Superset: dataset {table} and its {len(ds['metrics'])} metrics certified")
    q = "(filters:!((col:dashboard_title,opr:eq,value:'Taxi operations')))"
    dash = s.get(f"{SUPERSET}/api/v1/dashboard/", params={"q": q}).json()["result"][0]
    check(bool(dash["certified_by"]) and dash["published"], "Superset: Taxi operations dashboard published + certified")

    v = requests.Session()
    login = v.post(f"{SUPERSET}/api/v1/security/login", json={
        "username": "ops_manager", "password": f"{os.environ['SUPERSET_ADMIN_PASSWORD']}-ops_manager",
        "provider": "db"}).json()
    v.headers["Authorization"] = f"Bearer {login['access_token']}"
    titles = [d["dashboard_title"] for d in v.get(f"{SUPERSET}/api/v1/dashboard/").json()["result"]]
    n_ds = v.get(f"{SUPERSET}/api/v1/dataset/").json()["count"]
    n_db = v.get(f"{SUPERSET}/api/v1/database/").json()["count"]
    sqllab = v.get(f"{SUPERSET}/api/v1/sqllab/").status_code
    check(titles == ["Taxi operations"] and n_ds == 0 and n_db == 0 and sqllab == 403,
          "Superset: viewer sees only the certified dashboard (no datasets, databases, SQL Lab)",
          f"dashboards={titles} datasets={n_ds} databases={n_db} sqllab={sqllab}")


def adoption() -> None:
    try:
        rows = sql("select * from marts.mart_bi_adoption order by event_date")
    except psycopg2.Error as exc:
        check(False, "Adoption mart exists (run the bi_usage DAG)", str(exc).splitlines()[0])
        return
    check(bool(rows), "Adoption mart has rows", f"{len(rows)} day(s)")
    for r in rows:
        date, viewers, makers, views, loads, cert_loads, share, uncert, uncert_on_cert = r
        share = None if share is None else float(share)
        consistent = cert_loads <= loads and (share is None or abs(share - cert_loads / loads) < 1e-9)
        check(consistent, f"Adoption {date}: certified loads / loads = share",
              f"viewers={viewers} makers={makers} views={views} loads={loads} certified={share:.0%} "
              f"uncertified charts in use={uncert}")


def main() -> int:
    three_way()
    row_level_security()
    rollups()
    superset_governance()
    adoption()
    print("PASS: BI add-on certified" if not failures else f"FAILED: {len(failures)} check(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
