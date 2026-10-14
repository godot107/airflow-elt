#!/usr/bin/env bash
# One-time: the monthly budget alert on tag project=airflow-elt. Kept across demos.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_iam_user
aws cloudformation deploy --stack-name "$COST_STACK" --template-file "$ROOT/infra/cost.yaml" \
  --no-fail-on-empty-changeset --tags "${TAGS[@]}"
echo "Budget stack $COST_STACK ready."
