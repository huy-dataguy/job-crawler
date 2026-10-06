"""Harvest thư mục công ty đầy đủ từ 3 nguồn + enrich quy mô theo ngân sách.

Phạm vi đã recon (06/10):
- topcv: sitemap companies (~247 sub × 200 ≈ 49k công ty) →
  /cong-ty/<slug>/<id>.html — nguồn ĐẦY ĐỦ.
- itviec: /companies?page=N (25 công ty/trang, không có sitemap) → crawl hết
  các trang cho tới khi hết (hard cap JC_ITVIEC_COMPANY_PAGES).
- topdev: sitemap companies trả 500 (hỏng phía server), /companies chỉ render
  trang đầu qua RSC → harvest trang đầu + TÍCH LŨY dần từ job listings
  (mỗi job crawl bổ sung công ty đang tuyển với tên + URL chính xác).

Enrich quy mô: fetch trang detail theo ngân sách mỗi run (ưu tiên công ty
đang tuyển), không dồn một cục hàng chục nghìn request.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from . import config
from .company_enrich import bucket_for, parse_size_range

_S = curl_requests.Session(impersonate="chrome124")

TOPCV_SITEMAP_INDEX = "https://www.topcv.vn/sitemap/companies.xml"
ITVIEC_COMPANIES_URL = "https://itviec.com/companies"
TOPDEV_COMPANIES_URL = "https://topdev.vn/companies"

_SITEMAP_DELAY = 0.4   # sitemap là file tĩnh, giãn cách nhẹ
_DETAIL_DELAY = 1.5    # trang detail công ty — lịch sự với nguồn

_META_TABLE = """
CREATE TABLE IF NOT EXISTS harvest_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS company_directory (
  source        TEXT NOT NULL,
  slug          TEXT NOT NULL,
  company_id    TEXT,
  name          TEXT NOT NULL,
  name_exact    INTEGER NOT NULL DEFAULT 0,  -- 1 = tên bóc từ nguồn (không đè)
  detail_url    TEXT,
  size_raw      TEXT,
  size_min      INTEGER,
  size_max      INTEGER,
  num_employees TEXT,
  bucket        TEXT,
  is_hiring     INTEGER NOT NULL DEFAULT 0,  -- có job trong lần crawl gần nhất
  enriched_at   TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  PRIMARY KEY (source, slug)
);
CREATE INDEX IF NOT EXISTS idx_company_dir_hiring ON company_directory (is_hiring);
CREATE INDEX IF NOT EXISTS idx_company_dir_name ON company_directory (name);
""" + _META_TABLE


def ensure_directory_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _now() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug_to_name(slug: str) -> str:
    """'fpt-software' → 'Fpt Software'; 'cong-ty-cp-kids-plaza' → giữ nguyên
    dạng chữ hoá (topcv slug không dấu — tên thật sẽ có khi enrich)."""
    words = re.sub(r"[-_]+", " ", slug).split()
    return " ".join(w.capitalize() for w in words if w)


def upsert_directory(conn: sqlite3.Connection, *, source: str, slug: str,
                     name: str, detail_url: str | None = None,
                     company_id: str | None = None, name_exact: bool = False,
                     hiring: bool | None = None) -> None:
    """Thêm/cập nhật 1 công ty. Tên chỉ đè khi bản ghi chưa có tên chính xác
    (name_exact=0) — tránh slug không dấu phá tên có dấu đã bóc được."""
    ts = _now()
    cur = conn.execute(
        "SELECT name_exact FROM company_directory WHERE source=? AND slug=?",
        (source, slug)).fetchone()
    if cur is None:
        conn.execute(
            """INSERT INTO company_directory
                 (source, slug, company_id, name, name_exact, detail_url,
                  is_hiring, first_seen_at, last_seen_at)
               VALUES (?,?,?,?,?,?,?, ?, ?)""",
            (source, slug, company_id, name, 1 if name_exact else 0,
             detail_url, 1 if hiring else 0, ts, ts))
        return
    keep_name = cur["name_exact"] == 1 and not name_exact
    conn.execute(
        f"""UPDATE company_directory SET
              name = CASE WHEN ? THEN name ELSE ? END,
              name_exact = MAX(name_exact, ?),
              detail_url = COALESCE(?, detail_url),
              company_id = COALESCE(?, company_id),
              is_hiring = CASE WHEN ? IS NULL THEN is_hiring ELSE ? END,
              last_seen_at = ?
            WHERE source=? AND slug=?""",
        (1 if keep_name else 0, name, 1 if name_exact else 0,
         detail_url, company_id,
         None if hiring is None else 1, 1 if hiring else 0,
         ts, source, slug))


def link_job_company(conn: sqlite3.Connection, *, source: str,
                     company: str, company_url: str | None) -> str | None:
    """Gắn job → công ty trong directory: đặt tên chính xác + is_hiring=1.
    Trả về slug nếu link được (để pipeline reset is_hiring cho công ty hết tin)."""
    if not company or not company_url:
        # Fallback: match theo tên với công ty đã có trong directory
        # (topdev job card không luôn có link công ty) → chỉ đánh dấu đang tuyển
        if company:
            row = conn.execute(
                "SELECT slug FROM company_directory WHERE source=? AND name=?",
                (source, company)).fetchone()
            if row:
                conn.execute(
                    "UPDATE company_directory SET is_hiring=1, last_seen_at=?"
                    " WHERE source=? AND slug=?",
                    (_now(), source, row["slug"]))
                return row["slug"]
        return None
    m = re.search(r"/(?:companies|cong-ty)/([^?#]+?)(?:\.html)?(?:[?#]|$)", company_url)
    if not m:
        return None
    slug = m.group(1)
    # topcv URL dạng <slug>/<id>.html → tách id
    cid = None
    if source == "topcv":
        mm = re.match(r"(.+)/(\d+)$", slug)
        if mm:
            slug, cid = mm.group(1), mm.group(2)
    upsert_directory(conn, source=source, slug=slug, name=company,
                     detail_url=company_url, company_id=cid,
                     name_exact=True, hiring=True)
    return slug


def refresh_hiring_flags(conn: sqlite3.Connection, source: str,
                         seen_slugs: set[str]) -> None:
    """Sau 1 lượt crawl job: công ty nguồn này không còn tin → is_hiring=0."""
    conn.execute(
        "UPDATE company_directory SET is_hiring=0 WHERE source=? AND is_hiring=1",
        (source,))
    if seen_slugs:
        conn.executemany(
            "UPDATE company_directory SET is_hiring=1 WHERE source=? AND slug=?",
            [(source, s) for s in seen_slugs])


# ---------- harvest: topcv (sitemap — đầy đủ) ------------------------------

def _load_done_subs(conn: sqlite3.Connection, key: str) -> set[str]:
    row = conn.execute("SELECT value FROM harvest_meta WHERE key=?", (key,)).fetchone()
    return set(json.loads(row["value"])) if row else set()


def _save_done_subs(conn: sqlite3.Connection, key: str, done: set[str]) -> None:
    conn.execute(
        """INSERT INTO harvest_meta(key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (key, json.dumps(sorted(done))))


