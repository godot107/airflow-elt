#!/usr/bin/env bash
# Forward the demo's Airflow UI/API (localhost:8080) and warehouse (localhost:5433) over SSM, with no open
# ports. The notebook and `make psql`-style tools then work exactly as against the local stack.
# Ctrl-C closes both tunnels.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
command -v session-manager-plugin >/dev/null || {
  echo "Needs the AWS session-manager-plugin; see deploy/README.md" >&2; exit 1; }
INSTANCE=$(out InstanceId)
forward() {
  aws ssm start-session --target "$INSTANCE" --document-name AWS-StartPortForwardingSession \
    --parameters "portNumber=$1,localPortNumber=$2" >/dev/null
}
forward 5433 "${WAREHOUSE_PORT:-5433}" &
WAREHOUSE_PID=$!
trap 'kill $WAREHOUSE_PID 2>/dev/null' EXIT
echo "Airflow   http://localhost:${LOCAL_PORT:-8080}"
echo "Warehouse localhost:${WAREHOUSE_PORT:-5433} (user warehouse)"
echo "Ctrl-C to close."
forward 8080 "${LOCAL_PORT:-8080}"
