#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
# No outbound notifications during this rollout. Explicit opt-in remains in CLI.
export JC_TELEGRAM_ENABLED=0
exec "$REPO_DIR/.venv/bin/python" -m job_crawler all
