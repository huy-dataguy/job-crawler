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
# Lượt 15 phút = QUICK crawl: job mới luôn xuất hiện đầu listing (sort theo
# ngày đăng), 2 trang/nguồn là dư; deep hằng ngày quét đủ JC_DEEP_PAGES_*.
export JC_MAX_PAGES_ITVIEC="${JC_QUICK_PAGES_ITVIEC:-2}"
export JC_MAX_PAGES_TOPCV="${JC_QUICK_PAGES_TOPCV:-2}"
export JC_MAX_PAGES_TOPDEV="${JC_QUICK_PAGES_TOPDEV:-2}"
exec "$REPO_DIR/.venv/bin/python" -m job_crawler all
