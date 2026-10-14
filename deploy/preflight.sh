#!/usr/bin/env bash
# Run before deploy/up.sh: catches everything that would otherwise fail ten minutes into a deploy.
# Read-only; changes nothing in AWS or the repo.
set -uo pipefail
source "$(dirname "$0")/_common.sh"
fail=0
ok()   { echo "  ok    $*"; }
bad()  { echo "  FAIL  $*"; fail=1; }
warn() { echo "  warn  $*"; }

echo "==> Local tools"
command -v aws >/dev/null && ok "aws cli $(aws --version 2>&1 | cut -d' ' -f1)" || bad "aws cli missing"
command -v session-manager-plugin >/dev/null && ok "session-manager-plugin $(session-manager-plugin --version)" \
  || bad "session-manager-plugin missing (deploy/README.md shows a no-sudo install)"
command -v python3 >/dev/null && ok "python3" || bad "python3 missing (deploy scripts use it for JSON)"

echo "==> AWS session"
session=0
if arn=$(aws sts get-caller-identity --query Arn --output text 2>/dev/null); then
  case "$arn" in *:root) bad "signed in as root: 'aws login' as WillieMaize" ;; *) ok "$arn"; session=1 ;; esac
else
  bad "no AWS session: run 'aws login'"
fi
ok "region $AWS_REGION"

if [ $session = 1 ]; then
  echo "==> Account"
  aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text 2>/dev/null \
    | grep -q '^vpc-' && ok "default VPC present" || bad "no default VPC in $AWS_REGION (the template uses it)"
  aws cloudformation describe-stacks --stack-name "$COST_STACK" >/dev/null 2>&1 \
    && ok "budget stack $COST_STACK" || warn "budget stack missing: run deploy/deploy_cost.sh (up.sh requires it)"
  if aws cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1; then
    bad "stack $STACK already exists: deploy/down.sh first"
  else
    ok "no leftover $STACK stack"
  fi
  types=$(aws ec2 describe-instance-type-offerings --location-type region \
    --filters Name=instance-type,Values="${INSTANCE_TYPE:-t4g.large}" --query 'InstanceTypeOfferings[].InstanceType' --output text)
  [ -n "$types" ] && ok "${INSTANCE_TYPE:-t4g.large} offered in $AWS_REGION" || bad "${INSTANCE_TYPE:-t4g.large} not offered in $AWS_REGION"
  aws cloudformation validate-template --template-body "file://$ROOT/infra/demo.yaml" >/dev/null \
    && ok "infra/demo.yaml validates" || bad "infra/demo.yaml does not validate"
fi

echo "==> Code the instance will run (it clones GitHub, not this working tree)"
ref=${GIT_REF:-main}
git -C "$ROOT" fetch -q origin 2>/dev/null || warn "could not fetch origin"
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  warn "uncommitted changes here will NOT be deployed"
fi
if git -C "$ROOT" rev-parse -q --verify "origin/$ref" >/dev/null; then
  ahead=$(git -C "$ROOT" rev-list --count "origin/$ref..HEAD" 2>/dev/null || echo 0)
  [ "$ahead" = 0 ] && ok "origin/$ref is up to date with HEAD" || warn "$ahead local commit(s) not pushed to origin/$ref"
else
  bad "origin/$ref not found (GIT_REF=$ref)"
fi

echo
if [ $fail = 0 ]; then echo "Preflight passed: deploy/up.sh"; else echo "Preflight failed: fix the FAIL lines first."; exit 1; fi
