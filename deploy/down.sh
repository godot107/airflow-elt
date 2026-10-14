#!/usr/bin/env bash
# Delete the demo stack: instance, disk, security group, role. The budget stack is kept.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
require_iam_user
echo "==> Deleting stack $STACK"
aws cloudformation delete-stack --stack-name "$STACK"
aws cloudformation wait stack-delete-complete --stack-name "$STACK"
echo "Done. Nothing billable remains (the budget stack is free)."
