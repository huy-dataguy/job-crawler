#!/usr/bin/env bash
# Kiểm tra cả chuỗi job-crawler sau khi mở máy: timers → crawler → sync → cloud.
# Chạy: scripts/local/check.sh   (nên đợi ~2 phút sau khi mở máy cho nhịp bù chạy xong)
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"
now=$(date +%s)
ok=0; bad=0
mark() { if [ "$1" = "ok" ]; then echo "  ✓ $2"; ok=$((ok+1)); else echo "  ✗ $2"; bad=$((bad+1)); fi; }
age_min() { # tuổi (phút) của thời điểm cho trước "YYYY-MM-DD HH:MM:SS"
  local t; t=$(date -d "$1" +%s 2>/dev/null) || echo 99999
  echo $(( (now - t) / 60 ))
}

echo "═══ 1. Windmill (scheduler chính — UI: http://localhost:8132/runs) ═══"
if curl -fsS -m 4 http://localhost:8132/api/version >/dev/null 2>&1 \
   || curl -fsS -m 4 http://server:8000/api/version >/dev/null 2>&1; then
  echo "  ✓ Windmill đang chạy — crawl 9h/12h/14h/16h (topdev :00 · itviec :02 · topcv :04) · health mỗi giờ"
  echo "    (systemd timers đã tắt — Windmill là nơi duy nhất quyết định lịch)"
else
  echo "  ✗ Windmill KHÔNG chạy → scripts/local/windmill.sh up"
fi
echo

echo "═══ 2. Dashboard local (localhost:8130) ═══"
if [ ! -d /run/systemd ]; then
  echo "  (bỏ qua — đang chạy trong container, dashboard là việc của host)"
elif [ "$(systemctl --user is-active job-crawler-dashboard.service)" = "active" ] \
   && curl -fsS -m 5 localhost:8130/api/health >/dev/null 2>&1; then
  mark ok "dashboard đang chạy"
else
  mark bad "dashboard KHÔNG chạy → systemctl --user restart job-crawler-dashboard"
fi

echo "═══ 3. Crawler: lượt chạy cuối TỪNG NGUỒN (từ crawl_runs) ═══"
sec3=$(.venv/bin/python - <<'PYEOF'
import sqlite3, datetime, pathlib
db = pathlib.Path(__file__ if False else ".") / "data" / "job_crawler.db"
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rows = conn.execute("""
  SELECT source, status, finished_at FROM crawl_runs r
  WHERE finished_at IS NOT NULL
    AND id = (SELECT MAX(id) FROM crawl_runs r2
              WHERE r2.source = r.source AND r2.finished_at IS NOT NULL)""").fetchall()
conn.close()
now = datetime.datetime.now(datetime.timezone.utc)
for source, status, ts in rows:
    dt = datetime.datetime.fromisoformat(ts)
    age = int((now - dt).total_seconds() // 60)
    # Crawl 4 lượt/ngày + companies 2 lượt/ngày → cho phép 18 giờ.
    limit = 1080
    if age > limit:
        print(f"BAD|{source}|lượt cuối {age} phút trước — QUÁ CŨ (máy mới mở? đợi nhịp bù)")
    elif status in ("ok", "partial"):
        print(f"OK|{source}|{status}, {age} phút trước")
    else:
        print(f"BAD|{source}|lỗi ({status}) {age} phút trước — lặp lại nhiều nhịp → parser hỏng, xem journalctl --user -u job-crawler-crawl -n 50")
PYEOF
)
echo "$sec3" | sort | while IFS='|' read -r mark src msg; do [ -n "$mark" ] && echo "  $([ "$mark" = OK ] && echo ✓ || echo ✗) $src: $msg"; done
bad=$((bad + $(echo "$sec3" | grep -c '^BAD')))
ok=$((ok + $(echo "$sec3" | grep -c '^OK')))
echo

echo "═══ 4. Sync lên Supabase vừa chạy OK? ═══"
last_sync=$(.venv/bin/python -c "
import json, pathlib
p = pathlib.Path('data/supabase_sync_state.json')
print(json.loads(p.read_text()).get('last_sync', '')) if p.exists() else None" 2>/dev/null)
if [ -n "$last_sync" ]; then
  m=$(age_min "$last_sync")
  if [ "$m" -lt 35 ] 2>/dev/null; then
    mark ok "sync OK cuối: $last_sync (${m} phút trước)"
  else
    mark bad "sync cũ ${m} phút (>35) — chạy tay: source .env && .venv/bin/python scripts/sync_supabase.py"
  fi
else
  mark bad "chưa có state sync — chạy tay: source .env && .venv/bin/python scripts/sync_supabase.py"
fi

echo "═══ 5. Đầu cuối: data trên cloud tươi cỡ nào? ═══"
set -a; source .env 2>/dev/null; set +a
if [ -n "$SUPABASE_DB_URL" ]; then
  result=$(.venv/bin/python - <<'EOF' 2>/dev/null
import psycopg2, os
from datetime import datetime, timezone
conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=10)
cur = conn.cursor()
cur.execute("SELECT max(last_seen_at) FROM jobs")
fresh = cur.fetchone()[0]
mins = int((datetime.now(fresh.tzinfo) - fresh).total_seconds() // 60)
cur.execute("SELECT count(*) FROM jobs")
print(f"{mins}|{cur.fetchone()[0]}")
conn.close()
EOF
)
  mins="${result%%|*}"; njobs="${result##*|}"
  if [ -n "$mins" ] && [ "$mins" -lt 60 ] 2>/dev/null; then
    mark ok "cloud vừa nhận data ${mins} phút trước (${njobs} job)"
  else
    mark bad "data cloud cũ ${mins:-?} phút — sync chưa tới, xem mục 4"
  fi
else
  mark bad "thiếu SUPABASE_DB_URL trong .env"
fi

echo
echo "Tổng: $ok OK, $bad vấn đề."
[ "$bad" = "0" ] || exit 1
