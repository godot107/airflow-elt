#!/usr/bin/env bash
# Create the demo stack and wait until Airflow is healthy (~10 min: Docker install + image build).
#
#   deploy/up.sh                                   # defaults: main, backfill 2024-01..03, 4 hours
#   MAX_HOURS=2 FROM= deploy/up.sh                 # 2 hours, no backfill
#   GIT_REF=v1 FROM=2024-01-01 TO=2024-06-30 deploy/up.sh
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_iam_user
aws cloudformation describe-stacks --stack-name "$COST_STACK" >/dev/null 2>&1 || {
  echo "Run deploy/deploy_cost.sh first (budget alert)." >&2; exit 1; }

params=("GitRef=${GIT_REF:-main}" "MaxHours=${MAX_HOURS:-4}")
[ -n "${FROM+x}" ] && params+=("BackfillFrom=$FROM")
[ -n "${TO:-}" ] && params+=("BackfillTo=$TO")
[ -n "${INSTANCE_TYPE:-}" ] && params+=("InstanceType=$INSTANCE_TYPE")

if aws cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1; then
  echo "Stack $STACK already exists. New settings would not re-run the boot script:" >&2
  echo "deploy/down.sh first (or deploy/extend.sh to change only the timer)." >&2; exit 1
fi
echo "==> Stack $STACK in $AWS_REGION (${params[*]})"
aws cloudformation deploy --stack-name "$STACK" --template-file "$ROOT/infra/demo.yaml" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset --tags "${TAGS[@]}" \
  --parameter-overrides "${params[@]}"
INSTANCE=$(out InstanceId)

echo "==> Waiting for SSM"
state=""
for _ in $(seq 60); do
  state=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$INSTANCE" \
    --query "InstanceInformationList[0].PingStatus" --output text 2>/dev/null || true)
  [ "$state" = "Online" ] && break
  sleep 10
done
[ "$state" = "Online" ] || { echo "instance never came online in SSM" >&2; exit 1; }

echo "==> Waiting for Airflow (Docker install + image build; tail with: deploy/logs.sh)"
for _ in $(seq 90); do
  on_instance "$INSTANCE" "test -f /var/lib/airflow-elt-ready" >/dev/null 2>&1 && break
  sleep 10
done
on_instance "$INSTANCE" "test -f /var/lib/airflow-elt-ready" >/dev/null || {
  echo "Airflow not ready after 15 min; see deploy/logs.sh" >&2; exit 1; }

PASSWORD=$(on_instance "$INSTANCE" "grep ^AIRFLOW_ADMIN_PASSWORD= /opt/airflow-elt/.env | cut -d= -f2")
WH_PASSWORD=$(on_instance "$INSTANCE" "grep ^WAREHOUSE_PASSWORD= /opt/airflow-elt/.env | cut -d= -f2")
EXPIRES=$(on_instance "$INSTANCE" "cat /var/lib/demo-expires-at")
cat <<MSG

Airflow is up. The backfill keeps running for a few more minutes (deploy/smoke.sh checks it).
  1. deploy/tunnel.sh             # Airflow on http://localhost:8080, warehouse on localhost:5433
  2. login: admin / $PASSWORD
  3. notebook against the cloud stack:
       export AIRFLOW_PASSWORD='$PASSWORD' WAREHOUSE_PASSWORD='$WH_PASSWORD'
       jupyter lab notebooks/demo.ipynb
  Self-terminates at $EXPIRES (deploy/extend.sh HOURS to push it back).
  When done: deploy/down.sh
MSG
