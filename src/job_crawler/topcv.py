"""Crawler TopCV — curl_cffi impersonate TLS profile (không cần Chrome).

Recon + probe 23/09 đã verify từ máy local VÀ từ trong Windmill worker:
- Cloudflare TopCV chặn theo TLS fingerprint (JA3), hiện KHÔNG ép JS challenge:
  curl_cffi impersonate `chrome124`/`chrome136`/`safari184` → 200 full HTML
  (cả listing lẫn company page); `chrome131`/`firefox135`/`edge101`/curl thô → 403.
- Headless Chrome trong worker bị treo → TimeoutExpired 120s mỗi run (lý do
  topcv chết từ 19/09) → bỏ hẳn Chrome.

Nếu CF siết lại: `fetch_html` thử lần lượt chuỗi profile, hết chuỗi thì raise
(challenge-then-stop, không đổi UA hammer — tránh bị ban nặng hơn).
"""
from __future__ import annotations

import json
import time

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from . import config
from . import normalize
from .itviec import _posted_iso

# Chuỗi profile TLS impersonate theo thứ tự ưu tiên. Profile pass đầu tiên sẽ
# được ghim (sticky) để các request sau chỉ tốn 1 lần fetch.
_IMPERSONATE_CHAIN: tuple[str, ...] = ("chrome124", "chrome136", "safari184")
_sticky_profile: str | None = None
_session: curl_requests.Session | None = None

# Marker của trang challenge Cloudflare (trang THẬT không chứa các chuỗi này
# trong title/head; "challenge-platform" thì trang thật cũng có nên không dùng).
_CHALLENGE_MARKERS = ("Just a moment", "Attention Required")


def _get_session() -> curl_requests.Session:
    global _session
    if _session is None:
        _session = curl_requests.Session()
    return _session


def fetch_html(
    url: str,
    expect: tuple[str, ...] = (),
    timeout: float = 30,
) -> str:
    """GET url qua curl_cffi, thử lần lượt chuỗi profile TLS.

    Nhận là challenge khi: status != 200, marker Cloudflare, hoặc thiếu token
    trong `expect` (ví dụ "data-job-id" cho listing, "Quy mô" cho company page).
    Hết chuỗi profile mà vẫn chặn → raise RuntimeError, KHÔNG retry đổi UA.
    """
    global _sticky_profile
    order: list[str] = []
    if _sticky_profile:
        order.append(_sticky_profile)
    order.extend(p for p in _IMPERSONATE_CHAIN if p not in order)

    errors: list[str] = []
    session = _get_session()
    for imp in order:
        try:
            r = session.get(
                url,
                impersonate=imp,
                timeout=timeout,
                headers={"Accept-Language": "vi,en;q=0.8"},
            )
        except Exception as e:  # transport error → thử profile kế tiếp
            errors.append(f"{imp}: {type(e).__name__}: {e}")
            continue
        html = r.text
        challenge = r.status_code != 200 or any(m in html for m in _CHALLENGE_MARKERS)
        missing_expect = bool(expect) and not all(tok in html for tok in expect)
        if challenge or missing_expect:
            errors.append(f"{imp}: status={r.status_code} challenge={challenge}")
            continue
        _sticky_profile = imp
        return html
    raise RuntimeError(
        f"TopCV chặn mọi profile TLS cho {url} [{'; '.join(errors)}] — "
        "dừng theo pattern challenge-then-stop, không hammer."
    )


def _fetch_listing(url: str) -> str:
    return fetch_html(url, expect=("company-name", "data-job-id"), timeout=40)


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    for card in soup.select("div[data-job-id]") :
        jid = card.get("data-job-id")
        if not jid:
            continue
        title_el = card.select_one("h3.title a[target=_blank]")
        company_el = card.select_one("span.company-name")
        company_link = card.select_one("a[href*='/cong-ty/']")
        salary_el = card.select_one("label.salary")
        exp_el = card.select_one("label.exp span")
        city_el = card.select_one(".city-text")
        # Tags: ưu tiên data-original-title (bản đầy đủ, không bị cắt "…");
        # chip "+N" (remaining-items) giấu nốt list trong data-original-title, tách theo dấu phẩy.
        raw_tags: list[str] = []
        for _t in card.select("span.item-tag"):
            full = (_t.get("data-original-title") or "").strip()
            raw_tags.append(full or _t.get_text(" ", strip=True))
        for _r in card.select("span.remaining-items"):
            extra = (_r.get("data-original-title") or "").strip()
            raw_tags.extend([p.strip() for p in extra.split(",") if p.strip()])
        exp_text = exp_el.get_text(" ", strip=True) if exp_el else ""
        posted_text = ""
        for sp in card.select("span, label"):
            t = sp.get_text(" ", strip=True)
            if "trước" in t and ("Đăng" in t or "giờ" in t or "ngày" in t):
                posted_text = t
                break
        href = title_el["href"] if title_el and title_el.has_attr("href") else ""
        title = title_el.get_text(" ", strip=True) if title_el else ""
        tags_clean = normalize.clean_tags(raw_tags)
        skills = normalize.extract_skills(title, tags_clean)
        salary_text = salary_el.get_text(" ", strip=True) if salary_el else ""
        sal_min, sal_max = normalize.parse_salary_range(salary_text)
        jobs.append(
            {
                "source": "topcv",
                "source_id": jid,
                "title": title,
                "company": company_el.get_text(" ", strip=True) if company_el else "",
                "company_url": (
                    (company_link["href"].split("?")[0]
                     if company_link["href"].startswith("http")
                     else "https://www.topcv.vn" + company_link["href"].split("?")[0])
                    if company_link and company_link.has_attr("href") else None),
                "url": href.split("?")[0] if href.startswith("http") else f"https://www.topcv.vn{href}",
                "city": city_el.get_text(" ", strip=True) if city_el else "",
                "salary": salary_text,
                "experience": exp_text,
                "exp_min": normalize.parse_exp_min(exp_text),
                "category": normalize.infer_category(title, skills, ""),
                "tags": normalize.tags_json(raw_tags),
                "skills": json.dumps(skills, ensure_ascii=False),
                "is_it": 1 if normalize.is_it_job(title, tags_clean, "", "topcv") else 0,
                "level": normalize.parse_level(title),
                "salary_min": sal_min,
                "salary_max": sal_max,
                "posted_text": posted_text,
                "posted_at": _posted_iso(posted_text),
            }
        )
    return jobs


def crawl(max_pages: int | None = None) -> tuple[list[dict], int]:
    """Trả về (jobs, pages_crawled)."""
    all_jobs: dict[str, dict] = {}
    pages = 0
    for page in range(1, (max_pages or config.MAX_PAGES_TOPCV) + 1):
        url = config.TOPCV_URL + (f"&page={page}" if page > 1 else "")
        jobs = parse_listing(_fetch_listing(url))
        # Trang biến thế — bỏ qua card không có title, tránh ghi rác
        jobs = [j for j in jobs if j["title"]]
        if not jobs:
            break
        pages += 1
        for j in jobs:
            all_jobs[j["source_id"]] = j
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    return list(all_jobs.values()), pages
