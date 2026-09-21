"""Crawler TopDev — HTTP thuần (Next.js server-render), không cần browser.

Listing: https://topdev.vn/jobs/search?region_ids=79 (79 = TP.HCM) &page=N, 15 tin/trang.
Card: a[href^="/detail-jobs/"] (title, id ở cuối slug) + company + salary +
      location/type + skill chips (a[href*=keyword=]) + "N days ago".
"""
from __future__ import annotations

import json
import re
import time

from bs4 import BeautifulSoup
from curl_cffi import requests

from . import config, normalize
from .itviec import _posted_iso

_S = requests.Session(impersonate="chrome124")

LISTING_URL = "https://topdev.vn/jobs/search?region_ids=79"
MAX_PAGES = int(__import__("os").environ.get("JC_MAX_PAGES_TOPDEV", "4"))

_ID_RE = re.compile(r"-(\d+)(?:\?|$)")


def fetch_html(url: str) -> str:
    r = _S.get(url, timeout=30, headers={"Accept-Language": "vi,en;q=0.8"})
    r.raise_for_status()
    return r.text


def _txt(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    for a in soup.select('a[href^="/detail-jobs/"]'):
        classes = " ".join(a.get("class", []))
        if "font-semibold" not in classes:
            continue  # bỏ link trùng trong card (logo/company)
        m = _ID_RE.search(a.get("href", ""))
        if not m:
            continue
        jid = m.group(1)
        card = a
        for _ in range(8):  # leo lên đúng card (div.cursor-pointer chứa card)
            card = card.parent
            if card is None:
                break
            if card.name == "div" and "cursor-pointer" in " ".join(card.get("class", [])):
                break
        if card is None or card.name != "div":
            continue
        title = _txt(a)
        company = ""
        sib = a.find_next_sibling("span")
        if sib:
            company = _txt(sib)
        salary = ""
        sal_el = card.select_one('span[class*="text-[#e4007f]"] span')
        if sal_el:
            salary = _txt(sal_el)
            if "login" in salary.lower():
                salary = ""
        location = ""
        for sp in card.select("span"):
            t = _txt(sp)
            if t in ("Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Remote", "Hybrid"):
                location = t
                break
        skills_raw = [_txt(x) for x in card.select('a[href*="keyword="]')]
        posted_text = ""
        for sp in card.select("span"):
            t = _txt(sp)
            if re.fullmatch(r"\d+\s+(minute|hour|day|week|month)s?\s+ago", t, re.I):
                posted_text = t
                break
        tags_clean = normalize.clean_tags(skills_raw)
        skills = normalize.extract_skills(title, tags_clean)
        level = normalize.parse_level(title)
        jobs.append(
            {
                "source": "topdev",
                "source_id": jid,
                "title": title,
                "company": company,
                "url": "https://topdev.vn/detail-jobs/" + a["href"].split("/detail-jobs/")[1].split("?")[0],
                "city": location or "Hồ Chí Minh",
                "salary": salary or "N/A",
                "experience": "",
                "exp_min": normalize.LEVEL_EXP.get(level),
                "category": normalize.infer_category(title, skills, ""),
                "tags": normalize.tags_json(skills_raw),
                "skills": json.dumps(skills, ensure_ascii=False),
                "is_it": 1 if normalize.is_it_job(title, tags_clean, "", "topdev") else 0,
                "level": level,
                "salary_min": normalize.parse_salary_range(salary)[0],
                "salary_max": normalize.parse_salary_range(salary)[1],
                "posted_text": posted_text,
                "posted_at": _posted_iso(posted_text),
            }
        )
    # dedup (card có thể match 2 lần)
    return list({j["source_id"]: j for j in jobs}.values())


def crawl(max_pages: int | None = None) -> tuple[list[dict], int]:
    """Trả về (jobs, pages_crawled)."""
    all_jobs: dict[str, dict] = {}
    pages = 0
    for page in range(1, (max_pages or MAX_PAGES) + 1):
        url = LISTING_URL + (f"&page={page}" if page > 1 else "")
        found = parse_listing(fetch_html(url))
        if not found:
            break
        pages += 1
        for j in found:
            all_jobs[j["source_id"]] = j
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    return list(all_jobs.values()), pages
