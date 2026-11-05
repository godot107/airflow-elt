"""Generate a small, clearly-labelled burst of demo BI usage so the adoption pipeline has something to measure.

Real activity through the real UI (headless Chromium logs in and opens dashboards, so Superset records the
same events a person would generate), timestamped now; nothing is backdated or written to the log directly.
  - the three demo viewers open the certified "Taxi operations" dashboard (ops_manager twice)
  - the demo citizen developer builds an uncertified chart on the certified dataset, puts it on a personal
    dashboard, and opens both dashboards

    set -a; . ./.env; set +a; python bi/simulate_usage.py      (shared workspace venv: playwright + requests)
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from bootstrap_superset import BASE, Superset, viewer_password  # noqa: E402

MAKER = "citizen_dev"
MAKER_CHART = "Trips by pickup hour (citizen copy)"
MAKER_DASH = "My taxi notes"


def password(user: str) -> str:
    return os.environ["SUPERSET_ADMIN_PASSWORD"] if user == "admin" else viewer_password(user)


def maker_builds() -> int:
    """As the citizen developer: an uncertified chart + personal dashboard. Returns the dashboard id."""
    ss = Superset(MAKER, password(MAKER))
    ds = ss.find("dataset", "table_name", "taxi_operations")["id"]
    dash = ss.find("dashboard", "dashboard_title", MAKER_DASH)
    dash_id = dash["id"] if dash else ss.call("POST", "/api/v1/dashboard/", json={"dashboard_title": MAKER_DASH})["id"]
    params = {"viz_type": "echarts_timeseries_bar", "datasource": f"{ds}__table", "x_axis": "pickup_hour",
              "metrics": ["trips"], "groupby": [], "adhoc_filters": [], "row_limit": 100}
    body = {"slice_name": MAKER_CHART, "viz_type": "echarts_timeseries_bar", "datasource_id": ds,
            "datasource_type": "table", "params": json.dumps(params), "dashboards": [dash_id]}
    hit = ss.find("chart", "slice_name", MAKER_CHART)
    chart_id = hit["id"] if hit else ss.call("POST", "/api/v1/chart/", json=body)["id"]
    layout = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"], "children": ["ROW-0"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": MAKER_DASH}},
        "ROW-0": {"type": "ROW", "id": "ROW-0", "parents": ["ROOT_ID", "GRID_ID"], "children": [f"CHART-{chart_id}"],
                  "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        f"CHART-{chart_id}": {"type": "CHART", "id": f"CHART-{chart_id}", "children": [],
                              "parents": ["ROOT_ID", "GRID_ID", "ROW-0"],
                              "meta": {"chartId": chart_id, "width": 12, "height": 60, "sliceName": MAKER_CHART}},
    }
    ss.call("PUT", f"/api/v1/dashboard/{dash_id}", json={"position_json": json.dumps(layout)})
    return dash_id


def open_dashboards(user: str, dashboard_ids: list[int], browser) -> None:
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"{BASE}/login/")
    page.fill("input[name=username], #username", user)
    page.fill("input[name=password], #password", password(user))
    page.keyboard.press("Enter")
    page.wait_for_url(lambda u: "/login" not in u, timeout=30_000)
    for dash_id in dashboard_ids:
        page.goto(f"{BASE}/superset/dashboard/{dash_id}/")
        page.wait_for_selector(".dashboard-component-chart-holder", timeout=60_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)  # chart-load events are posted from the browser after render
    page.close()
    print(f"{user}: opened dashboards {dashboard_ids}")


def main() -> None:
    admin = Superset("admin", password("admin"))
    certified = admin.find("dashboard", "dashboard_title", "Taxi operations")["id"]
    personal = maker_builds()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        open_dashboards("ops_manager", [certified, certified], browser)
        open_dashboards("finance_analyst", [certified], browser)
        open_dashboards("dispatch_lead", [certified], browser)
        open_dashboards(MAKER, [certified, personal], browser)
        browser.close()


if __name__ == "__main__":
    main()
