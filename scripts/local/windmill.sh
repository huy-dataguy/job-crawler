#!/usr/bin/env bash
# Windmill pipeline dashboard — cách mở mỗi sáng:
#   scripts/local/windmill.sh up    → bật stack, UI tại http://localhost:8132
#   scripts/local/windmill.sh stop  → tắt
#   scripts/local/windmill.sh runs  → xem vài run gần nhất (kèm success/fail)
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE="docker compose -f $REPO/windmill/docker-compose.yml --env-file $REPO/windmill/.env"
case "${1:-up}" in
  up)
    $COMPOSE up -d
    echo "→ chạy provision (đảm bảo workspace/script/schedule đầy đủ)…"
    "$REPO/.venv/bin/python" "$REPO/windmill/provision.py"
    echo "→ UI: http://localhost:8132  (admin@windmill.dev / changeme — workspace Job Crawler)"
    ;;
  stop) $COMPOSE stop ;;
  runs)
    TOK=$(curl -s -X POST http://localhost:8132/api/auth/login -H "Content-Type: application/json" \
      -d '{"email":"admin@windmill.dev","password":"changeme"}' | tr -d '"[:space:]')
    [ -z "$TOK" ] && { echo "Windmill chưa chạy — scripts/local/windmill.sh up"; exit 1; }
    curl -s "http://localhost:8132/api/w/jobcrawler/jobs/completed/list?limit=10" -H "Authorization: Bearer $TOK" \
    | python3 -c "
import json, sys, datetime
for j in json.load(sys.stdin):
    end = (j.get('end_time') or j.get('started_at') or '')[:16]
    mark = '✓' if j.get('success') else '✗ FAIL'
    print(f\"  {mark} {j.get('script_path','?'):32} {end}\")"
    ;;
  *) echo "dùng: $0 {up|stop|runs}";;
esac
