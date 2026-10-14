"""Build demo.ipynb (run from anywhere):  python notebooks/build_notebook.py
Execute and keep outputs:  jupyter nbconvert --to notebook --execute --inplace notebooks/demo.ipynb"""
from pathlib import Path

import nbformat as nbf

HERE = Path(__file__).parent

CELLS = [
    """md:# Airflow ELT demo: drive the pipeline from a notebook

This notebook runs the demo through Airflow's REST API and reads the results from the warehouse. Every
action here is also a button in the Airflow UI (http://localhost:8080); keep both open side by side.

1. **Load a month** and watch its tasks.
2. **The quality gate's verdict**, read from the audit table.
3. **Data-aware scheduling:** the passing month's asset event starts `taxi_transform` (dbt).
4. **What landed** in the marts.
5. **Break a month** with an injected fault and watch the gate stop it.
6. **Fix and recover:** remove the fault, rerun from `load_raw`, and the month flows through.

**Where it runs:** the local Compose stack (`make up`), or the AWS demo through `deploy/tunnel.sh`,
which forwards the same two ports. Credentials come from `.env`, or from `AIRFLOW_PASSWORD` and
`WAREHOUSE_PASSWORD` in the environment (printed by `deploy/up.sh`).""",
    """import matplotlib.pyplot as plt
import pandas as pd
from airflow_demo import Airflow, sql
from IPython.display import Image, display

pd.set_option("display.width", 160)
pd.set_option("display.max_colwidth", 60)
MONTH_GOOD = "2024-05"     # a month to load cleanly (any published month works; reloading is safe)
MONTH_BAD = "2024-06"      # a month to corrupt on purpose
FAULT = "bad_zones"        # shift_pickups | bad_zones | missing_column (see include/taxi/faults.py)

af = Airflow()
af.unpause("taxi_ingest", "taxi_transform")
af.dags()""",
    """md:## The pipeline

`taxi_ingest` runs once per month of data and only a month that passes its quality gate publishes the
`raw_yellow_trips` asset; `taxi_transform` (dbt) runs on that asset, not on a clock.""",
    """display(Image("../docs/img/workflow.png", width=1100))""",
    """md:## 1. Load a month

A one-month backfill: the same call as `make backfill`, through the API. Watch the tasks move from
queued to running to success; the file is deleted once the month passes the gate.""",
    """transform_before = af.latest_run("taxi_transform")["dag_run_id"]
run_id = af.start_month(MONTH_GOOD)
af.watch("taxi_ingest", run_id)""",
    """md:## 2. The quality gate's verdict

Every rule, every load, lands in `audit.dq_results`, pass or fail. Error rules stop a month; warn rules
alert and let it through.""",
    """sql('''select rule, round(value::numeric, 4) as value, op, threshold, severity, passed
       from audit.dq_results
       where source_month = %s and checked_at = (select max(checked_at) from audit.dq_results where source_month = %s)
       order by severity, rule''', (f"{MONTH_GOOD}-01", f"{MONTH_GOOD}-01"))""",
    """md:## 3. Data-aware scheduling

The gate's success published an asset event, and that event created a `taxi_transform` run. dbt
rebuilds only the months reloaded since its last run, and only months whose latest gate passed.""",
    """display(af.asset_events(limit=3))
transform = af.wait_for_new_run("taxi_transform", after=transform_before)
af.watch("taxi_transform", transform["dag_run_id"])""",
    """md:## 4. What landed""",
    """sql('''select q.source_month, q.raw_rows, q.kept_rows, round(100 * q.excluded_share, 1) as excluded_pct,
              a.approved_at is not null as approved
       from marts.mart_data_quality q left join staging.approved_months a using (source_month)
       order by 1''')""",
    """demand = sql("select pickup_dow, pickup_hour, avg_trips from marts.mart_hourly_demand")
grid = demand.pivot(index="pickup_dow", columns="pickup_hour", values="avg_trips").astype(float)
zones = sql('''select zone_name, borough, sum(trips) as trips, round(sum(revenue)) as revenue
               from marts.mart_daily_zone where pickup_date >= %s and pickup_date < %s::date + interval '1 month'
               group by 1, 2 order by revenue desc limit 10''', (f"{MONTH_GOOD}-01", f"{MONTH_GOOD}-01"))

fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 3.8), gridspec_kw={"width_ratios": [1.6, 1]})
im = a1.imshow(grid.values, aspect="auto", cmap="viridis")
a1.set_yticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
a1.set_xticks(range(0, 24, 3), [f"{h:02d}:00" for h in range(0, 24, 3)])
a1.set_title("Average pickups per hour of week (all loaded months)")
fig.colorbar(im, ax=a1)
a2.barh(zones.zone_name[::-1], zones.revenue[::-1].astype(float) / 1e6)
a2.set_xlabel("revenue, $M")
a2.set_title(f"Top pickup zones by revenue, {MONTH_GOOD}")
plt.tight_layout()
plt.show()""",
    """md:## 5. Break a month

`set_fault` writes the `taxi_fault` Airflow Variable; `load_raw` corrupts that month's source batches
as if TLC had shipped a bad file. With `bad_zones`, 5% of pickup zone ids become 999.""",
    """af.set_fault(MONTH_BAD, FAULT)
transform_before = af.latest_run("taxi_transform")["dag_run_id"]
bad_run = af.start_month(MONTH_BAD)
af.watch("taxi_ingest", bad_run)""",
    """md:The gate failed on its first try (`retries=0`: bad data doesn't get better by waiting), the failure
alert fired, the download was kept for investigation, and no asset event was published, so dbt never
ran. The audit table says exactly why:""",
    """sql('''select rule, round(value::numeric, 4) as value, op, threshold, severity, passed
       from audit.dq_results
       where source_month = %s and checked_at = (select max(checked_at) from audit.dq_results where source_month = %s)
       order by passed, rule''', (f"{MONTH_BAD}-01", f"{MONTH_BAD}-01"))""",
    """print("latest taxi_transform run unchanged:", af.latest_run("taxi_transform")["dag_run_id"] == transform_before)
sql("select source_month from staging.approved_months order by 1")""",
    """md:## 6. Fix and recover

"Fix the source" (remove the fault), then clear `load_raw` and everything downstream of it: the same as
**Clear → Downstream** in the UI. The reload replaces the bad rows, the gate passes, the asset event
fires, and dbt picks the month up.""",
    """af.delete_fault()
af.rerun_from("taxi_ingest", bad_run, "load_raw")
af.watch("taxi_ingest", bad_run)""",
    """transform = af.wait_for_new_run("taxi_transform", after=transform_before)
af.watch("taxi_transform", transform["dag_run_id"])""",
    """sql('''select f.source_month, count(*) as trips_in_fct, a.approved_at
       from marts.fct_trips f join staging.approved_months a using (source_month)
       group by 1, 3 order by 1''')""",
    """md:## Recap

- **Idempotent loads:** every load replaces its month, so backfills, retries and reruns are safe.
- **Quality gate before transform:** a bad month stops at the gate, is recorded, and never reaches the marts.
- **Data-aware scheduling:** dbt runs because data changed, not because the clock struck.
- **Recovery is an ordinary Airflow action:** fix the cause, clear the task, everything downstream follows.""",
]


def build() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = [nbf.v4.new_markdown_cell(c[3:]) if c.startswith("md:") else nbf.v4.new_code_cell(c) for c in CELLS]
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    return nb


if __name__ == "__main__":
    nbf.write(build(), HERE / "demo.ipynb")
    print("wrote", HERE / "demo.ipynb")
