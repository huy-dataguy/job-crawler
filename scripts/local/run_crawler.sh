#!/usr/bin/env bash
# Chạy 1 lượt crawl đủ 3 nguồn — dùng cho systemd timer/cron.
# Nạp secret Telegram từ .env ở root repo (file này KHÔNG được commit).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

UV="${UV:-$HOME/.local/bin/uv}"
mkdir -p data
exec "$UV" run job-crawler
