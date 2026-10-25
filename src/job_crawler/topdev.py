"""Crawler TopDev — RSC flight stream (site mới 10/2026, backend Saramin).

Listing cũ (HTML server-render có a[href^="/detail-jobs/"]) đã bị TopDev bỏ
(10/2026, sáp nhập Saramin) → danh sách job giờ nằm trong React Server
Component stream: GET /jobs/search?region_ids=79&page=N kèm header `RSC: 1`
trả về text chứa object JSON đầy đủ mỗi job ({"id":..,"title":..,"salary":..}).

Bóc bằng brace-balancing từng object (flight không phải JSON chuẩn) — không
dùng browser. Chi tiết mỗi job vẫn ở /detail-jobs/<slug>-<id> như cũ.
"""
from __future__ import annotations

import json
import re
import os
import time
from datetime import datetime

from bs4 import BeautifulSoup

from curl_cffi import requests

from . import config, normalize
from .itviec import _posted_iso
from .http import fetch

_S = requests.Session(impersonate="chrome124")

LISTING_URL = "https://topdev.vn/jobs/search"
MAX_PAGES = int(os.environ.get("JC_MAX_PAGES_TOPDEV", "2"))

# object job bắt đầu bằng id + title ngay cạnh nhau (bỏ object company/id khác)
_JOB_START = re.compile(r'\{"id":\d+,"title":"')


def fetch_rsc(url: str) -> str:
    return fetch("topdev", url, session=_S, headers={"RSC": "1"})


def _balanced(s: str, start: int) -> str | None:
    """Trích object JSON cân bằng ngoặc từ vị trí start, đúng escape string."""
    depth = 0
    i, instr, esc = start, False, False
    while i < len(s):
        c = s[i]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
        i += 1
    return None


def _html_text(fragment: str | None) -> str:
    if not fragment:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(fragment, "html.parser").get_text(" ", strip=True))


def _salary_fields(sal: dict, value_text: str) -> tuple[str, float | None, float | None]:
    """min/max theo currency của tin (VND/USD lẫn lộn, đôi khi là string) →
    (text hiển thị, min triệu, max triệu). Trả thẳng số để khỏi re-parse text."""
    try:
        lo = float(sal.get("min") or 0)
        hi = float(sal.get("max") or 0)
    except (TypeError, ValueError):
        return "Thoả thuận", None, None
    if str(sal.get("is_negotiable")) == "1" or (lo <= 0 and hi <= 0):
        return "Thoả thuận", None, None
    cur = (sal.get("currency") or "").upper()
    if not cur:
        cur = "USD" if "USD" in (value_text or "") else "VND"

    def trieu(v: float) -> float:
        return round(v * 0.026, 1) if cur == "USD" else round(v / 1e6, 1)

    if lo > 0 and hi > 0:
        return f"{trieu(lo):g} - {trieu(hi):g} triệu", trieu(lo), trieu(hi)
    if hi > 0:
        return f"Up to {trieu(hi):g} triệu", None, trieu(hi)
    return f"From {trieu(lo):g} triệu", trieu(lo), None


def _exp_fields(j: dict) -> tuple[str, float | None]:
    years = [float(y) for y in re.findall(r"(\d+)\s*year", j.get("experiences_str") or "")]
    if not years:
        return "", None
    lo, hi = min(years), max(years)
    return (f"{lo:g} năm" if lo == hi else f"{lo:g} - {hi:g} năm"), lo


def _expires_iso(j: dict) -> str | None:
    raw = ((j.get("expires") or {}).get("date") or "").strip()  # DD-MM-YYYY
    try:
        d = datetime.strptime(raw, "%d-%m-%Y")
        return d.replace(hour=23, minute=59).astimezone().isoformat(timespec="seconds")
    except ValueError:
        return None


def parse_listing(raw: str) -> list[dict]:
    """Bóc list job dict từ RSC flight stream (1 trang)."""
    jobs: list[dict] = []
    seen: set[str] = set()
    for m in _JOB_START.finditer(raw):
        obj = _balanced(raw, m.start())
        if not obj:
            continue
        try:
            j = json.loads(obj)
        except json.JSONDecodeError:
            continue
        jid = str(j.get("id") or "")
        title = (j.get("title") or "").strip()
        if not jid or not title or jid in seen:
            continue
        seen.add(jid)

        sal = j.get("salary") or {}
        salary_text, sal_min, sal_max = _salary_fields(sal, sal.get("value"))
        exp_text, exp_min = _exp_fields(j)
        addr = j.get("addresses") or {}
        city = addr.get("address_region_list") or ""
        tags_raw = [str(s) for s in (j.get("skills_arr") or [])]
        posted_text = ((j.get("published") or {}).get("since") or "")
        blob = f"{title} {j.get('job_types_str') or ''}"
        tags_clean = normalize.clean_tags(tags_raw)
        jobs.append({
            "source": "topdev",
            "source_id": jid,
            "title": title,
            "company": (j.get("company") or {}).get("display_name") or "",
            "company_url": (j.get("company") or {}).get("detail_url"),
            "url": j.get("detail_url"),
            "city": city,
            "work_mode": next((mode for term, mode in
                               (("remote", "remote"), ("hybrid", "hybrid"))
                               if term in blob.lower()), "onsite" if city else ""),
            "salary": salary_text,
            "experience": exp_text,
            "exp_min": exp_min,
            "tags": normalize.tags_json(tags_clean),
            "skills": json.dumps(normalize.extract_skills(title, tags_clean), ensure_ascii=False),
            "level": normalize.parse_level(title),
            "salary_min": sal_min,
            "salary_max": sal_max,
            "posted_text": posted_text,
            "posted_at": _posted_iso(posted_text),
            "valid_through": _expires_iso(j),
            "is_it": int(normalize.is_it_job(title, tags_clean, "", "topdev")),
        })
    return jobs


def crawl(max_pages: int | None = None) -> tuple[list[dict], int]:
    """Quét listing theo trang; dừng sớm khi trang không còn job mới."""
    pages = max_pages or MAX_PAGES
    jobs: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        url = f"{LISTING_URL}?region_ids=79&page={page}"
        found = parse_listing(fetch_rsc(url))
        fresh = [j for j in found if j["source_id"] not in seen]
        for j in fresh:
            seen.add(j["source_id"])
        jobs.extend(found)
        if not fresh and page > 1:
            break
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    if not jobs:
        raise RuntimeError("TopDev RSC stream has no jobs: check source/parser")
    return jobs, len(seen)
