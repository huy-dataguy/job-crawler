"""Crawler TopCV — Cloudflare chặn HTTP thuần → dùng headless Chrome one-shot.

`chrome --headless --dump-dom URL` trả HTML server-rendered đầy đủ (đã verify
ở recon: chrome124 impersonation bị CF JS-challenge, headless Chrome pass).
"""
from __future__ import annotations

import json
import re
import subprocess
import time

from bs4 import BeautifulSoup

from . import config
from . import normalize
from .itviec import _posted_iso

def _resolve_chrome() -> str:
    """Tìm chrome/chromium: override env → PATH → playwright cache."""
    import glob
    import os
    import shutil

    env_bin = os.environ.get("JC_CHROME_BIN")
    if env_bin and (os.path.isfile(env_bin) or shutil.which(env_bin)):
        return env_bin
    for cand in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(cand):
            return cand
    for pattern in (
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"),
        "/root/.cache/ms-playwright/chromium-*/chrome-linux*/chrome",
        "/ms-playwright/chromium-*/chrome-linux*/chrome",
    ):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return "google-chrome"


def _chrome_fetch(url: str, attempts: int = 2) -> str:
    cmd = [
        _resolve_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        f"--virtual-time-budget={config.CHROME_FLUSH_SECONDS}", "--dump-dom", url,
    ]
    for i in range(attempts):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
        except subprocess.TimeoutExpired:
            if i == attempts - 1:
                raise
            time.sleep(10)
            continue
        html = out.stdout
        ok = (
            "company-name" in html
            and "data-job-id" in html
            and "Attention Required" not in html
            and "Just a moment" not in html
        )
        if not ok:
            if i == attempts - 1:
                raise RuntimeError(f"TopCV không trả trang listing hợp lệ (len={len(html)})")
            time.sleep(15)
            continue
        return html
    raise RuntimeError("unreachable")


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    for card in soup.select("div[data-job-id]") :
        jid = card.get("data-job-id")
        if not jid:
            continue
        title_el = card.select_one("h3.title a[target=_blank]")
        company_el = card.select_one("span.company-name")
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
        jobs = parse_listing(_chrome_fetch(url))
        # Trang biến thế — bỏ qua card không có title, tránh ghi rác
        jobs = [j for j in jobs if j["title"]]
        if not jobs:
            break
        pages += 1
        for j in jobs:
            all_jobs[j["source_id"]] = j
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    return list(all_jobs.values()), pages
