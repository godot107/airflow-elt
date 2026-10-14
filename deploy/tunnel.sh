#!/usr/bin/env bash
# Forward the demo's Airflow UI to http://localhost:8080 over SSM (no open ports). Ctrl-C to close.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
command -v session-manager-plugin >/dev/null || {
  echo "Needs the AWS session-manager-plugin; see deploy/README.md" >&2; exit 1; }
aws ssm start-session --target "$(out InstanceId)" --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=8080,localPortNumber=${LOCAL_PORT:-8080}"
