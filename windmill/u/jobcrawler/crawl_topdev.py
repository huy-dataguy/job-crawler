#requirements:
#curl_cffi>=0.15
#beautifulsoup4>=4.12

"""summary: "Crawl TopDev HCM (region 79, 4 trang đầu) → SQLite qua API + HTTP"
description: |
  TopDev có API sạch api.topdev.vn nhưng list metadata nằm ở HTML server-render
  → fetch HTTP thuần, parse card. Repo mounted /workspace (ro), SQLite /data.
"""
import os
import sys
import json
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, "/workspace/src")
os.environ.setdefault("JC_DATA_DIR", "/data")

def _secret(path: str) -> str:
    base = os.environ.get("BASE_INTERNAL_URL") or os.environ["WM_BASE_URL"]
    url = f"{base}/api/w/{os.environ['WM_WORKSPACE']}/variables/get_value/{quote(path, safe='/')}"
    request = Request(url, headers={"Authorization": f"Bearer {os.environ['WM_TOKEN']}"})
    with urlopen(request, timeout=15) as response:
        value = json.loads(response.read().decode("utf-8"))
    return value["value"] if isinstance(value, dict) else value


os.environ.setdefault("TELEGRAM_BOT_TOKEN", _secret("u/jobcrawler/telegram_bot_token"))
os.environ.setdefault("TELEGRAM_CHAT_ID", _secret("u/jobcrawler/telegram_chat_id"))

from job_crawler.pipeline import run_source  # noqa: E402


def main():
    return run_source("topdev")
