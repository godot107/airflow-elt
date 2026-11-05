#!/bin/bash
# Migrate, make sure the admin exists, then serve. Safe to rerun on every start.
set -euo pipefail
superset db upgrade
superset fab create-admin --username admin --firstname BI --lastname Admin \
  --email admin@localhost --password "$SUPERSET_ADMIN_PASSWORD" || true
superset init
exec gunicorn --bind 0.0.0.0:8088 --workers 2 --timeout 120 "superset.app:create_app()"
