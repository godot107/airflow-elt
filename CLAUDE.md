# airflow-elt — Claude notes

Classic ELT warehouse on NYC TLC yellow-taxi trips, orchestrated by Airflow 3.3.2 (local Docker Compose) with
dbt via Cosmos. Trello #73 ("Airflow"). Portfolio piece for workflow orchestration.

## Run
```bash
make env up        # .env with random secrets, build image, start stack; UI http://localhost:8080 (admin / .env)
make test          # pytest inside the image: contract, quality rules, DAG integrity, warehouse reload test
make backfill FROM=2024-01-01 TO=2024-06-30
make psql          # warehouse; also on localhost:5433
make down          # `make nuke` also drops both Postgres volumes
```

## AWS demo deploy
- `infra/demo.yaml` + `deploy/*.sh` (runbook `deploy/README.md`). Ephemeral by design: up before a demo,
  down after; **no cloud schedule** (user asked; answer: create/delete beats start/stop for a few-hour demo).
- Safety net: `shutdown -h +MaxHours` first in UserData + `InstanceInitiatedShutdownBehavior: terminate`.
- No inbound SG rules; UI via SSM port forwarding (`tunnel.sh`, needs session-manager-plugin, installable
  without sudo via `dpkg -x`). Tags per shared/TAGGING.md: project=airflow-elt environment=dev component=lab.
- Not deployed yet as of 2026-10-14 (no aws session while the user was away). cfn-lint + CloudBurn clean.
- `dbt-core-experimental-parser` is pinned in the Dockerfile: dbt-core 1.12 pulls it, it is an sdist that
  downloads a sha256-checked binary from dbt Labs' GitHub releases at build time (x86_64 + aarch64).

## Layout
- `dags/taxi_ingest.py`: monthly interval, sensor (reschedule) → download → load_raw (pool `warehouse_load`=2) →
  quality_gate (outlet asset `raw_yellow_trips`).
- `dags/taxi_transform.py`: scheduled on that asset; Cosmos `DbtTaskGroup`, tests after each model.
- `include/taxi/`: config (contract + DQ rules), extract, load, quality, alerts, assets. `PYTHONPATH=/opt/airflow/include`.
- `dbt/taxi/`: staging view with `exclusion_reason`, incremental `fct_trips` (delete+insert by source_month),
  `dim_zones` (seed), marts `mart_daily_zone`, `mart_hourly_demand`, `mart_data_quality`. No dbt packages.

## Decisions
- **LocalExecutor**, not Celery: one machine, no Redis/worker; same scheduling semantics.
- **CronDataIntervalTimetable** explicitly: Airflow 3 defaults to trigger timetables (no interval), and each
  run must own one month. Backfill dates are logical dates = month start.
- **Idempotent load:** delete month + COPY in one transaction; streamed in 250k-row batches (constant memory).
- **Schema contract:** case-insensitive mapping, NULL for missing, log extras (TLC drift: Airport_fee,
  cbd_congestion_fee in 2025). Missing required column → fail.
- **DQ gate** before dbt: error rules fail the run and keep the asset from updating; warn rules only audit.
  Audit rows commit even on failure. `quality_gate` has retries=0.
- dbt in its own venv (`/home/airflow/dbt-venv`) so its pins don't fight Airflow's constraints.
- Airflow 3 gotchas: `Asset(name=..., uri=...)` (name is the first positional arg); `DagBag` has no
  `include_examples`; Cosmos `install_deps` → `ProjectConfig(install_dbt_deps=...)`.
- Data is downloaded at run time into `data/` (gitignored); only the 12 KB zone lookup seed is committed.
- Visuals: `docs/diagrams/*.mmd` rendered with minlag/mermaid-cli:11.17.0 into `docs/img/`; Airflow UI
  screenshots via headless Playwright (FAB login, "Show Graph", "Collapse Details Panel", expand groups,
  Options → Dependencies "External conditions" to show the asset); charts via `scripts/charts.py`.
- Cosmos test selection is `buildable`: with dbt's default "eager", a test spanning two models runs with the
  first parent and fails because the second doesn't exist yet.
- Postgres provider 7.x hook returns **psycopg 3** connections (`cursor.copy`, not `copy_expert`); `load._copy`
  handles both. Tests must use the hook, not raw psycopg2.
