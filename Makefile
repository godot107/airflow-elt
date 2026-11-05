# Local Airflow ELT demo. `make env up` then open http://localhost:8080
COMPOSE := docker compose
RUN := $(COMPOSE) run --rm airflow-cli
FROM ?= 2024-01-01
TO   ?= 2024-06-30

.PHONY: env up down nuke test dbt dbt-unit check lint docs docs-down demo-bad-month demo-recover backfill psql logs notebook semantic-setup mf semantic-check bi-env bi-up bi-down bi-check

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

semantic-setup: ## host venv (.venv-mf) with the MetricFlow CLI for the semantic layer
	python3 -m venv .venv-mf && .venv-mf/bin/pip install -q -r requirements-semantic.txt

# dbt/taxi/target is shared with the Airflow image, and `make dbt-unit` leaves a manifest pointing at the
# unit_* schemas, so every MetricFlow entry point re-parses against the real warehouse first (~3 s).
MF_PARSE := DBT_TARGET=host ../../.venv-mf/bin/dbt parse --profiles-dir . --quiet

mf:             ## query metrics by name: make mf ARGS="query --metrics trips,revenue --group-by metric_time__month"
	@set -a && . ./.env && set +a && cd dbt/taxi && $(MF_PARSE) && DBT_TARGET=host ../../.venv-mf/bin/mf $(ARGS)

semantic-check: ## validate the semantic layer against the warehouse and prove it matches the marts
	@set -a && . ./.env && set +a && cd dbt/taxi && $(MF_PARSE) \
	  && DBT_TARGET=host ../../.venv-mf/bin/dbt build --select metricflow_time_spine --profiles-dir . --quiet \
	  && DBT_TARGET=host ../../.venv-mf/bin/mf validate-configs 2>&1 | grep -E "ERRORS|ERROR:" | sed "s/.*[✔✖] //"
	@set -a && . ./.env && set +a && .venv-mf/bin/python scripts/check_semantic_layer.py

bi-env:         ## append any missing BI secrets to an existing .env
	python3 scripts/make_env.py --missing .env >> .env

bi-up: bi-env   ## BI add-on: Cube semantic layer (:4000 REST, :15432 SQL) + Superset (:8088), then bootstrap
	$(COMPOSE) --profile bi up -d --build cubestore cube superset-db superset
	@set -a && . ./.env && set +a && $(COMPOSE) exec -T warehouse psql -q -U warehouse -d warehouse \
	  -v pw="$$CUBE_DB_PASSWORD" < bi/warehouse_reader.sql
	$(COMPOSE) --profile bi restart cube
	@set -a && . ./.env && set +a && .venv-mf/bin/python bi/bootstrap_superset.py

bi-down:        ## stop the BI add-on (volumes kept)
	$(COMPOSE) --profile bi stop cubestore cube superset-db superset

bi-check:       ## certify: Cube = MetricFlow = marts, row-level security, rollups used, Superset dashboard serves
	@set -a && . ./.env && set +a && cd dbt/taxi && $(MF_PARSE)
	@set -a && . ./.env && set +a && .venv-mf/bin/python scripts/check_bi.py

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