def harvest_topcv(conn: sqlite3.Connection, *, max_pages: int | None = None) -> dict:
    """Sitemap topcv có thể đứt giữa chừng (timeout) — sub đã xong được ghi
    vào harvest_meta và bỏ qua ở lượt sau (resume); sub lỗi sẽ retry lần sau."""
    cap = max_pages or config.TOPCV_SITEMAP_PAGES
    r = _S.get(TOPCV_SITEMAP_INDEX, timeout=40,
               headers={"Accept-Language": "vi,en;q=0.8"})
    r.raise_for_status()
    subs = re.findall(r"<loc>([^<]*companies[^<]*)</loc>", r.text)
    done = _load_done_subs(conn, "topcv_subs_done")
    updated = failed = 0
    for i, sub in enumerate(subs[:cap], 1):
        if sub in done:
            continue
        html = None
        for attempt in (1, 2):  # timeout/throttle → thử lại 1 lần
            try:
                r2 = _S.get(sub, timeout=30,
                            headers={"Accept-Language": "vi,en;q=0.8"})
                if r2.status_code == 200:
                    html = r2.text
                    break
            except Exception:
                pass
            time.sleep(2 * attempt)
        if html is None:
            failed += 1
            continue
        for loc in re.findall(r"<loc>([^<]+)/cong-ty/([^<]+)</loc>", html):
            url, tail = loc[0] + "/cong-ty/" + loc[1], loc[1]
            m = re.match(r"(.+)/(\d+)\.html?$", tail)
            if not m:
                continue
            slug, cid = m.group(1), m.group(2)
            before = conn.total_changes
            upsert_directory(conn, source="topcv", slug=slug,
                             name=_slug_to_name(slug),
                             detail_url=url, company_id=cid)
            if conn.total_changes > before:
                updated += 1
        done.add(sub)
        if i % 20 == 0:
            conn.commit()
            _save_done_subs(conn, "topcv_subs_done", done)
        time.sleep(_SITEMAP_DELAY)
    conn.commit()
    _save_done_subs(conn, "topcv_subs_done", done)
    return {"source": "topcv", "pages": min(len(subs), cap),
            "subs_done": len(done & set(subs[:cap])), "subs_failed": failed,
            "rows_touched": updated}


