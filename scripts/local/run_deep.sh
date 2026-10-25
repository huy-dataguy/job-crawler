#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
export JC_TELEGRAM_ENABLED=0
export JC_MAX_PAGES_ITVIEC="${JC_DEEP_PAGES_ITVIEC:-50}"
export JC_MAX_PAGES_TOPCV="${JC_DEEP_PAGES_TOPCV:-20}"
export JC_MAX_PAGES_TOPDEV="${JC_DEEP_PAGES_TOPDEV:-40}"
export JC_JOB_DETAIL_BUDGET="${JC_DEEP_DETAIL_BUDGET:-100}"
exec "$REPO_DIR/.venv/bin/python" -m job_crawler all
