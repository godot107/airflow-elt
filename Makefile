# Local Airflow ELT demo. `make env up` then open http://localhost:8080
COMPOSE := docker compose
RUN := $(COMPOSE) run --rm airflow-cli
FROM ?= 2024-01-01
TO   ?= 2024-06-30

.PHONY: env up down nuke test dbt dbt-unit check lint docs docs-down demo-bad-month demo-recover backfill psql logs notebook

env:            ## write .env with random secrets (won't overwrite)
	@test -f .env && echo ".env exists, leaving it" || python3 scripts/make_env.py > .env

up:             ## build the image and start Airflow + warehouse
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

nuke:           ## stop and delete all data volumes (metadata + warehouse)
	$(COMPOSE) down -v

test:           ## pytest inside the Airflow image: contract, faults, alerts, quality rules, DAGs, warehouse
	$(RUN) bash -c "cd /opt/airflow && python -m pytest -q tests"

DBT := cd /opt/airflow/dbt/taxi && /home/airflow/dbt-venv/bin/dbt
dbt:            ## any dbt command against the warehouse: make dbt ARGS="ls --resource-type model"
	$(RUN) bash -c "$(DBT) $(ARGS) --profiles-dir ."

dbt-unit:       ## dbt unit tests in unit_* schemas (creates raw/audit tables if missing; parents built empty)
	$(RUN) bash -c "python /opt/airflow/scripts/ensure_tables.py \
	  && $(DBT) run --target unit --empty --select +fct_trips --profiles-dir . \
	  && $(DBT) test --target unit --select test_type:unit --profiles-dir ."

lint:           ## ruff (Python) + sqlfluff (dbt SQL); same versions as CI and pre-commit
	ruff check . && sqlfluff lint dbt/taxi/models

check: lint test dbt-unit

docs:           ## dbt docs site on http://localhost:8081 (lineage graph, column docs)
	$(COMPOSE) --profile docs up -d --build dbt-docs
	@echo "dbt docs: http://localhost:8081"

docs-down:
	$(COMPOSE) --profile docs stop dbt-docs

MONTH ?= 2024-04
FAULT ?= shift_pickups
demo-bad-month: ## load MONTH with a corrupted source (FAULT=shift_pickups|bad_zones|missing_column) and watch it fail
	$(RUN) airflow variables set taxi_fault '{"$(MONTH)": "$(FAULT)"}'
	@# A backfill, not `dags trigger`: in Airflow 3 a manual run's data interval comes from the current time,
	@# not from --logical-date, so a trigger would load this month's (unpublished) data instead of MONTH.
	$(RUN) airflow backfill create --dag-id taxi_ingest --from-date $(MONTH)-01 --to-date $(MONTH)-01

demo-recover:   ## "fix the source" (drop the fault) and rerun the failed month from load_raw
	$(RUN) airflow variables delete taxi_fault
	$(RUN) airflow tasks clear taxi_ingest -t "load_raw" -s $(MONTH)-01 -e $(MONTH)-01 -d -y

notebook:       ## the demo notebook (host Python with jupyter, pandas, matplotlib)
	jupyter lab notebooks/demo.ipynb

backfill:       ## load months FROM..TO: make backfill FROM=2024-01-01 TO=2024-06-30
	$(RUN) airflow dags unpause taxi_ingest
	$(RUN) airflow dags unpause taxi_transform
	$(RUN) airflow dags unpause taxi_housekeeping
	$(RUN) airflow backfill create --dag-id taxi_ingest --from-date $(FROM) --to-date $(TO) --max-active-runs 3

psql:           ## open psql on the warehouse
	$(COMPOSE) exec warehouse psql -U warehouse warehouse

logs:
	$(COMPOSE) logs -f --tail 50 airflow-scheduler
