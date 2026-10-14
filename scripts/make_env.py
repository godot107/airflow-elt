"""Print a .env with random local secrets (stdlib only; the Fernet key is 32 url-safe base64 bytes)."""
import base64
import os
import secrets

print(f"""AIRFLOW_UID={os.getuid()}
AIRFLOW_ADMIN_USER=admin
AIRFLOW_ADMIN_PASSWORD={secrets.token_urlsafe(12)}
AIRFLOW_DB_PASSWORD={secrets.token_urlsafe(16)}
WAREHOUSE_PASSWORD={secrets.token_urlsafe(16)}
FERNET_KEY={base64.urlsafe_b64encode(os.urandom(32)).decode()}
JWT_SECRET={secrets.token_urlsafe(32)}""")
