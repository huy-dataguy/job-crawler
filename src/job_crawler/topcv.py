"""TopCV public national IT listings, acquired through a source-scoped TLS session.

TopCV nằm sau Cloudflare. Kinh nghiệm đo được: burst 5 request song song bị
`403` + `cf-mitigated: challenge`, trong khi warm-up trang chủ rồi giữ **một**
session (cookie cf_clearance) và giãn cách ~2.5s thì 6/6 request trả 200.
Vì vậy: không xoay TLS profile mỗi lần lỗi (xoay = mất cookie = tự bắn vào
challenge), chỉ warm-up một lần và tái dùng session.
"""
from __future__ import annotations

import json
import re
import time

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from . import config, drift
from . import normalize
from .http import SourceError, fetch, warm_up
from .itviec import _posted_iso

_IMPERSONATE_CHAIN: tuple[str, ...] = ("chrome136", "safari184", "chrome124")
_sticky_profile: str = "chrome136"
_profile_idx: int = 0
_sessions: dict[str, curl_requests.Session] = {}
_warmed = False


def _get_session(profile: str | None = None) -> curl_requests.Session:
    p = profile or _sticky_profile
    if p not in _sessions:
        _sessions[p] = curl_requests.Session(impersonate=p)
    return _sessions[p]


def _warm(force: bool = False) -> None:
    """Lấy cookie hợp lệ trước khi vào listing; force=True xoay profile khi bị challenge."""
    global _warmed, _sticky_profile, _profile_idx
    if _warmed and not force:
        return
    start = _profile_idx if not force else (_profile_idx + 1) % len(_IMPERSONATE_CHAIN)
    for offset in range(len(_IMPERSONATE_CHAIN)):
        idx = (start + offset) % len(_IMPERSONATE_CHAIN)
        profile = _IMPERSONATE_CHAIN[idx]
        if warm_up("topcv", "https://www.topcv.vn/", session=_get_session(profile)):
            _sticky_profile = profile
            _profile_idx = idx
            _warmed = True
            return
    _warmed = True  # vẫn thử listing: warm-up lỗi không được chặn crawl


def fetch_html(
    url: str,
    expect: tuple[str, ...] = (),
    timeout: float = 30,
) -> str:
    """Fetch one public page with the sticky session; rotate profile on challenge."""
    _warm()
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            html = fetch("topcv", url, session=_get_session(), timeout=timeout)
            if expect and not all(tok in html for tok in expect):
                raise SourceError(f"TopCV page missing {expect}: markup drifted")
            return html
        except SourceError as exc:
            last_exc = exc
            if exc.status == 403 and attempt < 2:
                _warm(force=True)
                time.sleep(2 ** attempt + 1)
                continue
            raise
    raise last_exc  # type: ignore[misc]


def _fetch_listing(url: str) -> str:
    return fetch_html(url, expect=("job-item-search-result", "data-job-id"), timeout=40)


def _url_to_id(url: str) -> str | None:
    m = re.search(r"/(\d+)\.html", url)
    return m.group(1) if m else None


def parse_item_list(html: str) -> list[tuple[str, str]]:
    """ItemList JSON-LD lồng trong CollectionPage.mainEntity: [(url, name)]."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            if "ItemList" in str(obj.get("@type")):
                for entry in obj.get("itemListElement") or []:
                    item = entry.get("item") if isinstance(entry, dict) else None
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url") or ""
                    if isinstance(url, str) and "/viec-lam/" in url:
                        out.append((url.split("?")[0], item.get("name") or ""))
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    walk(value)

    for node in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(node.get_text()))
        except (ValueError, TypeError):
            continue
    return list(dict.fromkeys(out))


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    for card in soup.select("div.job-item-search-result[data-job-id]"):
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
    # Dự phòng: card không parse được vẫn còn URL trong JSON-LD để verify bù.
    seen = {j["source_id"] for j in jobs}
    for url, name in parse_item_list(html):
        jid = _url_to_id(url)
        if not jid or jid in seen:
            continue
        jobs.append(_ld_only_job(url, jid, name))
    return jobs


def _ld_only_job(url: str, jid: str, name: str) -> dict:
    title = (name or "").strip()
    return {
        "source": "topcv", "source_id": jid, "title": title, "company": "",
        "company_url": None, "url": url, "city": "", "salary": "",
        "experience": "", "exp_min": None,
        "category": normalize.infer_category(title, [], ""),
        "tags": normalize.tags_json([]), "skills": "[]",
        "is_it": 1 if normalize.is_it_job(title, [], "", "topcv") else 0,
        "level": normalize.parse_level(title), "salary_min": None,
        "salary_max": None, "posted_text": "", "posted_at": None,
        "_fallback": True,
    }


def crawl(max_pages: int | None = None) -> tuple[list[dict], int]:
    """Trả về (jobs, pages_crawled)."""
    all_jobs: dict[str, dict] = {}
    pages = 0
    for page in range(1, (max_pages or config.MAX_PAGES_TOPCV) + 1):
        url = config.TOPCV_URL + (("&" if "?" in config.TOPCV_URL else "?") + f"page={page}" if page > 1 else "")
        jobs = parse_listing(_fetch_listing(url))
        # Trang biến thế — bỏ qua card không có title, tránh ghi rác
        jobs = [j for j in jobs if j["title"]]
        if not jobs and page == 1:
            raise RuntimeError("TopCV first page has no jobs: check source/parser")
        if not jobs:
            break
        if all(j["source_id"] in all_jobs for j in jobs):
            break
        pages += 1
        for j in jobs:
            all_jobs[j["source_id"]] = j
    jobs = list(all_jobs.values())
    fallback = sum(1 for j in jobs if j.pop("_fallback", False))
    if jobs and fallback / len(jobs) > 1 - config.MIN_FILL_RATE:
        raise drift.SchemaDrift(
            "topcv", fill_rate=1 - fallback / len(jobs),
            threshold=config.MIN_FILL_RATE,
            sample_missing=["div.job-item-search-result"])
    drift.ensure("topcv", jobs)
    return jobs, pages


def fetch_detail(job: dict) -> dict:
    """Detail TopCV qua session đã warm-up (tránh 403 Cloudflare)."""
    from .details import parse_detail
    html = fetch_html(job["url"], timeout=40)
    return parse_detail(html, job)
