"""Enrich company size từ job detail / company detail cho 3 nguồn.

Recon đã xác minh:
- itviec: job detail https://itviec.com/it-jobs/<slug>-<id> chứa 'Company size' block (1000+ employees, 501-1000...)
         company page https://itviec.com/companies/<slug> cũng chứa. Dùng job detail cho gọn (đã có URL trong DB).
- topdev: company detail https://topdev.vn/companies/<slug>-<id> chứa RSC JSON company_size + num_employees (500-999). Search payload không có.
- topcv: company page https://www.topcv.vn/cong-ty/<slug>/<id>.html chứa 'Quy mô'.
  Fetch qua curl_cffi impersonate TLS (dùng chung topcv.fetch_html — probe 23/09
  verify pass từ local lẫn Windmill worker; Chrome bị bỏ vì treo trong worker).

Buckets chuẩn: <50 | 50-100 | 101-150 | 151-300 | 301-1000 | 1000+
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from . import config

# ---------- buckets ----------
BUCKETS = [
    ("<50", 0, 49),
    ("50-100", 50, 100),
    ("101-150", 101, 150),
    ("151-300", 151, 300),
    ("301-1000", 301, 999),   # 301-999
    ("1000+", 1000, None),    # 1000+ (inclusive)
]
BUCKET_LABELS = [b[0] for b in BUCKETS]

def bucket_for(min_v: int | None, max_v: int | None) -> str:
    if min_v is None and max_v is None:
        return "unknown"
    # ưu tiên max, nếu 1000+ thì min >=1001
    v = max_v if max_v is not None else min_v
    if v is None:
        return "unknown"
    for label, lo, hi in BUCKETS:
        if hi is None:
            if v >= lo:
                return label
        else:
            if lo <= v <= hi:
                return label
    return "unknown"

def parse_size_range(raw: str) -> tuple[int | None, int | None]:
    """'1000+ employees' -> (1000, None); '51-150 employees' -> (51,150); 
    '500-999' -> (500,999); '10.000-19.999' -> (10000, 19999); 'Hơn 1000' -> (1001, None)"""
    t = (raw or "").lower().replace(",", "").strip()
    if not t or t in ("n/a", "-", "unknown"):
        return (None, None)
    # 1. "hơn 1000" / "trên 1000" / ">1000" -> 1000+
    if "hơn" in t or "trên" in t or ">1000" in t:
        return (1001, None)
    # 2. 1000+ / 1000 + (English)
    m = re.search(r"(\d+)\s*\+", t)
    if m:
        return (int(m.group(1)), None)
    # 3. range with dots as thousand separators: 10.000-19.999
    # Remove dots used as thousand separators, then parse
    t_no_dots = t.replace(".", "")
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)", t_no_dots)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    # 4. range without dots: 51-150, 500-999
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)", t)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    # 5. single number like "25" (hiếm)
    m = re.search(r"(\d+)", t)
    if m:
        v = int(m.group(1))
        return (v, v)
    return (None, None)

# ---------- itviec ----------
_IT_S = curl_requests.Session(impersonate="chrome120")

def fetch_itviec_size(job_url: str) -> str | None:
    try:
        r = _IT_S.get(job_url, timeout=30, headers={"Accept-Language": "vi,en;q=0.8"})
        r.raise_for_status()
        html = r.text
        soup = BeautifulSoup(html, "html.parser")
        # job detail: <div class='col text-dark-grey'> Company size </div><div class='col text-end text-it-black'> 1000+ employees </div>
        for node in soup.select("div"):
            if "Company size" in node.get_text():
                sib = node.find_next_sibling("div")
                if sib:
                    raw = re.sub(r"\s+", " ", sib.get_text(" ", strip=True))
                    if raw and "employee" in raw.lower():
                        return raw
                # fallback: parent row
                parent = node.parent
                if parent:
                    txt = parent.get_text(" ", strip=True)
                    m = re.search(r"Company size\s*([0-9\-\+ ]+employees)", txt, re.I)
                    if m:
                        return m.group(1).strip()
        # also try generic search
        m = re.search(r"Company size[^<]*</div>\s*<div[^>]*>([^<]+employees)", html, re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1).strip())
    except Exception as e:
        print(f"[itviec] fetch fail {job_url}: {e}")
    return None

# ---------- topdev ----------
_TD_S = curl_requests.Session(impersonate="chrome120")

def fetch_topdev_size(company_url: str | None, job_url: str | None = None) -> tuple[str | None, str | None]:
    """Trả về (company_size_raw, num_employees). Thử company_url trước, fallback job_url."""
    candidates = [u for u in [company_url, job_url] if u]
    for url in candidates:
        try:
            # topdev company detail là SSR, fetch HTML
            if "topdev.vn/companies" in url:
                r = _TD_S.get(url, timeout=30, headers={"Accept-Language": "vi,en;q=0.8"})
            else:
                r = _TD_S.get(url, timeout=30, headers={"Accept-Language": "vi,en;q=0.8"})
            if r.status_code != 200:
                continue
            html = r.text
            # RSC JSON: "company":{"... "company_size":"500-999","num_employees":"4283"
            m = re.search(r'"company_size"\s*:\s*"([^"]+)"', html)
            n = re.search(r'"num_employees"\s*:\s*"([^"]+)"', html)
            if m:
                return (m.group(1).strip(), n.group(1).strip() if n else None)
            # fallback DOM: <span>Size:</span><span>500-999</span> — validate ngắn & chứa số
            soup = BeautifulSoup(html, "html.parser")
            for node in soup.find_all(string=re.compile(r"Size", re.I)):
                sib = node.parent.find_next_sibling()
                if sib:
                    raw = re.sub(r"\s+", " ", sib.get_text(" ", strip=True)).strip()
                    if re.search(r"\d", raw) and len(raw) < 40 and re.search(r"(\d.*Employees|\d.*nhân viên|\d+-\d+|\d+\+)", raw, re.I):
                        return (raw, None)
        except Exception as e:
            print(f"[topdev] fetch fail {url}: {e}")
            continue
    return (None, None)

# ---------- topcv (curl_cffi) ----------
def fetch_topcv_size(company_url: str) -> str | None:
    """Fetch company page qua curl_cffi (dùng chung topcv.fetch_html), parse 'Quy mô'.

    Trả None khi fetch lỗi hoặc trang không có field 'Qu mô' — caller chỉ log,
    không raise (enrich chạy theo batch trên nhiều công ty).
    """
    try:
        from .topcv import fetch_html

        html = fetch_html(company_url)
    except Exception as e:
        print(f"[topcv] fetch fail {company_url}: {e}")
        return None
    soup = BeautifulSoup(html, "html.parser")
    # tìm dòng chứa Quy mô
    for node in soup.find_all(string=re.compile(r"Quy mô", re.I)):
        parent = node.parent
        # thường là <span>Quy mô:</span><span>100-200 nhân viên</span> hoặc <div>
        sib = parent.find_next_sibling()
        if sib:
            raw = sib.get_text(" ", strip=True)
            if raw and re.search(r"\d", raw):
                return raw
        # fallback: parent container text
        txt = parent.parent.get_text(" ", strip=True) if parent.parent else ""
        m = re.search(r"Quy mô[^:]*:\s*([0-9\-\+ ]+nhân viên[^\n<]*)", txt, re.I)
        if m:
            return m.group(1).strip()
    # generic regex
    m = re.search(r"Quy mô[^<]*</[^>]+>\s*[^<]*([0-9\-\+\s]+nhân viên)", html, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1).strip())
    return None

# ---------- store helpers ----------
def ensure_company_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS companies (
        source TEXT NOT NULL,
        company TEXT NOT NULL,
        company_slug TEXT,
        detail_url TEXT,
        size_raw TEXT,
        size_min INTEGER,
        size_max INTEGER,
        num_employees TEXT,
        bucket TEXT,
        fetched_at TEXT,
        PRIMARY KEY (source, company)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_bucket ON companies(bucket)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_source ON companies(source)")

def upsert_company(conn, source: str, company: str, detail_url: str | None, size_raw: str | None, size_min, size_max, num_employees=None, company_slug=None):
    # special: raw chứa "+" hoặc "hơn" => 1000+
    if size_raw and ("+" in size_raw or "hơn" in size_raw.lower()):
        bucket = "1000+"
    else:
        bucket = bucket_for(size_min, size_max)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("""INSERT INTO companies(source, company, company_slug, detail_url, size_raw, size_min, size_max, num_employees, bucket, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source, company) DO UPDATE SET
                      company_slug=excluded.company_slug, detail_url=excluded.detail_url,
                      size_raw=excluded.size_raw, size_min=excluded.size_min, size_max=excluded.size_max,
                      num_employees=excluded.num_employees, bucket=excluded.bucket, fetched_at=excluded.fetched_at
                 """, (source, company, company_slug, detail_url, size_raw, size_min, size_max, num_employees, bucket, now))
