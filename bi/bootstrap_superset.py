"""Bootstrap Superset on the certified Cube views, through Superset's REST API. Idempotent (find-or-create).

Creates:
  - a database connection to Cube's SQL API (as the admin service login)
  - two certified datasets (taxi_operations, data_health) whose saved metrics are the Cube measures,
    each marked certified with a pointer to the check that certifies it
  - the "Taxi operations" dashboard (published, certified) and its charts
  - role "Taxi Viewer" + demo viewer accounts: with DASHBOARD_RBAC, the role grants that one dashboard and
    the data behind it, nothing else (no SQL Lab, no other datasets)

Run with the BI stack up:  make bi-up  (calls this)
"""
import json
import os
import sys
import time

import requests

BASE = "http://localhost:8088"
CERTIFIED_BY = "Data & Analytics"
CERT_DETAILS = "Defined once in the Cube semantic layer; certified against the marts by make bi-check."
LABELS = {
    "pickup_date": "Pickup date", "pickup_hour": "Pickup hour", "pickup_dow": "Pickup day of week",
    "payment_type": "Payment type", "pickup_zones_borough": "Pickup borough", "pickup_zones_zone_name": "Pickup zone",
    "pickup_zones_service_zone": "Pickup service zone", "dropoff_zones_borough": "Dropoff borough",
    "dropoff_zones_zone_name": "Dropoff zone", "source_month": "Source month",
}
VIEWERS = ["ops_manager", "finance_analyst", "dispatch_lead"]  # demo accounts (scripted usage only)
MAKERS = ["citizen_dev"]  # demo citizen developer: may build its own charts on the certified datasets
VIEWER_ROLE = "Taxi Viewer"

METRICS = {
    "taxi_operations": {
        "trips": "Trips",
        "revenue": "Revenue",
        "revenue_per_trip": "Revenue per trip",
        "avg_fare": "Average fare",
        "avg_miles": "Average trip miles",
        "card_tip_rate": "Card tip rate",
        "trips_mtd": "Trips, month to date",
    },
    "data_health": {
        "raw_rows": "Raw rows",
        "kept_rows": "Kept rows",
        "kept_share": "Share of raw rows kept",
    },
}


