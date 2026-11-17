#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
# Bật Telegram khi đã có token/chat id; có thể override bằng env.
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  export JC_TELEGRAM_ENABLED="${JC_TELEGRAM_ENABLED:-1}"
else
  export JC_TELEGRAM_ENABLED="${JC_TELEGRAM_ENABLED:-0}"
fi
# Lượt 15 phút = QUICK crawl: job mới luôn xuất hiện đầu listing (sort theo
# ngày đăng), 2 trang/nguồn là dư; deep hằng ngày quét đủ JC_DEEP_PAGES_*.
export JC_MAX_PAGES_ITVIEC="${JC_QUICK_PAGES_ITVIEC:-2}"
export JC_MAX_PAGES_TOPCV="${JC_QUICK_PAGES_TOPCV:-2}"
export JC_MAX_PAGES_TOPDEV="${JC_QUICK_PAGES_TOPDEV:-2}"
# Quick chỉ kiểm tra chi tiết vài job; deep mới dùng ngân sách lớn.
export JC_JOB_DETAIL_BUDGET="${JC_QUICK_DETAIL_BUDGET:-15}"
exec "$REPO_DIR/.venv/bin/python" -m job_crawler all
