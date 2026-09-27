"""Gửi các job gần đây trong DB vào Telegram — tool flush một lần.

Dùng khi có job mới đã vào DB nhưng chưa được báo Telegram (ví dụ lần crawl tay
chạy khi Telegram chưa cấu hình). Creds đọc từ env, KHÔNG lưu vào file:

    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... \
        uv run python scripts/notify_recent.py --source topcv --limit 10

Mặc định: topcv, 10 job mới nhất theo first_seen_at. Mỗi job gửi cách nhau
>= 1.05s (nhịp an toàn của TelegramNotifier).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_crawler.notifier import TelegramError, TelegramNotifier  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Flush recent jobs to Telegram")
    ap.add_argument("--source", default="topcv", choices=["topcv", "itviec", "topdev"])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--db", default=None, help="Đường dẫn SQLite (mặc định data/job_crawler.db)")
    args = ap.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat_id):
        print("Thiếu TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID trong env — không gửi gì.")
        return 2

    db_path = Path(args.db or Path(__file__).resolve().parents[1] / "data" / "job_crawler.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT source, source_id, title, company, city, salary, experience, level,
                  skills, tags, posted_text, url
           FROM jobs WHERE source = ? AND is_active = 1
           ORDER BY first_seen_at DESC LIMIT ?""",
        (args.source, args.limit),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"Không có job {args.source} nào trong DB.")
        return 0

    notifier = TelegramNotifier(token, chat_id)
    sent = failed = 0
    for r in rows:
        job = dict(r)
        try:
            notifier.send_job(job)
            sent += 1
            print(f"[ok] {job['title'][:60]}")
        except TelegramError as e:
            failed += 1
            print(f"[fail] {job['title'][:60]}: {e}")

    print(f"\nXong: gửi {sent}/{len(rows)} job {args.source}" + (f", lỗi {failed}" if failed else ""))
    return 1 if failed and not sent else 0


if __name__ == "__main__":
    raise SystemExit(main())
