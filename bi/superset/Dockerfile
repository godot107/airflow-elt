# Superset 6 images ship without database drivers; add the Postgres one (Cube's SQL API speaks Postgres).
FROM apache/superset:6.1.0
USER root
RUN uv pip install --no-cache --python /app/.venv/bin/python psycopg2-binary==2.9.10
COPY superset_config.py /app/pythonpath/superset_config.py
COPY start.sh /app/start.sh
USER superset
CMD ["/app/start.sh"]
