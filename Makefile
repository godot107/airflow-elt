# Local Airflow ELT demo. `make env up` then open http://localhost:8080
COMPOSE := docker compose
RUN := $(COMPOSE) run --rm airflow-cli
FROM ?= 2024-01-01
TO   ?= 2024-06-30

.PHONY: env up down nuke test backfill psql logs

env:            ## write .env with random secrets (won't overwrite)
	@test -f .env && echo ".env exists, leaving it" || python3 scripts/make_env.py > .env

up:             ## build the image and start Airflow + warehouse
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

nuke:           ## stop and delete all data volumes (metadata + warehouse)
	$(COMPOSE) down -v

test:           ## unit tests + DAG integrity, inside the Airflow image
	$(RUN) bash -c "cd /opt/airflow && python -m pytest -q tests"

backfill:       ## load months FROM..TO: make backfill FROM=2024-01-01 TO=2024-06-30
	$(RUN) airflow dags unpause taxi_ingest
	$(RUN) airflow dags unpause taxi_transform
	$(RUN) airflow backfill create --dag-id taxi_ingest --from-date $(FROM) --to-date $(TO) --max-active-runs 3

psql:           ## open psql on the warehouse
	$(COMPOSE) exec warehouse psql -U warehouse warehouse

logs:
	$(COMPOSE) logs -f --tail 50 airflow-scheduler
