"""Crawler ITviec — HTTP thuần (server-rendered), không cần browser."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone

from curl_cffi import requests
from bs4 import BeautifulSoup

from . import config
from . import normalize
from .http import fetch

_S = requests.Session(impersonate="chrome124")

_SLUG_RE = re.compile(r"-\d{3,4}$")


def fetch_html(url: str) -> str:
    return fetch("itviec", url, session=_S)


def _txt(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    for card in soup.select("div[class*=job-card]"):
        slug_attr = card.get("data-search--job-selection-job-slug-value")
        if not slug_attr:
            continue
        title_el = card.select_one("h3 a[target=_blank]")
        company_el = card.select_one("span.small-text a[href^='/companies/']")
        # posted: span đầu tiên chứa "Posted"
        posted_el = None
        for sp in card.select("span"):
            if "Posted" in sp.get_text() or "Đăng" in sp.get_text():
                posted_el = sp
                break
        category_el = card.select_one('a[href^="/it-jobs/"][title]')
        salary_el = card.select_one("div.salary")
        tags = []
        tags_box = None
        for d in card.select("div"):
            cls = " ".join(d.get("class", []))
            if "tag-list" in cls or "d-flex flex-wrap" in cls:
                tags_box = d
        tags = [_txt(a) for a in card.select('a[data-responsive-tag-list-target="tag"]')]
        if not tags and tags_box:
            tags = [_txt(a) for a in tags_box.find_all(["span", "a"]) if _txt(a)]
        posted_text = _txt(posted_el).removeprefix("Posted ").removeprefix("Đăng ")
        title = _txt(title_el)
        company_href = company_el.get("href", "") if company_el else ""
        category = _txt(category_el) or (category_el.get("title") if category_el else "")
        tags_clean = normalize.clean_tags(tags)
        skills = normalize.extract_skills(title, tags_clean, category)
        level = normalize.parse_level(title)
        salary_text = _txt(salary_el).replace("Sign in to view salary", "").strip() or "N/A"
        sal_min, sal_max = normalize.parse_salary_range(salary_text)
        jobs.append(
            {
                "source": "itviec",
                "source_id": slug_attr,
                "title": title,
                "company": _txt(company_el),
                "company_url": ("https://itviec.com" + company_href.split("?")[0]) if company_href else None,
                "url": config.BASE_URL + "it-jobs/" + slug_attr,
                "city": ", ".join(dict.fromkeys(n.get("title") or _txt(n)
                         for n in card.select('div.text-nowrap[title]'))),
                "work_mode": next((m for term,m in (("At office","onsite"),("Hybrid","hybrid"),("Remote","remote"))
                                   if any(_txt(n) == term for n in card.select('div.text-rich-grey.flex-shrink-0'))), None),
                "salary": salary_text,
                "experience": "",
                # itviec card không ghi số năm → ước tính từ level trong title
                "exp_min": normalize.LEVEL_EXP.get(level),
                "category": normalize.infer_category(title, skills, category),
                "tags": normalize.tags_json(tags),
                "skills": json.dumps(skills, ensure_ascii=False),
                "is_it": 1,  # itviec là site IT thuần
                "level": level,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "posted_text": posted_text,
                "posted_at": _posted_iso(posted_text),
            }
        )
    return jobs


def _posted_iso(text: str) -> str | None:
    """'9 hours ago' / '1 tuần trước' → ISO timestamp ước tính."""
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month)s?\s*-?\s*ago", text, re.I)
    if m:
        n = int(m.group(1))
        unit = {"minute": "minutes", "hour": "hours", "day": "days",
                "week": "weeks", "month": "days"}[m.group(2).lower()]
        if m.group(2).lower() == "month":
            n *= 30
    else:
        m2 = re.search(r"(\d+)\s*(giờ|ngày|tuần|tháng|phút|năm)\s*trước", text, re.I)
        if not m2:
            return None
        n = int(m2.group(1))
        unit = {"giờ": "hours", "ngày": "days", "tuần": "weeks",
                "tháng": "days", "phút": "minutes", "năm": "days"}[m2.group(2).lower()]
        if m2.group(2).lower() in ("tháng", "năm"):
            n *= 365 if m2.group(2).lower() == "năm" else 30
    dt = datetime.now().astimezone() - timedelta(**{unit: n})
    return dt.isoformat(timespec="seconds")


def crawl(max_pages: int | None = None) -> tuple[list[dict], int]:
    """Crawl N trang đầu của listing HCM (việc mới nằm ở các trang đầu).
    Trả về (jobs, pages_crawled)."""
    all_jobs: dict[str, dict] = {}
    pages = 0
    for page in range(1, (max_pages or config.MAX_PAGES_ITVIEC) + 1):
        url = config.LISTING_URL + (f"?page={page}" if page > 1 else "")
        html = fetch_html(url)
        found = parse_listing(html)
        if not found and page == 1:
            raise RuntimeError("ITviec first page has no jobs: check source/parser")
        if not found:
            break
        if all(j["source_id"] in all_jobs for j in found):
            break
        pages += 1
        for j in found:
            all_jobs[j["source_id"]] = j
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    return list(all_jobs.values()), pages