# ---------- harvest: itviec (directory phân trang) -------------------------

def parse_itviec_directory(html: str) -> list[tuple[str, str]]:
    """[(name, slug)] từ trang /companies — thẻ <a href='/companies/x'> tên </a>."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a[href^='/companies/']"):
        href = a.get("href", "")
        m = re.match(r"^/companies/([^/?#]+)$", href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        name = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if not name or len(name) < 2:
            continue
        seen.add(slug)
        out.append((name, slug))
    return out


def harvest_itviec(conn: sqlite3.Connection, *, max_pages: int | None = None) -> dict:
    cap = max_pages or config.ITVIEC_COMPANY_PAGES
    seen: set[str] = set()
    pages = 0
    for page in range(1, cap + 1):
        url = ITVIEC_COMPANIES_URL + (f"?page={page}" if page > 1 else "")
        r = _S.get(url, timeout=30, headers={"Accept-Language": "vi,en;q=0.8"})
        r.raise_for_status()
        found = parse_itviec_directory(r.text)
        fresh = [(n, s) for n, s in found if s not in seen]
        if not fresh:
            break
        pages += 1
        for name, slug in fresh:
            seen.add(slug)
            upsert_directory(conn, source="itviec", slug=slug, name=name,
                             detail_url=f"https://itviec.com/companies/{slug}",
                             name_exact=True)
        conn.commit()
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    return {"source": "itviec", "pages": pages, "companies": len(seen)}


# ---------- harvest: topdev (trang đầu + tích lũy job) ---------------------

def harvest_topdev(conn: sqlite3.Connection) -> dict:
    """TopDev không có sitemap dùng được (500) — lấy từ: (1) trang /companies
    đầu tiên, (2) RSC của trang tìm việc (mỗi job card chứa company object với
    display_name + detail_url)."""
    r = _S.get(TOPDEV_COMPANIES_URL, timeout=40,
               headers={"Accept-Language": "vi,en;q=0.8", "RSC": "1"})
    r.raise_for_status()
    html = r.text
    pairs: dict[str, tuple[str, str]] = {}
    for m in re.finditer(r"/companies/([a-z0-9-]+-\d+)", html):
        slug = m.group(1)
        if slug in pairs:
            continue
        chunk = html[m.start():m.start() + 3000]
        nm = re.search(r'"display_name\\?":\\?"((?:[^"\\]|\\.)+)', chunk)
        pairs[slug] = (nm.group(1) if nm else _slug_to_name(slug),
                       f"https://topdev.vn/companies/{slug}")
    n_dir = len(pairs)
    # (2) RSC các trang tìm việc HCM — công ty đang tuyển (chất lượng cao nhất)
    try:
        for page in range(1, 6):  # 5 trang đầu ≈ 75 tin mới nhất
            url = "https://topdev.vn/jobs/search?region_ids=79" + (
                f"&page={page}" if page > 1 else "")
            r2 = _S.get(url, timeout=40,
                        headers={"Accept-Language": "vi,en;q=0.8"})
            if r2.status_code != 200:
                break
            for m in re.finditer(r"/companies/([a-z0-9-]+-\d+)", r2.text):
                slug = m.group(1)
                if slug in pairs:
                    continue
                chunk = r2.text[m.start():m.start() + 3000]
                nm = re.search(r'"display_name\\?":\\?"((?:[^"\\]|\\.)+)', chunk)
                pairs[slug] = (nm.group(1) if nm else _slug_to_name(slug),
                               f"https://topdev.vn/companies/{slug}")
            time.sleep(config.DELAY_BETWEEN_REQUESTS)
    except Exception:
        pass
    for slug, (name, url) in pairs.items():
        upsert_directory(conn, source="topdev", slug=slug, name=name,
                         detail_url=url, name_exact=True)
    conn.commit()
    return {"source": "topdev", "companies": len(pairs),
            "from_directory": n_dir,
            "note": "sitemap 500 phía topdev — directory trang 1 + RSC jobs"}


# ---------- enrich quy mô (ngân sách mỗi run) ------------------------------

def _fetch(url: str) -> str | None:
    try:
        r = _S.get(url, timeout=30, headers={"Accept-Language": "vi,en;q=0.8"})
        if r.status_code != 200:
            return None
        return r.text
    except Exception:
        return None


def _enrich_topcv(html: str) -> tuple[str | None, str | None]:
    """(size_raw, real_name) từ trang công ty topcv."""
    soup = BeautifulSoup(html, "html.parser")
    name = None
    h1 = soup.find("h1")
    if h1:
        name = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
    size = None
    for node in soup.find_all(string=re.compile(r"Quy mô", re.I)):
        sib = node.parent.find_next_sibling() if node.parent else None
        if sib:
            raw = sib.get_text(" ", strip=True)
            if raw and re.search(r"\d", raw):
                size = raw
                break
    return size, name


def _enrich_itviec(html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    name = None
    h1 = soup.find("h1")
    if h1:
        name = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
    size = None
    for node in soup.find_all(string=re.compile(r"Company size", re.I)):
        sib = node.parent.find_next_sibling("div") if node.parent else None
        if sib:
            raw = re.sub(r"\s+", " ", sib.get_text(" ", strip=True))
            if raw and re.search(r"\d", raw):
                size = raw
                break
    return size, name


def _enrich_topdev(html: str) -> tuple[str | None, str | None]:
    m = re.search(r'"company_size\\?":\\?"([^"\\]*)', html)
    n = re.search(r'"display_name\\?":\\?"((?:[^"\\]|\\.)+)', html)
    emp = re.search(r'"num_employees\\?":\\?"([^"\\]*)', html)
    size = m.group(1).strip() if m else None
    name = n.group(1).strip() if n else None
    if emp and size:
        size = f"{size} ({emp.group(1)} NV)"
    return (size or None), name


_ENRICHERS = {"topcv": _enrich_topcv, "itviec": _enrich_itviec,
              "topdev": _enrich_topdev}


def enrich_missing(conn: sqlite3.Connection, *, budget: int | None = None) -> dict:
    """Fetch trang detail cho các công ty chưa có quy mô — ưu tiên đang tuyển.
    Chạy hết ngân sách là dừng (lịch sự với nguồn, lượt sau nối tiếp).

    Chính sách retry: công ty đã fetch mà trang KHÔNG có quy mô → chờ 14 ngày
    trước khi thử lại; lỗi mạng (không fetch được) → KHÔNG đánh dấu, lượt sau
    retry ngay."""
    budget = budget if budget is not None else config.COMPANY_ENRICH_BUDGET
    rows = conn.execute(
        """SELECT source, slug, name, detail_url FROM company_directory
           WHERE size_raw IS NULL AND detail_url IS NOT NULL
             AND (enriched_at IS NULL
                  OR julianday(enriched_at) < julianday('now', '-14 day'))
           ORDER BY is_hiring DESC, last_seen_at ASC LIMIT ?""", (budget,)
    ).fetchall()
    done = errors = 0
    for r in rows:
        html = _fetch(r["detail_url"])
        if not html:
            errors += 1  # lỗi mạng → không đánh dấu, lượt sau retry
            continue
        fn = _ENRICHERS.get(r["source"])
        size, name = fn(html) if fn else (None, None)
        if size:
            lo, hi = parse_size_range(size)
            bucket = ("1000+" if (size and "+" in size) else bucket_for(lo, hi))
            conn.execute(
                """UPDATE company_directory SET size_raw=?, size_min=?, size_max=?,
                     bucket=?, enriched_at=? WHERE source=? AND slug=?""",
                (size, lo, hi, bucket, _now(), r["source"], r["slug"]))
            done += 1
        else:
            # không thấy quy mô — đánh dấu đã thử để không lặp vô hạn
            conn.execute(
                "UPDATE company_directory SET enriched_at=? WHERE source=? AND slug=?",
                (_now(), r["source"], r["slug"]))
        if name and name != r["name"]:
            # cập nhật tên chính xác (có dấu) khi nguồn là topcv (slug không dấu)
            conn.execute(
                "UPDATE company_directory SET name=?, name_exact=1 WHERE source=? AND slug=? AND name_exact=0",
                (name, r["source"], r["slug"]))
        conn.commit()
        time.sleep(_DETAIL_DELAY)
    return {"budget": budget, "attempted": len(rows), "enriched": done,
            "fetch_errors": errors}
