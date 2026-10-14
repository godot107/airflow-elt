# Official Airflow image + the project's deps, installed at build time (not on every container start).
FROM apache/airflow:3.3.2-python3.12

COPY requirements-airflow.txt /tmp/requirements-airflow.txt
RUN pip install --no-cache-dir -r /tmp/requirements-airflow.txt \
      --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt

# dbt lives in its own venv so its pins never fight Airflow's; Cosmos calls this executable.
# dbt-core 1.12 pulls dbt-core-experimental-parser, an sdist whose build step downloads a prebuilt,
# sha256-checked binary from dbt Labs' GitHub releases (x86_64 and aarch64). Pinned: unpinned, every
# build would take whatever was published that day.
RUN python -m venv /home/airflow/dbt-venv \
 && /home/airflow/dbt-venv/bin/pip install --no-cache-dir \
      dbt-core==1.12.5 dbt-postgres==1.11.0 dbt-core-experimental-parser==2.0.5

ENV PYTHONPATH=/opt/airflow/include
