"""Crawler TopDev — JSON API công khai của backend Saramin.

TopDev (sáp nhập Saramin 10/2026) render danh sách bằng React Server Components,
nhưng phía sau là REST API `https://api.topdev.vn/td/v2`, chính là endpoint mà
Next.js server gọi. API trả JSON đầy đủ hơn RSC flight stream và rẻ hơn ~12 lần
(2.4 KB/job so với 27.9 KB/job), kèm `ordering=newest` để crawl tăng dần.

Contract lấy từ chính JS bundle của site (`fields[job]`), không phải suy đoán:
  GET /jobs?page=N&page_size=100&region_ids=79&ordering=newest&fields[job]=...
  GET /jobs/{id}?fields[job]=id,content,requirements_arr,responsibilities,benefits_v2
  GET /jobs?ids=1,2,3            (batch refresh theo id)
API công khai cho khách chưa đăng nhập (header `X-Topdev-Device` là tuỳ chọn).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from curl_cffi import requests

from . import config, drift, normalize
from .http import fetch_json, warm_up

_S = requests.Session(impersonate=config.IMPERSONATE)

LIST_FIELDS = (
    "id,slug,title,salary,company,extra_skills,skills_str,skills_arr,skills_ids,"
    "job_types_str,job_levels_str,job_levels_ids,experiences_str,contract_types_str,"
    "addresses,status_display,detail_url,published,refreshed,expires"
)
DETAIL_FIELDS = (
    "id,content,requirements_arr,requirements_original,responsibilities,"
    "responsibilities_original,benefits_v2,expires,status_display"
)

_MAX_PAGE_SIZE = 100  # API trả 422 nếu page_size > 100

_LEVEL_MAP = (
    ("thực tập", "intern"), ("intern", "intern"),
    ("fresher", "fresher"),
    ("senior", "senior"), ("lead", "lead"), ("trưởng", "lead"),
    ("manager", "manager"), ("quản lý", "manager"), ("giám đốc", "manager"),
)


def _api_page(path: str, **params) -> tuple[object, dict]:
    """Gọi API và giữ `meta` (total/last_page) để biết coverage thật."""
    payload = fetch_json("topdev", config.TOPDEV_API + path, session=_S,
                         params={k: v for k, v in params.items() if v is not None})
    if isinstance(payload, dict):
        return payload.get("data"), payload.get("meta") or {}
    return payload, {}


def _api(path: str, **params):
    data, _ = _api_page(path, **params)
    return data


def _warm() -> None:
    """Mở session (cookie) trước khi gọi API; lỗi không chặn crawl."""
    warm_up("topdev", "https://topdev.vn/", session=_S)


def _trieu(value: float, currency: str) -> float:
    return round(value * 0.026, 1) if currency.upper() == "USD" else round(value / 1e6, 1)


def _salary_fields(sal: dict) -> tuple[str, float | None, float | None]:
    """min/max từ `*_filter` (số thật) vì `min`/`max` có thể bị che dạng '6******'."""
    sal = sal or {}
    currency = (sal.get("currency") or "VND").upper()
    try:
        lo = float(sal.get("min_filter") or 0)
        hi = float(sal.get("max_filter") or 0)
    except (TypeError, ValueError):
        lo = hi = 0.0
    if str(sal.get("is_negotiable")) == "1" or (lo <= 0 and hi <= 0):
        return "Thoả thuận", None, None
    if lo > 0 and hi > 0:
        return f"{_trieu(lo, currency):g} - {_trieu(hi, currency):g} triệu", _trieu(lo, currency), _trieu(hi, currency)
    if hi > 0:
        return f"Up to {_trieu(hi, currency):g} triệu", None, _trieu(hi, currency)
    return f"From {_trieu(lo, currency):g} triệu", _trieu(lo, currency), None


def _exp_fields(j: dict) -> tuple[str, float | None]:
    text = (j.get("experiences_str") or "").strip()
    if not text or re.search(r"not\s*required|không\s*yêu\s*cầu", text, re.I):
        return ("" if not text else text), 0.0 if text else None
    years = [float(y) for y in re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:year|năm)", text, re.I)]
    if not years:
        return text, None
    lo, hi = min(years), max(years)
    return (f"{lo:g} năm" if lo == hi else f"{lo:g} - {hi:g} năm"), lo


def _date_iso(value: str | None, *, deadline: bool = False) -> str | None:
    """'03-12-2026' (DD-MM-YYYY) → ISO; deadline = cuối ngày, local time."""
    try:
        d = datetime.strptime((value or "").strip(), "%d-%m-%Y")
    except ValueError:
        return None
    if deadline:
        d = d.replace(hour=23, minute=59)
    return d.astimezone().isoformat(timespec="seconds")


def _posted_fields(j: dict) -> tuple[str, str | None]:
    published = j.get("published") or {}
    text = (published.get("since") or "").strip()
    exact = _date_iso(published.get("date"))
    if exact:
        return text, exact
    return text, _posted_iso(text)


def _posted_iso(text: str) -> str | None:
    """'3 days ago' / '2 weeks from now' → ISO ước tính (fallback khi thiếu date)."""
    m = re.search(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s*(?:ago|from now)", text, re.I)
    if not m:
        return None
    unit = {"minute": "minutes", "hour": "hours", "day": "days",
            "week": "weeks", "month": "days", "year": "days"}[m.group(2).lower()]
    amount = int(m.group(1)) * (30 if m.group(2).lower() == "month" else 365 if m.group(2).lower() == "year" else 1)
    from datetime import timedelta
    dt = datetime.now(timezone.utc) - timedelta(**{unit: amount})
    return dt.astimezone().isoformat(timespec="seconds")


def _level(j: dict, title: str) -> str | None:
    level = normalize.parse_level(title)
    if level:
        return level
    raw = f"{j.get('job_levels_str') or ''}".lower()
    for needle, mapped in _LEVEL_MAP:
        if needle in raw:
            return mapped
    return None


def _work_mode(j: dict, city: str) -> str:
    blob = f"{j.get('job_types_str') or ''} {j.get('contract_types_str') or ''}".lower()
    if "remote" in blob:
        return "remote"
    if "hybrid" in blob:
        return "hybrid"
    return "onsite" if city else ""


def _city(j: dict) -> str:
    addr = j.get("addresses") or {}
    return (addr.get("address_region_list")
            or ", ".join(addr.get("address_region_array") or []))


def map_job(j: dict) -> dict:
    """1 object job của API → bản ghi canonical (cùng shape 3 nguồn)."""
    jid = str(j.get("id") or "")
    title = (j.get("title") or "").strip()
    company = j.get("company") or {}
    salary_text, sal_min, sal_max = _salary_fields(j.get("salary") or {})
    exp_text, exp_min = _exp_fields(j)
    posted_text, posted_at = _posted_fields(j)
    city = _city(j)
    tags = [str(s) for s in (j.get("skills_arr") or j.get("extra_skills") or [])]
    if not tags and j.get("skills_str"):
        tags = [p.strip() for p in j["skills_str"].split(",") if p.strip()]
    tags_clean = normalize.clean_tags(tags)
    skills = normalize.extract_skills(title, tags_clean)
    return {
        "source": "topdev",
        "source_id": jid,
        "title": title,
        "company": company.get("display_name") or "",
        "company_url": company.get("detail_url"),
        "url": j.get("detail_url") or j.get("job_url"),
        "city": city,
        "work_mode": _work_mode(j, city),
        "salary": salary_text,
        "experience": exp_text,
        "exp_min": exp_min,
        "category": normalize.infer_category(title, skills, ""),
        "tags": normalize.tags_json(tags_clean),
        "skills": json.dumps(skills, ensure_ascii=False),
        "is_it": int(normalize.is_it_job(title, tags_clean, "", "topdev")),
        "level": _level(j, title),
        "salary_min": sal_min,
        "salary_max": sal_max,
        "posted_text": posted_text,
        "posted_at": posted_at,
        "valid_through": _date_iso((j.get("expires") or {}).get("date"), deadline=True),
    }


def parse_listing(payload) -> list[dict]:
    """Payload API `/jobs` (dict có `data`) hoặc list job → list bản ghi canonical."""
    rows = payload.get("data") if isinstance(payload, dict) else payload
    jobs: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        job = map_job(row)
        if not job["source_id"] or not job["title"] or job["source_id"] in seen:
            continue
        seen.add(job["source_id"])
        jobs.append(job)
    return jobs


def crawl(max_pages: int | None = None) -> tuple[list[dict], int]:
    """Quét listing mới nhất trước; dừng sớm khi cả trang không còn job mới.

    `max_pages <= 0` = full sweep: đọc tới `meta.last_page` (coverage đầy đủ),
    không dừng sớm dù gặp job đã biết. Trả về (jobs, pages_crawled).
    """
    _warm()
    setting = config.MAX_PAGES_TOPDEV if max_pages is None else max_pages
    full = setting is not None and setting <= 0
    limit = None if full else setting
    page_size = min(config.TOPDEV_PAGE_SIZE, _MAX_PAGE_SIZE)
    all_jobs: dict[str, dict] = {}
    pages_crawled = 0
    page = 1
    while True:
        if limit is not None and page > limit:
            break
        if page > 500:  # chốt an toàn nếu API trả last_page sai
            break
        payload, meta = _api_page(
            "/jobs", page=page, page_size=page_size, region_ids=79,
            ordering=config.TOPDEV_ORDERING, **{"fields[job]": LIST_FIELDS})
        found = parse_listing(payload)
        if not found:
            break  # meta.total toàn quốc; region 79 hết job trước last_page
        fresh = [j for j in found if j["source_id"] not in all_jobs]
        pages_crawled += 1
        for job in fresh:
            all_jobs[job["source_id"]] = job
        try:
            last_page = int(meta.get("last_page") or 0)
        except (TypeError, ValueError):
            last_page = 0
        if last_page and page >= last_page:
            break
        # Incremental: cả trang toàn job đã biết → các trang sau cũ hơn, dừng.
        if not fresh and page > 1 and not full:
            break
        page += 1
    jobs = list(all_jobs.values())
    if not jobs:
        raise RuntimeError("TopDev API has no jobs: check source/parser")
    drift.ensure("topdev", jobs)
    return jobs, pages_crawled


def fetch_detail(job: dict) -> dict:
    """Lấy nội dung JD + trạng thái từ API detail (14KB thay vì 324KB HTML)."""
    jid = job.get("source_id")
    if not jid:
        raise ValueError("TopDev job has no source_id")
    data = _api(f"/jobs/{jid}", **{"fields[job]": DETAIL_FIELDS})
    if not isinstance(data, dict):
        raise ValueError(f"TopDev detail for {jid} is empty")
    status = str(data.get("status_display") or "").lower()
    closed = status in {"closed", "expired", "removed", "deleted"}
    expires = _date_iso((data.get("expires") or {}).get("date"), deadline=True)
    if expires and datetime.fromisoformat(expires) < datetime.now().astimezone():
        closed = True
    description = (data.get("content") or "").strip()
    requirements = _join_sections(data.get("requirements_arr"), data.get("requirements_original"))
    responsibilities = _join_sections(data.get("responsibilities"), data.get("responsibilities_original"))
    benefits = "\n".join(
        part for part in ((b or {}).get("description") for b in (data.get("benefits_v2") or []))
        if part
    )
    body = "\n".join(p for p in (description, responsibilities, requirements) if p)
    return {
        "description": body or None,
        "requirements": requirements or None,
        "benefits": benefits or None,
        "valid_through": expires,
        "status": "closed" if closed else "open",
        "status_reason": "api_status_display" if closed else "api_open",
        "application_url": job.get("url"),
        "company_url": job.get("company_url"),
        "work_mode": job.get("work_mode"),
        "employment_type": None,
    }


def _join_sections(arr, original) -> str:
    if isinstance(arr, list) and arr:
        parts = []
        for item in arr:
            if isinstance(item, dict):
                parts.append(str(item.get("value") or item.get("description") or "").strip())
            else:
                parts.append(str(item).strip())
        return "\n".join(p for p in parts if p)
    return (original or "").strip()
