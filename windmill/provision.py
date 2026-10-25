#!/usr/bin/env python3
"""Bootstrap Windmill riêng của job-crawler — idempotent, chạy lại thoải mái.

Sau `docker compose up -d`: đợi server → login admin mặc định → tạo workspace
"jobcrawler" → 5 script pipeline → 4 schedule. Đã có thì bỏ qua (không nhân đôi).

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

SCRIPTS = {
    "crawl_all": ("Crawl 3 nguồn itviec+topcv+topdev → SQLite",
                  ".venv/bin/job-crawler all 2>&1"),
    "sync_supabase": ("Sync SQLite → Supabase (production Vercel)",
                      "timeout 280 .venv/bin/python scripts/sync_supabase.py 2>&1"),
    "companies": ("Làm giàu danh bạ công ty",
                  ".venv/bin/job-crawler companies 2>&1"),
    "deep": ("Quét sâu + kiểm tra job còn mở",
             ".venv/bin/job-crawler deep 2>&1"),
    "check": ("Kiểm tra sức khoẻ cả chuỗi (windmill→cloud)",
              "bash scripts/local/check.sh 2>&1"),
}
SCHEDULES = [
    ("crawl_15min", "crawl_all", "0 */15 * * * *"),
    ("sync_15min", "sync_supabase", "0 10-59/15 * * * *"),
    ("companies_hour", "companies", "0 20 * * * *"),
    ("deep_daily", "deep", "0 37 4 * * *"),
]


def api(method: str, path: str, token: str = "", body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw[:1] in ("[", "{") else raw)
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
    bash = ("#!/bin/bash\ncd {repo}\nset -a; source .env; set +a\n{cmd}\n"
            "exit_code=$?\necho '---- done ----'\nexit $exit_code")
    for name, (summary, cmd) in SCRIPTS.items():
        path = f"u/jobcrawler/{name}"
        code, body = api("GET", f"/api/w/jobcrawler/scripts/exists/p/{path}", token)
        # API trả 200 kèm true/false — phải soi body, không nhìn status
        if code == 200 and body is True:
            print(f"script {name}: đã có")
            continue
        body = {"path": path, "parent_hash": None, "summary": summary, "kind": "script",
                "language": "bash", "is_template": False,
                "content": bash.format(repo=REPO, cmd=cmd)}
        code, err = api("POST", "/api/w/jobcrawler/scripts/create", token, body)
        print(f"script {name}: HTTP {code}" + (f" {err}" if code >= 400 else ""))


def ensure_schedules(token: str) -> None:
    code, existing = api("GET", "/api/w/jobcrawler/schedules/list", token)
    have = {s["path"] for s in (existing or [])} if isinstance(existing, list) else set()
    for name, script, cron in SCHEDULES:
        path = f"u/jobcrawler/{name}"
        if path in have:
            print(f"schedule {name}: đã có")
            continue
        body = {"path": path, "schedule": cron, "timezone": "Asia/Ho_Chi_Minh",
                "script_path": f"u/jobcrawler/{script}", "is_flow": False,
                "args": {}, "enabled": True, "no_flow_overlap": True}
        code, err = api("POST", "/api/w/jobcrawler/schedules/create", token, body)
        print(f"schedule {name} ({cron}): HTTP {code}" + (f" {err}" if code >= 400 else ""))


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