class Superset:
    def __init__(self, user: str, password: str):
        self.s = requests.Session()
        for _ in range(60):  # Superset may still be starting
            try:
                r = self.s.post(f"{BASE}/api/v1/security/login",
                                json={"username": user, "password": password, "provider": "db", "refresh": True})
                if r.ok:
                    break
            except requests.ConnectionError:
                pass
            time.sleep(5)
        r.raise_for_status()
        self.s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        csrf = self.s.get(f"{BASE}/api/v1/security/csrf_token/").json()["result"]
        self.s.headers.update({"X-CSRFToken": csrf, "Referer": BASE})

    def call(self, method: str, path: str, **kw) -> dict:
        r = self.s.request(method, f"{BASE}{path}", **kw)
        if not r.ok:
            sys.exit(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.text else {}

    def find(self, resource: str, col: str, value: str) -> dict | None:
        q = f"(filters:!((col:{col},opr:eq,value:'{value}')))"
        res = self.call("GET", f"/api/v1/{resource}/", params={"q": q})["result"]
        return res[0] if res else None


def ensure_database(ss: Superset) -> int:
    name = "Cube semantic layer (certified)"
    uri = (f"postgresql+psycopg2://{os.environ['CUBE_SQL_ADMIN_USER']}:{os.environ['CUBE_SQL_ADMIN_PASSWORD']}"
           "@cube:15432/cube")
    body = {"database_name": name, "sqlalchemy_uri": uri, "expose_in_sqllab": True, "allow_run_async": False}
    found = ss.find("database", "database_name", name)
    if found:
        ss.call("PUT", f"/api/v1/database/{found['id']}", json=body)
        return found["id"]
    return ss.call("POST", "/api/v1/database/", json=body)["id"]


def ensure_dataset(ss: Superset, db_id: int, table: str) -> int:
    found = ss.find("dataset", "table_name", table)
    ds_id = found["id"] if found else ss.call(
        "POST", "/api/v1/dataset/", json={"database": db_id, "schema": "public", "table_name": table})["id"]
    ss.call("PUT", f"/api/v1/dataset/{ds_id}/refresh")  # pick up columns from Cube's catalog
    current = ss.call("GET", f"/api/v1/dataset/{ds_id}")["result"]
    existing = {m["metric_name"]: m["id"] for m in current["metrics"]}
    metrics = [
        {
            **({"id": existing[name]} if name in existing else {}),
            "metric_name": name,
            "verbose_name": label,
            "expression": f"MEASURE({name})",
            "extra": json.dumps({"certification": {"certified_by": CERTIFIED_BY, "details": CERT_DETAILS}}),
        }
        for name, label in METRICS[table].items()
    ]
    # Measures arrive as columns too; hide them so users pick the certified metric, not SUM(column).
    columns = [
        {"id": c["id"], "column_name": c["column_name"], "is_dttm": c["is_dttm"],
         "verbose_name": LABELS.get(c["column_name"]),
         "filterable": c["column_name"] not in METRICS[table], "groupby": c["column_name"] not in METRICS[table]}
        for c in current["columns"]
    ]
    extra = {"certification": {"certified_by": CERTIFIED_BY, "details": CERT_DETAILS}}
    ss.call("PUT", f"/api/v1/dataset/{ds_id}", params={"override_columns": "false"},
            json={"metrics": metrics, "columns": columns, "extra": json.dumps(extra),
                  "description": f"Certified Cube view `{table}`."})
    return ds_id


def chart_specs(ops: int, dq: int) -> list[dict]:
    """(name, dataset, viz_type, params) for every chart on the dashboard, in layout order."""
    base = {"adhoc_filters": [], "row_limit": 10000}
    return [
        {"name": "Trips", "ds": ops, "viz": "big_number_total",
         "params": {**base, "metric": "trips", "subheader": "kept trips, gate-approved months",
                    "subheader_font_size": 0.15}},
        {"name": "Revenue per trip", "ds": ops, "viz": "big_number_total",
         "params": {**base, "metric": "revenue_per_trip", "y_axis_format": "$,.2f"}},
        {"name": "Card tip rate", "ds": ops, "viz": "big_number_total",
         "params": {**base, "metric": "card_tip_rate", "y_axis_format": ".1%",
                    "subheader": "card trips only", "subheader_font_size": 0.15}},
        {"name": "Data health: share of rows kept", "ds": dq, "viz": "big_number_total",
         "params": {**base, "metric": "kept_share", "y_axis_format": ".1%"}},
        # Bars, not a line: only some months are loaded, and a line would draw data across the gaps.
        {"name": "Trips by month (loaded months)", "ds": ops, "viz": "echarts_timeseries_bar",
         "params": {**base, "x_axis": "pickup_date", "time_grain_sqla": "P1M", "metrics": ["trips"],
                    "groupby": [], "y_axis_format": "SMART_NUMBER", "x_axis_time_format": "%b %Y"}},
        {"name": "Revenue by pickup borough", "ds": ops, "viz": "echarts_timeseries_bar",
         "params": {**base, "x_axis": "pickup_zones_borough", "metrics": ["revenue"], "groupby": [],
                    "orientation": "horizontal", "y_axis_format": "$,.3s",
                    "x_axis_sort": "revenue", "x_axis_sort_asc": True}},
        {"name": "Borough scorecard", "ds": ops, "viz": "table",
         "params": {**base, "query_mode": "aggregate", "groupby": ["pickup_zones_borough"],
                    "metrics": ["trips", "revenue_per_trip", "avg_miles", "card_tip_rate"],
                    "order_desc": True, "timeseries_limit_metric": "trips",
                    "column_config": {"card_tip_rate": {"d3NumberFormat": ".1%"},
                                      "revenue_per_trip": {"d3NumberFormat": "$,.2f"},
                                      "avg_miles": {"d3NumberFormat": ",.1f"}}}},
    ]


def ensure_dashboard(ss: Superset, ops: int, dq: int, role_id: int) -> int:
    title = "Taxi operations"
    found = ss.find("dashboard", "dashboard_title", title)
    dash_id = found["id"] if found else ss.call("POST", "/api/v1/dashboard/", json={"dashboard_title": title})["id"]

    chart_ids = []
    for spec in chart_specs(ops, dq):
        params = {**spec["params"], "viz_type": spec["viz"], "datasource": f"{spec['ds']}__table"}
        body = {"slice_name": spec["name"], "viz_type": spec["viz"], "datasource_id": spec["ds"],
                "datasource_type": "table", "params": json.dumps(params), "dashboards": [dash_id],
                "certified_by": CERTIFIED_BY, "certification_details": CERT_DETAILS}
        hit = ss.find("chart", "slice_name", spec["name"])
        if hit:
            ss.call("PUT", f"/api/v1/chart/{hit['id']}", json=body)
            chart_ids.append(hit["id"])
        else:
            chart_ids.append(ss.call("POST", "/api/v1/chart/", json=body)["id"])

    names = [s["name"] for s in chart_specs(ops, dq)]
    stale = ss.call("GET", "/api/v1/chart/", params={"q": "(page_size:100)"})["result"]
    for chart in stale:  # charts the bootstrap owns but no longer defines (makers' charts are left alone)
        if chart["slice_name"] not in names and chart["certified_by"] == CERTIFIED_BY:
            ss.call("DELETE", f"/api/v1/chart/{chart['id']}")
    rows = [chart_ids[0:4], chart_ids[4:6], chart_ids[6:7]]
    widths = [[3, 3, 3, 3], [6, 6], [12]]
    layout = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"],
                    "children": [f"ROW-{i}" for i in range(len(rows))]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": title}},
    }
    for i, (row, ws) in enumerate(zip(rows, widths, strict=True)):
        layout[f"ROW-{i}"] = {"type": "ROW", "id": f"ROW-{i}", "parents": ["ROOT_ID", "GRID_ID"],
                              "children": [f"CHART-{c}" for c in row], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for c, w in zip(row, ws, strict=True):
            layout[f"CHART-{c}"] = {"type": "CHART", "id": f"CHART-{c}", "children": [],
                                    "parents": ["ROOT_ID", "GRID_ID", f"ROW-{i}"],
                                    "meta": {"chartId": c, "width": w, "height": 28 if i == 0 else 60,
                                             "sliceName": names[chart_ids.index(c)]}}
    ss.call("PUT", f"/api/v1/dashboard/{dash_id}", json={
        "dashboard_title": title, "published": True, "roles": [role_id],
        "certified_by": CERTIFIED_BY, "certification_details": CERT_DETAILS,
        "position_json": json.dumps(layout),
        "json_metadata": json.dumps({"color_scheme": "supersetColors", "refresh_frequency": 0}),
    })
    return dash_id


def ensure_role_and_viewers(ss: Superset) -> int:
    roles = {r["name"]: r["id"] for r in ss.call(
        "GET", "/api/v1/security/roles/", params={"q": "(page_size:100)"})["result"]}
    if VIEWER_ROLE not in roles:
        roles[VIEWER_ROLE] = ss.call("POST", "/api/v1/security/roles/", json={"name": VIEWER_ROLE})["id"]
    users = {u["username"] for u in ss.call(
        "GET", "/api/v1/security/users/", params={"q": "(page_size:100)"})["result"]}
    accounts = [(n, [roles["Gamma"], roles[VIEWER_ROLE]]) for n in VIEWERS]
    accounts += [(n, [roles["Alpha"], roles[VIEWER_ROLE]]) for n in MAKERS]  # Alpha: build on any dataset
    for name, role_ids in accounts:
        if name not in users:
            ss.call("POST", "/api/v1/security/users/", json={
                "username": name, "first_name": name.split("_")[0].title(), "last_name": "Demo",
                "email": f"{name}@example.com", "active": True, "password": viewer_password(name),
                "roles": role_ids})
    return roles[VIEWER_ROLE]


def viewer_password(name: str) -> str:
    """Demo viewers share a password derived from the admin one (never printed, never committed)."""
    return f"{os.environ['SUPERSET_ADMIN_PASSWORD']}-{name}"


def main() -> None:
    ss = Superset("admin", os.environ["SUPERSET_ADMIN_PASSWORD"])
    db_id = ensure_database(ss)
    ops = ensure_dataset(ss, db_id, "taxi_operations")
    dq = ensure_dataset(ss, db_id, "data_health")
    role_id = ensure_role_and_viewers(ss)
    dash_id = ensure_dashboard(ss, ops, dq, role_id)
    print(f"Superset ready: {BASE}/superset/dashboard/{dash_id}/  (admin / SUPERSET_ADMIN_PASSWORD in .env)")


if __name__ == "__main__":
    main()
