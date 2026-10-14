#!/usr/bin/env bash
# Push back the demo's self-termination: deploy/extend.sh 2   -> shut down 2 hours from now.
set -euo pipefail
source "$(dirname "$0")/_common.sh"
HOURS=${1:?usage: deploy/extend.sh HOURS}
[[ "$HOURS" =~ ^[0-9]+$ ]] && [ "$HOURS" -ge 1 ] && [ "$HOURS" -le 24 ] || { echo "HOURS must be 1-24" >&2; exit 1; }
on_instance "$(out InstanceId)" \
  "shutdown -c; shutdown -h +$((HOURS * 60)) extended; date -u -d +${HOURS}hours +%FT%TZ | tee /var/lib/demo-expires-at"
