"""Print a .env with random local secrets (stdlib only; the Fernet key is 32 url-safe base64 bytes).

    python3 scripts/make_env.py > .env            # fresh file
    python3 scripts/make_env.py --missing .env    # only keys .env lacks (make bi-env appends them)
"""
import base64
import os
import secrets
import sys


def values() -> dict[str, str]:
    tok = secrets.token_urlsafe
    return {
        "AIRFLOW_UID": str(os.getuid()),
        "AIRFLOW_ADMIN_USER": "admin",
        "AIRFLOW_ADMIN_PASSWORD": tok(12),
        "AIRFLOW_DB_PASSWORD": tok(16),
        "WAREHOUSE_PASSWORD": tok(16),
        "FERNET_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "JWT_SECRET": tok(32),
        "ALERT_WEBHOOK_URL": "",
        # BI add-on (make bi-up): Cube semantic layer + Superset
        "CUBE_DB_PASSWORD": tok(16),          # read-only warehouse role Cube connects as
        "CUBEJS_API_SECRET": tok(32),         # signs REST API tokens
        "CUBE_SQL_ADMIN_USER": "bi_admin",
        "CUBE_SQL_ADMIN_PASSWORD": tok(16),
        "CUBE_SQL_ANALYST_USER": "queens_analyst",
        "CUBE_SQL_ANALYST_PASSWORD": tok(16),
        "CUBE_SQL_ANALYST_BOROUGH": "Queens",
        "SUPERSET_SECRET_KEY": tok(42),
        "SUPERSET_ADMIN_PASSWORD": tok(12),
        "SUPERSET_DB_PASSWORD": tok(16),
    }


if __name__ == "__main__":
    have: set[str] = set()
    if len(sys.argv) == 3 and sys.argv[1] == "--missing":
        with open(sys.argv[2]) as f:
            have = {line.split("=", 1)[0] for line in f if "=" in line}
    for key, value in values().items():
        if key not in have:
            print(f"{key}={value}")
