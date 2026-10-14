# Demo script (~15 minutes)

Two windows side by side: the **Airflow UI** (http://localhost:8080) and **`notebooks/demo.ipynb`**. The
notebook drives everything through the REST API; the UI shows the same thing happening. Works the same
locally (`make up`) and on AWS (`deploy/up.sh`, then `deploy/tunnel.sh`).

## Before the audience arrives

| Local | AWS |
|---|---|
| `make up` | `deploy/preflight.sh` then `deploy/up.sh` (~15 min) |
| `make backfill FROM=2024-01-01 TO=2024-04-30` if the warehouse is empty | done at boot (Jan–Mar 2024) |
| | `deploy/smoke.sh` (all ok), `deploy/tunnel.sh` in its own terminal |
| `make docs` (dbt docs on :8081) | |
| open the UI, log in, open the notebook | `export AIRFLOW_PASSWORD=... WAREHOUSE_PASSWORD=...` (printed by `up.sh`), open the notebook |

Pick months the warehouse hasn't loaded for `MONTH_GOOD` and `MONTH_BAD` in the notebook's first cell
(reloading a month also works; it just isn't "new").

## Talk track

1. **The problem (1 min).** "Pipelines don't fail on the happy path. They fail on retries, backfills,
   late files and bad files. This one is built for those." Show `docs/img/workflow.png` (notebook cell).
2. **Load a month (3 min).** Run section 1. In the UI: Dags → taxi_ingest → Grid, the new run going
   green. Point at `wait_for_file` (a sensor that frees its slot while waiting; TLC publishes two months
   late), `load_raw` (delete + COPY in one transaction: rerunning replaces, never duplicates), the pool.
3. **The gate (2 min).** Section 2: seven rules, every result in `audit.dq_results`. "Negative fares are
   1–2% every month; they're refunds, so that rule warns instead of stopping the load. Thresholds come
   from measuring the data." Mention January 2025, where both warning rules fired for real.
4. **Data-aware scheduling (2 min).** Section 3. UI: Assets → raw_yellow_trips → the event and the
   `taxi_transform` run it created. Graph view: every dbt model is a `run` task followed by its `test` task.
5. **Results (1 min).** Section 4: the data-quality mart and the demand heatmap.
6. **Break it (3 min).** Section 5. UI: the run turns red at `quality_gate` on the first try, with no
   retries. "The month is in raw, because raw is a landing zone, but it never reaches the marts: no asset
   event, and `fct_trips` only takes months whose latest gate passed. The file is kept for investigation."
7. **Recover (2 min).** Section 6: remove the fault, clear `load_raw` with downstream (show the same
   button in the UI), green, transform runs, the month is in the fact table.
8. **Close (1 min).** CI on every push (lint, pytest, dbt unit tests); `make check` locally; the same
   stack on EC2 with no open ports and a self-destruct timer.

## Afterwards

Local: `make down` (data is kept; `make nuke` deletes it). AWS: `deploy/down.sh`.

## If something goes wrong live

| Symptom | Fix |
|---|---|
| A run sits in `queued` | Check the DAG is unpaused (notebook's first cell does it); `make logs` |
| Notebook `401`/connection refused | Tunnel closed (AWS) or stack down (local); restart it, rerun the cell |
| `wait_for_file` sleeping (`up_for_reschedule`) | That month isn't published yet; pick an older one |
| Leftover fault | `make demo-recover MONTH=...` or `af.delete_fault()` |
