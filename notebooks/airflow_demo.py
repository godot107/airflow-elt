"""Small helpers for the demo notebook: drive Airflow through its REST API (v2) and read the warehouse.

Works against the local Compose stack or the AWS demo through `deploy/tunnel.sh` (both forward Airflow to
localhost:8080 and the warehouse to localhost:5433). Credentials come from the project's .env locally, or
from AIRFLOW_PASSWORD / WAREHOUSE_PASSWORD in the environment (the AWS demo prints them).
"""
import os
import time
from pathlib import Path

import pandas as pd
import psycopg
import requests
from IPython.display import clear_output, display

ROOT = Path(__file__).resolve().parents[1]
STATE_ICON = {"success": "✅", "failed": "❌", "running": "⏳", "queued": "🕓", "scheduled": "🕓",
              "up_for_retry": "🔁", "up_for_reschedule": "💤", "upstream_failed": "⛔", "skipped": "⏭️",
              None: "·"}


def _env() -> dict:
    path = ROOT / ".env"
    env = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line) if path.exists() else {}
    env.update({k: v for k, v in os.environ.items() if k in ("AIRFLOW_PASSWORD", "WAREHOUSE_PASSWORD")})
    return env


class Airflow:
    """Token auth (FAB: POST /auth/token) and the handful of v2 endpoints the demo needs."""

    def __init__(self, url="http://localhost:8080", user="admin", password=None):
        env = _env()
        self.url = url.rstrip("/")
        self.user = user
        self.password = password or env.get("AIRFLOW_PASSWORD") or env["AIRFLOW_ADMIN_PASSWORD"]
        self.session = requests.Session()
        self._login()

    def _login(self):
        r = requests.post(f"{self.url}/auth/token", json={"username": self.user, "password": self.password},
                          timeout=30)
        r.raise_for_status()
        self.session.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    def call(self, method, path, **kw):
        r = self.session.request(method, f"{self.url}/api/v2{path}", timeout=60, **kw)
        if r.status_code == 401:                      # token expired: log in again once
            self._login()
            r = self.session.request(method, f"{self.url}/api/v2{path}", timeout=60, **kw)
        if not r.ok:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else None

    # --- reads ---------------------------------------------------------------------------------------
    def dags(self) -> pd.DataFrame:
        d = self.call("GET", "/dags", params={"tags": "taxi"})["dags"]
        return pd.DataFrame(d)[["dag_id", "is_paused", "timetable_description", "next_dagrun_run_after"]]

    def month_run(self, dag_id: str, month: str) -> dict | None:
        """The run whose logical date is the first of `month` (taxi_ingest runs are one month each)."""
        at = f"{month}-01T00:00:00Z"
        runs = self.call("GET", f"/dags/{dag_id}/dagRuns",
                         params={"logical_date_gte": at, "logical_date_lte": at, "order_by": "-run_after",
                                 "limit": 1})["dag_runs"]
        return runs[0] if runs else None

    def tasks(self, dag_id: str, run_id: str) -> pd.DataFrame:
        ti = self.call("GET", f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances", params={"limit": 100})
        df = pd.DataFrame(ti["task_instances"])[["task_id", "state", "try_number", "start_date", "end_date"]]
        start, end = (pd.to_datetime(df[c], utc=True, format="ISO8601") for c in ("start_date", "end_date"))
        df["seconds"] = (end - start).dt.total_seconds().round()
        df.insert(0, "", df.state.map(lambda s: STATE_ICON.get(s, "?")))
        return df.sort_values("start_date", na_position="last").drop(columns=["start_date", "end_date"])

    def latest_run(self, dag_id: str) -> dict | None:
        runs = self.call("GET", f"/dags/{dag_id}/dagRuns", params={"order_by": "-run_after", "limit": 1})["dag_runs"]
        return runs[0] if runs else None

    def asset_events(self, name="raw_yellow_trips", limit=5) -> pd.DataFrame:
        """Recent events of one asset (Cosmos also publishes an asset per dbt model; those are left out)."""
        assets = self.call("GET", "/assets", params={"name_pattern": name})["assets"]
        asset_id = next(a["id"] for a in assets if a["name"] == name)
        ev = self.call("GET", "/assets/events", params={"asset_id": asset_id, "order_by": "-timestamp",
                                                        "limit": limit})["asset_events"]
        return pd.DataFrame([{"timestamp": e["timestamp"][:19], "from_run": e["source_run_id"],
                              "triggered": ", ".join(f"{r['dag_id']} ({r['state']})" for r in e["created_dagruns"])}
                             for e in ev])

    # --- actions -------------------------------------------------------------------------------------
    def start_month(self, month: str, dag_id="taxi_ingest", timeout=120) -> str:
        """Backfill one month and return its run id once that run is (re)started. A month loaded before
        keeps its run id; the run is reset and runs again."""
        before = self.month_run(dag_id, month)
        self.backfill_month(month, dag_id)
        t0 = time.time()
        while time.time() - t0 < timeout:
            run = self.month_run(dag_id, month)
            if run and (before is None or run["state"] not in ("success", "failed")
                        or run.get("end_date") != before.get("end_date")):
                return run["dag_run_id"]
            time.sleep(2)
        raise TimeoutError(f"{dag_id} {month} did not start")

    def unpause(self, *dag_ids):
        for d in dag_ids:
            self.call("PATCH", f"/dags/{d}", json={"is_paused": False})

    def backfill_month(self, month: str, dag_id="taxi_ingest") -> dict:
        """One-month backfill. reprocess_behavior=completed: a month already loaded is loaded again,
        which is safe because loads replace the month."""
        return self.call("POST", "/backfills", json={
            "dag_id": dag_id, "from_date": f"{month}-01T00:00:00Z", "to_date": f"{month}-01T00:00:00Z",
            "reprocess_behavior": "completed", "max_active_runs": 1, "run_backwards": False, "dag_run_conf": {}})

    def set_fault(self, month: str, kind: str):
        import json
        self.delete_fault()
        self.call("POST", "/variables", json={"key": "taxi_fault", "value": json.dumps({month: kind})})

    def delete_fault(self):
        try:
            self.call("DELETE", "/variables/taxi_fault")
        except RuntimeError as e:
            if "404" not in str(e):
                raise

    def rerun_from(self, dag_id: str, run_id: str, task_id: str):
        """Clear a task and everything downstream of it, the UI's 'Clear' with downstream ticked."""
        return self.call("POST", f"/dags/{dag_id}/clearTaskInstances", json={
            "dry_run": False, "dag_run_id": run_id, "task_ids": [task_id], "include_downstream": True,
            "only_failed": False, "reset_dag_runs": True})

    def watch(self, dag_id: str, run_id: str, every=5, timeout=1800) -> str:
        """Redraw the run's task table until the run finishes; returns the final state."""
        t0 = time.time()
        while True:
            run = self.call("GET", f"/dags/{dag_id}/dagRuns/{run_id}")
            clear_output(wait=True)
            print(f"{dag_id} / {run_id}: {STATE_ICON.get(run['state'], '')} {run['state']}  "
                  f"({time.time() - t0:.0f}s)")
            display(self.tasks(dag_id, run_id))
            if run["state"] in ("success", "failed") or time.time() - t0 > timeout:
                return run["state"]
            time.sleep(every)

    def wait_for_new_run(self, dag_id: str, after: str | None, timeout=300) -> dict:
        """Wait until `dag_id` has a run newer than run id `after` (e.g. the asset-triggered transform)."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            run = self.latest_run(dag_id)
            if run and run["dag_run_id"] != after:
                return run
            time.sleep(3)
        raise TimeoutError(f"no new {dag_id} run within {timeout}s")


def warehouse() -> psycopg.Connection:
    env = _env()
    return psycopg.connect(host="localhost", port=5433, dbname="warehouse", user="warehouse",
                           password=env["WAREHOUSE_PASSWORD"], autocommit=True)


def sql(query: str, params=None) -> pd.DataFrame:
    with warehouse() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
