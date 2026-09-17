"""Config cho crawler — nguồn, nhịp crawl, đường dẫn data.

Tất cả qua env để chạy được cả trên host lẫn trong Windmill worker container.
"""
from __future__ import annotations

import os
from pathlib import Path

# /data trong container; mặc định cục bộ ./data bên ngoài
DATA_DIR = Path(os.environ.get("JC_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = Path(os.environ.get("JC_DB_PATH", DATA_DIR / "job_crawler.db"))

BASE_URL = "https://itviec.com/"
LISTING_URL = BASE_URL + "it-jobs/ho-chi-minh-hcm"
TOPCV_URL = (
    "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-tai-ho-chi-minh-l2cr257"
    "?type_keyword=1&disable_auto_detect_type_keyword=1&sba=1&category_family=r257&locations=l2&saturday_status=0"
)

MAX_PAGES_ITVIEC = int(os.environ.get("JC_MAX_PAGES_ITVIEC", "3"))
MAX_PAGES_TOPCV = int(os.environ.get("JC_MAX_PAGES_TOPCV", "3"))
DELAY_BETWEEN_REQUESTS = float(os.environ.get("JC_DELAY", "2.0"))  # giây, lịch sự với nguồn
CHROME_BIN = os.environ.get("JC_CHROME_BIN", "google-chrome")
CHROME_FLUSH_SECONDS = os.environ.get(
    "JC_CHROME_VIRTUAL_TIME", "15000"
)  # virtual-time-budget cho Cloudflare JS runtime
