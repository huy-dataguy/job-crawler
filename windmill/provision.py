#!/usr/bin/env python3
"""Bootstrap Windmill riêng của job-crawler — idempotent, chạy lại thoải mái.

Sau `docker compose up -d`: đợi server → login admin mặc định → tạo workspace
"jobcrawler" → pipeline riêng từng sàn + deep + companies + health + sync.
Schedule đã có thì cập nhật cron; schedule legacy thì tắt.

Chạy: .venv/bin/python windmill/provision.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("WM_URL", "http://localhost:8132")
ADMIN = {"email": "admin@windmill.dev", "password": "changeme"}
WORKSPACE = {"id": "jobcrawler", "name": "Job Crawler"}
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

QUICK = ('JC_MAX_PAGES_ITVIEC="${JC_QUICK_PAGES_ITVIEC:-2}" '
         'JC_MAX_PAGES_TOPCV="${JC_QUICK_PAGES_TOPCV:-2}" '
         'JC_MAX_PAGES_TOPDEV="${JC_QUICK_PAGES_TOPDEV:-2}" '
         'JC_JOB_DETAIL_BUDGET="${JC_QUICK_DETAIL_BUDGET:-15}"')
DEEP = ('JC_JOB_DETAIL_BUDGET="${JC_DEEP_DETAIL_BUDGET:-100}" '
        'JC_COMMIT_BATCH="${JC_COMMIT_BATCH:-50}"')

SCRIPTS = {
    # Mỗi sàn là một pipeline riêng để xem/thử/retry độc lập trên Windmill.
    "crawl_itviec": ("Pipeline ITviec: listing mới nhất → SQLite + Telegram",
                     f'{QUICK} .venv/bin/job-crawler itviec 2>&1'),
    "crawl_topcv": ("Pipeline TopCV: listing mới nhất → SQLite + Telegram",
                    f'{QUICK} .venv/bin/job-crawler topcv 2>&1'),
    "crawl_topdev": ("Pipeline TopDev: JSON API newest → SQLite + Telegram",
                     f'{QUICK} .venv/bin/job-crawler topdev 2>&1'),
    "deep_itviec": ("Deep ITviec: 50 trang + kiểm tra job còn mở",
                    f'{DEEP} JC_MAX_PAGES_ITVIEC="${{JC_DEEP_PAGES_ITVIEC:-50}}" '
                    ".venv/bin/job-crawler itviec 2>&1"),
    "deep_topcv": ("Deep TopCV: 20 trang + kiểm tra job còn mở",
                   f'{DEEP} JC_MAX_PAGES_TOPCV="${{JC_DEEP_PAGES_TOPCV:-20}}" '
                   ".venv/bin/job-crawler topcv 2>&1"),
    "deep_topdev": ("Deep TopDev: đọc tới meta.last_page (full coverage)",
                    f'{DEEP} JC_MAX_PAGES_TOPDEV="${{JC_DEEP_PAGES_TOPDEV:-0}}" '
                    ".venv/bin/job-crawler topdev 2>&1"),
    "crawl_all": ("(tuỳ chọn) Crawl tuần tự 3 nguồn — dùng để test tay",
                  ".venv/bin/job-crawler all 2>&1"),
    "sync_supabase": ("Sync SQLite → Supabase (production Vercel)",
                      "timeout 280 .venv/bin/python scripts/sync_supabase.py 2>&1"),
    "companies": ("Làm giàu danh bạ công ty",
                  ".venv/bin/job-crawler companies 2>&1"),
    "health": ("Watchdog: pipeline chết/treo/lỗi → Telegram",
               ".venv/bin/job-crawler health 2>&1"),
    "check": ("Kiểm tra sức khoẻ cả chuỗi (windmill→cloud)",
              "bash scripts/local/check.sh 2>&1"),
    "telegram_test": ("Gửi thử một tin nhắn Telegram",
                      ".venv/bin/job-crawler telegram-test 2>&1"),
}
SCHEDULES = [
    # 4 lượt/ngày (giờ VN), lệch phút để không tranh lock/DB cùng lúc.
    # TopDev chạy trước vì API rẻ và trả job mới nhanh nhất.
    ("crawl_topdev", "crawl_topdev", "0 0 9,12,14,16 * * *"),
    ("crawl_itviec", "crawl_itviec", "0 2 9,12,14,16 * * *"),
    ("crawl_topcv", "crawl_topcv", "0 4 9,12,14,16 * * *"),
    # Deep 1 lần/ngày, sau giờ cao điểm tối.
    ("deep_itviec", "deep_itviec", "0 0 5 * * *"),
    ("deep_topcv", "deep_topcv", "0 10 5 * * *"),
    ("deep_topdev", "deep_topdev", "0 20 5 * * *"),
    # Danh bạ 2 lần/ngày; sync mỗi giờ sau lượt crawl; health mỗi giờ.
    ("companies_am", "companies", "0 25 6 * * *"),
    ("companies_pm", "companies", "0 25 18 * * *"),
    ("sync_hour", "sync_supabase", "0 20 * * * *"),
    ("health_hour", "health", "0 45 * * * *"),
]
# Schedule cũ (crawl_all 15') không còn dùng — tắt nếu workspace đã có.
OBSOLETE_SCHEDULES = ["crawl_15min", "deep_daily", "companies_hour", "sync_15min", "health_10min"]


def api(method: str, path: str, token: str = "", body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def wait_server() -> str:
    """Đợi server + login; trả token. Login chỉ thành công sau khi bootstrap xong."""
    last = ""
    for _ in range(40):
        try:
            code, body = api("POST", "/api/auth/login", body=ADMIN)
        except (urllib.error.URLError, ConnectionResetError, OSError) as e:
            last = str(e)[:80]  # server đang migrate DB — thử lại
            time.sleep(4)
            continue
        if code == 200:
            return str(body).strip().strip('"')
        last = f"HTTP {code}"
        time.sleep(4)
    raise SystemExit(f"Windmill không login được sau ~3 phút ({last}) — xem docker logs jobcrawler-windmill-server-1")


def ensure_workspace(token: str) -> None:
    code, _ = api("GET", "/api/workspaces/list", token)
    ws = _ if isinstance(_, list) else []
    if any(w.get("id") == WORKSPACE["id"] for w in ws):
        print(f"workspace '{WORKSPACE['id']}' đã có")
        return
    code, body = api("POST", "/api/workspaces/create", token, WORKSPACE)
    print(f"workspace '{WORKSPACE['id']}': HTTP {code}")


def ensure_scripts(token: str) -> None:
    bash = ("#!/bin/bash\ncd {repo}\nset -a; source .env; set +a\n"
            "# Windmill là scheduler chính: luôn bật Telegram khi đã có secrets.\n"
            "if [ -n \"${{TELEGRAM_BOT_TOKEN:-}}\" ] && [ -n \"${{TELEGRAM_CHAT_ID:-}}\" ]; then\n"
            "  export JC_TELEGRAM_ENABLED=1\nfi\n"
            "{cmd}\n"
            "exit_code=$?\necho '---- done ----'\nexit $exit_code")
    for name, (summary, cmd) in SCRIPTS.items():
        path = f"u/jobcrawler/{name}"
        content = bash.format(repo=REPO, cmd=cmd)
        body = {"path": path, "summary": summary, "kind": "script",
                "language": "bash", "is_template": False,
                "content": content}
        code, exists = api("GET", f"/api/w/jobcrawler/scripts/exists/p/{path}", token)
        # API trả 200 kèm true/false — phải soi body, không nhìn status
        if code == 200 and exists is True:
            _, cur = api("GET", f"/api/w/jobcrawler/scripts/get/p/{path}", token)
            if isinstance(cur, dict):
                if cur.get("content") == content:
                    print(f"script {name}: đã có (mới nhất)")
                    continue
                body["parent_hash"] = cur.get("hash")
                body["auto_parent"] = True
            code_u, err = api("POST", f"/api/w/jobcrawler/scripts/update/{path}", token, body)
            print(f"script {name}: cập nhật (HTTP {code_u})" + (f" {err}" if code_u >= 400 else ""))
            continue
        body["parent_hash"] = None
        code, err = api("POST", "/api/w/jobcrawler/scripts/create", token, body)
        print(f"script {name}: HTTP {code}" + (f" {err}" if code >= 400 else ""))


def ensure_schedules(token: str) -> None:
    code, existing = api("GET", "/api/w/jobcrawler/schedules/list", token)
    have = {s["path"] for s in (existing or [])} if isinstance(existing, list) else set()
    for name, script, cron in SCHEDULES:
        path = f"u/jobcrawler/{name}"
        body = {"path": path, "schedule": cron, "timezone": "Asia/Ho_Chi_Minh",
                "script_path": f"u/jobcrawler/{script}", "is_flow": False,
                "args": {}, "enabled": True, "no_flow_overlap": True}
        if path in have:
            # Cập nhật cron/script để workspace cũ nhận cấu hình mới.
            code_u, err = api("POST", f"/api/w/jobcrawler/schedules/update/{path}", token, body)
            print(f"schedule {name} ({cron}): cập nhật (HTTP {code_u})"
                  + (f" {err}" if code_u >= 400 else ""))
            continue
        code, err = api("POST", "/api/w/jobcrawler/schedules/create", token, body)
        print(f"schedule {name} ({cron}): HTTP {code}" + (f" {err}" if code >= 400 else ""))
    for name in OBSOLETE_SCHEDULES:
        path = f"u/jobcrawler/{name}"
        if path not in have:
            continue
        # schedules/update bỏ qua `enabled`; phải dùng setenabled riêng.
        code, err = api("POST", f"/api/w/jobcrawler/schedules/setenabled/{path}", token,
                        {"enabled": False})
        print(f"schedule {name}: tắt (legacy, HTTP {code})"
              + (f" {err}" if code >= 400 else ""))


def main() -> None:
    print("== Windmill job-crawler provision ==")
    token = wait_server()
    print("login OK")
    ensure_workspace(token)
    ensure_scripts(token)
    ensure_schedules(token)
    print("== xong — UI:", BASE, "(admin@windmill.dev / changeme, workspace Job Crawler) ==")


if __name__ == "__main__":
    main()
