#!/usr/bin/env bash
# Cài đặt runner local: systemd user timer (crawl 15 phút/lượt) + dashboard nền.
# Chạy 1 lần từ repo root:  bash scripts/local/install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

if [ ! -f "$REPO_DIR/.env" ]; then
  cat > "$REPO_DIR/.env" <<'EOF'
# Secret Telegram cho alert job mới — KHÔNG commit file này.
# Lấy token từ @BotFather, chat_id từ getUpdates (xem README).
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF
  chmod 600 "$REPO_DIR/.env"
  echo "Đã tạo $REPO_DIR/.env (placeholder) — điền token/chat_id rồi chạy lại."
fi

chmod +x "$REPO_DIR/scripts/local/run_crawler.sh"

for unit in job-crawler-crawl.service job-crawler-crawl.timer job-crawler-dashboard.service; do
  # Unit reference đường dẫn tuyệt đối của repo này → copy (không symlink)
  # để systemd không theo dõi file trong cây git.
  cp "$REPO_DIR/scripts/local/$unit" "$UNIT_DIR/$unit"
done

# Đường dẫn repo nằm trong unit đã copy; nếu đổi chỗ repo thì chạy lại install.
systemctl --user daemon-reload
systemctl --user enable --now job-crawler-crawl.timer
systemctl --user enable --now job-crawler-dashboard.service

echo "OK. Kiểm tra:"
echo "  systemctl --user list-timers job-crawler-crawl.timer"
echo "  curl -s localhost:8130/api/stats"
echo "  journalctl --user -u job-crawler-crawl.service -n 20 --no-pager"
