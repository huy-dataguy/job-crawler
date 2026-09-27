#requirements:
#curl_cffi>=0.15
#beautifulsoup4>=4.12

"""summary: "Crawl cả 3 nguồn itviec + topcv + topdev → SQLite (script cho schedule)"
description: |
  Được schedule chạy lúc 09:00 / 11:00 / 14:00 / 16:00 / 21:00 (Asia/Ho_Chi_Minh).
  Idempotent: chạy lại chỉ cập nhật last_seen, không pha dữ liệu.
"""
import os
import sys
import json
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, "/workspace/src")
# Windmill job sandboxes do not automatically inherit all worker environment
# variables.  Set the mounted, writable database location before importing the
# project config (which reads its env values at import time).
os.environ.setdefault("JC_DATA_DIR", "/data")

def _secret(path: str) -> str:
    """Read an encrypted Variable through this job's short-lived WM_TOKEN."""
    base = os.environ.get("BASE_INTERNAL_URL") or os.environ["WM_BASE_URL"]
    url = f"{base}/api/w/{os.environ['WM_WORKSPACE']}/variables/get_value/{quote(path, safe='/')}"
    request = Request(url, headers={"Authorization": f"Bearer {os.environ['WM_TOKEN']}"})
    with urlopen(request, timeout=15) as response:
        value = json.loads(response.read().decode("utf-8"))
    return value["value"] if isinstance(value, dict) else value


# Worker process variables are deliberately isolated from job sandboxes. Fetch
# Telegram credentials from encrypted Windmill Variables before importing config.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", _secret("u/jobcrawler/telegram_bot_token"))
os.environ.setdefault("TELEGRAM_CHAT_ID", _secret("u/jobcrawler/telegram_chat_id"))

from job_crawler.pipeline import run_source  # noqa: E402

import time  # noqa: E402


def main():
    results = []
    # Run the two HTTP/API sources first. TopCV's browser fallback may take
    # minutes under a Cloudflare challenge and must not delay new-job alerts
    # from ITviec or TopDev.
    for source in ("itviec", "topdev", "topcv"):
        try:
            results.append(run_source(source))
        except Exception as e:
            results.append({"source": source, "error": repr(e)[:200]})
        time.sleep(5)

    ok = [r for r in results if "error" not in r]
    return {"ok": len(ok), "results": results}
