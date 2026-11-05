"""Local Superset for the BI add-on. Metadata in its own Postgres; no Redis/Celery (single user, sync queries)."""
import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://superset:{os.environ['SUPERSET_DB_PASSWORD']}@superset-db:5432/superset"
)
CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}
DATA_CACHE_CONFIG = CACHE_CONFIG
TALISMAN_ENABLED = False      # localhost only; no TLS to enforce
WTF_CSRF_ENABLED = True
FEATURE_FLAGS = {"DASHBOARD_RBAC": True}
# Every dashboard view and chart query lands in the `logs` table (default DBEventLogger); the bi_usage DAG
# copies it into the warehouse for the adoption mart.
FAB_ADD_SECURITY_API = True   # users/roles API, used by bi/bootstrap_superset.py for the demo viewers
