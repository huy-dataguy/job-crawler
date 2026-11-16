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
TOPDEV_API = os.environ.get("JC_TOPDEV_API", "https://api.topdev.vn/td/v2")
# TopDev trả 100 job/request qua JSON API; sâu hơn nữa dùng phân trang `page`.
TOPDEV_PAGE_SIZE = int(os.environ.get("JC_TOPDEV_PAGE_SIZE", "100"))
# `ordering=newest` giúp incremental: gặp id đã biết là dừng, khỏi quét 6000 job.
TOPDEV_ORDERING = os.environ.get("JC_TOPDEV_ORDERING", "newest")
LISTING_URL = os.environ.get("JC_ITVIEC_URL", BASE_URL + "it-jobs")
TOPCV_URL = os.environ.get("JC_TOPCV_URL", "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257")

# Mặc định = QUICK crawl (2 trang/nguồn) cho lượt 15 phút — job mới luôn nằm
# đầu listing. Deep hằng ngày (run_deep.sh) override thành 50/20/40.
MAX_PAGES_ITVIEC = int(os.environ.get("JC_MAX_PAGES_ITVIEC", "2"))
MAX_PAGES_TOPCV = int(os.environ.get("JC_MAX_PAGES_TOPCV", "2"))
# Sau khi sáp nhập Saramin, TopDev là job board đa ngành: chỉ ~9% job là IT,
# nên phải quét nhiều trang hơn (100 job/trang API) rồi lọc `is_it` như cũ.
MAX_PAGES_TOPDEV = int(os.environ.get("JC_MAX_PAGES_TOPDEV", "5"))
# Lượt 15 phút chỉ quét trang đầu (job mới luôn nằm đầu listing, sort theo
# ngày đăng); deep hằng ngày quét đủ MAX_PAGES_* để bắt trượt sâu.
QUICK_PAGES_ITVIEC = int(os.environ.get("JC_QUICK_PAGES_ITVIEC", "2"))
QUICK_PAGES_TOPCV = int(os.environ.get("JC_QUICK_PAGES_TOPCV", "2"))
QUICK_PAGES_TOPDEV = int(os.environ.get("JC_QUICK_PAGES_TOPDEV", "2"))
# Raw = bằng chứng điều tra ngắn hạn: nén gzip + xoá quá TTL sau khi đã vào SQLite.
RAW_RETENTION_HOURS = float(os.environ.get("JC_RAW_RETENTION_HOURS", "48"))
DELAY_BETWEEN_REQUESTS = float(os.environ.get("JC_DELAY", "2.0"))  # giây, lịch sự với nguồn
IMPERSONATE = os.environ.get("JC_IMPERSONATE", "chrome136")
# Giãn cách theo host (giây). TopCV nằm sau Cloudflare nên cần chậm + jitter;
# TopDev đi JSON API nên có thể nhanh hơn nhiều.
SOURCE_DELAYS = {
    "itviec": float(os.environ.get("JC_DELAY_ITVIEC", "1.6")),
    "topcv": float(os.environ.get("JC_DELAY_TOPCV", "2.5")),
    "topdev": float(os.environ.get("JC_DELAY_TOPDEV", "0.4")),
}
SOURCE_DELAY_JITTER = float(os.environ.get("JC_DELAY_JITTER", "0.6"))
# Parser drift: nếu tỉ lệ job có đủ field thiết yếu thấp hơn ngưỡng này → dừng
# và báo lỗi (site đổi schema) thay vì âm thầm ghi dữ liệu rác.
MIN_FILL_RATE = float(os.environ.get("JC_MIN_FILL_RATE", "0.85"))


def source_delay(source: str) -> float:
    """Giãn cách tối thiểu giữa 2 request cùng nguồn (giây)."""
    return SOURCE_DELAYS.get(source, DELAY_BETWEEN_REQUESTS)


CHROME_BIN = os.environ.get("JC_CHROME_BIN", "google-chrome")
CHROME_FLUSH_SECONDS = os.environ.get(
    "JC_CHROME_VIRTUAL_TIME", "15000"
)  # virtual-time-budget cho Cloudflare JS runtime

# Telegram: auto-enable only when both secrets exist.  JC_TELEGRAM_ENABLED can
# explicitly disable delivery for local/debug runs without removing secrets.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
_telegram_override = os.environ.get("JC_TELEGRAM_ENABLED")
TELEGRAM_ENABLED = (
    _telegram_override.strip().lower() in {"1", "true", "yes", "on"}
    if _telegram_override is not None
    else False
)
TELEGRAM_TIMEOUT_SECONDS = float(os.environ.get("JC_TELEGRAM_TIMEOUT", "15"))
TELEGRAM_MIN_INTERVAL_SECONDS = float(os.environ.get("JC_TELEGRAM_MIN_INTERVAL", "1.05"))

# --- DB gọn nhẹ: chỉ giữ data mới nhất, sạch nhất ---------------------------
# Xoá job đăng lâu hơn KEEP_DAYS ngày (theo posted_at, fallback first_seen_at)
KEEP_DAYS = int(os.environ.get("JC_KEEP_DAYS", "30"))
# Xoá job không được thấy lại trên nguồn sau STALE_DAYS ngày (tin đã bị gỡ)
STALE_DAYS = int(os.environ.get("JC_STALE_DAYS", "7"))
# Telegram chỉ push job mới có điểm liên quan (theo CV) từ mức này trở lên;
# đặt 0 để push mọi job mới. Job vẫn được lưu DB bất kể điểm.
NOTIFY_MIN_RELEVANCE = int(os.environ.get("JC_NOTIFY_MIN_RELEVANCE", "40"))

# --- Thư mục công ty (company_directory) ------------------------------------
ITVIEC_COMPANY_PAGES = int(os.environ.get("JC_ITVIEC_COMPANY_PAGES", "120"))
TOPCV_SITEMAP_PAGES = int(os.environ.get("JC_TOPCV_SITEMAP_PAGES", "10"))
COMPANY_ENRICH_BUDGET = int(os.environ.get("JC_COMPANY_ENRICH_BUDGET", "90"))
JOB_DETAIL_BUDGET = int(os.environ.get("JC_JOB_DETAIL_BUDGET", "60"))
OPEN_CHECK_HOURS = int(os.environ.get("JC_OPEN_CHECK_HOURS", "24"))
RECENT_DAYS = int(os.environ.get("JC_RECENT_DAYS", "14"))
