#!/usr/bin/env bash
# Last lines of the instance bootstrap log (Docker install, image build, backfill trigger).
set -euo pipefail
source "$(dirname "$0")/_common.sh"
on_instance "$(out InstanceId)" "tail -n ${LINES:-25} /var/log/bootstrap.log"
