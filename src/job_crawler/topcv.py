"""TopCV public national IT listings, acquired through a source-scoped TLS session."""
from __future__ import annotations

import json
import time

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from . import config
from . import normalize
from .itviec import _posted_iso
from .http import fetch

_session: curl_requests.Session | None = None


def _get_session() -> curl_requests.Session:
    global _session
    if _session is None:
        _session = curl_requests.Session(impersonate="chrome124")
    return _session


def fetch_html(
    url: str,
    expect: tuple[str, ...] = (),
    timeout: float = 30,
) -> str:
    """Fetch one public page, stopping on challenge/rate limit."""
    html = fetch("topcv", url, session=_get_session(), timeout=timeout)
    if expect and not all(tok in html for tok in expect):
        raise RuntimeError(f"TopCV schema changed: missing {expect}")
    return html


def _fetch_listing(url: str) -> str:
    return fetch_html(url, expect=("company-name", "data-job-id"), timeout=40)


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    for card in soup.select("div.job-item-search-result[data-job-id]") :
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
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    return list(all_jobs.values()), pages
