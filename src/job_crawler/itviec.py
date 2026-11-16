"""Crawler ITviec — HTTP thuần (server-rendered), không cần browser."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from curl_cffi import requests
from bs4 import BeautifulSoup

from . import config, drift
from . import normalize
from .http import fetch, warm_up

_S = requests.Session(impersonate=config.IMPERSONATE)

_SLUG_RE = re.compile(r"-\d{3,4}$")


def fetch_html(url: str) -> str:
    return fetch("itviec", url, session=_S)


def _txt(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def parse_item_list(html: str) -> list[tuple[str, str]]:
    """ItemList JSON-LD: [(url, name)] — dạng dữ liệu site tự công bố cho crawler.

    Dùng làm lớp thứ hai: khi CSS card đổi class, ta vẫn có URL để đi tiếp và
    biết chính xác trang có bao nhiêu job (drift detector).
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.get_text())
        except (ValueError, TypeError):
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if not isinstance(obj, dict) or "ItemList" not in str(obj.get("@type")):
                continue
            for entry in obj.get("itemListElement") or []:
                if not isinstance(entry, dict):
                    continue
                item = entry.get("item") if isinstance(entry.get("item"), dict) else {}
                url = entry.get("url") or item.get("url") or ""
                name = entry.get("name") or item.get("name") or ""
                if isinstance(url, str) and "/it-jobs/" in url:
                    out.append((url.split("?")[0], name))
    return list(dict.fromkeys(out))


def _url_to_slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


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
    # Lớp dự phòng: ItemList JSON-LD có URL mà CSS card không parse được
    # (site đổi markup) → vẫn giữ job, phần chi tiết do bước verify bù.
    seen = {j["source_id"] for j in jobs}
    for url, name in parse_item_list(html):
        if _url_to_slug(url) in seen:
            continue
        jobs.append(_ld_only_job(url, name))
    return jobs


def _ld_only_job(url: str, name: str) -> dict:
    slug = _url_to_slug(url)
    title = name or slug.rsplit("-", 1)[0].replace("-", " ").title()
    level = normalize.parse_level(title)
    return {
        "source": "itviec", "source_id": slug, "title": title, "company": "",
        "company_url": None, "url": url, "city": "", "work_mode": None,
        "salary": "N/A", "experience": "", "exp_min": normalize.LEVEL_EXP.get(level),
        "category": normalize.infer_category(title, [], ""),
        "tags": normalize.tags_json([]), "skills": "[]", "is_it": 1,
        "level": level, "salary_min": None, "salary_max": None,
        "posted_text": "", "posted_at": None, "_fallback": True,
    }


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
    warm_up("itviec", config.LISTING_URL, session=_S)
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
    jobs = list(all_jobs.values())
    fallback = sum(1 for j in jobs if j.pop("_fallback", False))
    if jobs and fallback / len(jobs) > 1 - config.MIN_FILL_RATE:
        raise drift.SchemaDrift(
            "itviec", fill_rate=1 - fallback / len(jobs),
            threshold=config.MIN_FILL_RATE, sample_missing=["div[class*=job-card]"])
    drift.ensure("itviec", jobs)
    return jobs, pages
