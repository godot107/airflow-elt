#!/usr/bin/env bash
# After up.sh: confirm the cloud stack actually did its job. Exits non-zero if anything is off.
#   bootstrap done · containers healthy · DAGs parsed · backfill runs succeeded · transform ran · marts populated
set -euo pipefail
source "$(dirname "$0")/_common.sh"
INSTANCE=$(out InstanceId)
APP=/opt/airflow-elt
fail=0

# SQL travels as a quoted heredoc, so it needs no escaping on its way through SSM.
in_db() {   # in_db <compose service> <user/db> <sql>
  printf "cd %s && docker compose exec -T %s psql -U %s -tA %s <<'SQL'\n%s\nSQL" "$APP" "$1" "$2" "$2" "$3"
}
check() {   # check <label> <remote command> <regex the output must match>
  local got
  got=$(on_instance "$INSTANCE" "$2" 2>/dev/null || true)
  if grep -Eq "$3" <<<"$got"; then echo "  ok    $1"
  else echo "  FAIL  $1"; sed 's/^/        /' <<<"$got" | head -8; fail=1; fi
}

echo "==> Smoke test on $INSTANCE"
check "bootstrap finished" "test -f /var/lib/airflow-elt-backfill-started && echo done" "^done$"
check "all containers healthy" \
  "cd $APP && docker compose ps --format '{{.Name}} {{.Health}}' | grep -vc ' healthy$' || true" "^0$"
check "three DAGs parsed, none with import errors" \
  "$(in_db postgres airflow "select count(*) from dag where dag_id like 'taxi_%' and not has_import_errors")" "^3$"
check "every backfill run succeeded" \
  "$(in_db postgres airflow "select count(*) filter (where state = 'success') || '/' || count(*) from dag_run where dag_id = 'taxi_ingest' and run_type = 'backfill'")" \
  "^([1-9][0-9]*)/\1$"
check "a transform run succeeded" \
  "$(in_db postgres airflow "select count(*) from dag_run where dag_id = 'taxi_transform' and state = 'success'")" "^[1-9]"
check "marts populated" "$(in_db warehouse warehouse "select count(*) from marts.mart_daily_zone")" "^[1-9]"

if [ "$fail" = 0 ]; then echo "All checks passed."
else echo "Some checks failed (the backfill may still be running: retry in a few minutes)."; exit 1; fi
