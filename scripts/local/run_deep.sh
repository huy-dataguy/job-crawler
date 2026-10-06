#!/usr/bin/env bash
# Chạy hằng ngày (systemd timer): job crawl SÂU (nhiều trang hơn) + harvest
# thư mục công ty + enrich quy mô theo ngân sách.
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

# 1) Deep job crawl: rộng hơn nhịp 15 phút (bắt thêm công ty/job ở trang sâu)
JC_MAX_PAGES_ITVIEC="${JC_DEEP_PAGES_ITVIEC:-10}" \
JC_MAX_PAGES_TOPCV="${JC_DEEP_PAGES_TOPCV:-8}" \
JC_MAX_PAGES_TOPDEV="${JC_DEEP_PAGES_TOPDEV:-20}" \
  "$UV" run job-crawler

# 2) Harvest thư mục công ty + enrich quy mô (ngân sách JC_COMPANY_ENRICH_BUDGET)
"$UV" run job-crawler companies
