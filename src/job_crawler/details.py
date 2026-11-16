"""Original publication dates, full public descriptions and open-state evidence."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, time as day_time, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import config, normalize, raw, relevance, store
from .http import SourceError, fetch

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
HOSTS = {"itviec": {"itviec.com"}, "topcv": {"www.topcv.vn", "topcv.vn"},
         "topdev": {"topdev.vn"}}


def timestamp(value, *, deadline: bool = False) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        value = value.strip()
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if len(value) == 10 and deadline:
            dt = datetime.combine(dt.date(), day_time(23, 59, 59))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt.isoformat(timespec="seconds")
    except ValueError:
        return None


def text(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("text") or value.get("name")
    if isinstance(value, list):
        value = "\n".join(str(v) for v in value)
    if not value:
        return None
    return BeautifulSoup(str(value), "html.parser").get_text("\n", strip=True).strip() or None


def structured_objects(soup):
    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                yield from walk(item)
        elif isinstance(obj, dict):
            yield obj
            if "@graph" in obj:
                yield from walk(obj["@graph"])
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(node.get_text()))
        except (ValueError, TypeError):
            continue


def _same_title(a: str, b: str) -> bool:
    a, b = (re.sub(r"\W+", " ", t.lower()).strip() for t in (a, b))
    return bool(a and b and (a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.70))


def parse_detail(html: str, job: dict, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(LOCAL_TZ)
    soup = BeautifulSoup(html, "html.parser")
    posting = next((o for o in structured_objects(soup)
                    if "JobPosting" in ([o.get("@type")] if isinstance(o.get("@type"), str)
                                       else o.get("@type", []))
                    and _same_title(str(o.get("title", "")), job["title"])), None)
    if not posting:
        # A page with no matching posting cannot renew a job's open evidence.
        raise ValueError("No matching JobPosting: unavailable or source schema changed")
    expiry = timestamp(posting.get("validThrough"), deadline=True)
    published = timestamp(posting.get("datePosted"))
    desc = text(posting.get("description"))
    if not desc:
        raise ValueError("Matching JobPosting has no description")
    apply_nodes = [n for n in soup.select("a,button,input")
                   if re.fullmatch(r"(?:apply(?: now| for this job)?|ứng tuyển(?: ngay)?|nộp (?:đơn|hồ sơ))",
                                   n.get_text(" ", strip=True) or n.get("value", ""), re.I)
                   and not n.has_attr("disabled") and n.get("aria-disabled") != "true"
                   and "disabled" not in n.get("class", [])]
    closed_notice = bool(soup.select_one(".job-expired, .job-closed, .expired-job"))
    main = soup.select_one("main")
    main_text = main.get_text(" ", strip=True) if main else ""
    closed_notice |= bool(re.search(r"this job (?:has expired|is no longer available)|"
                                    r"tin tuyển dụng (?:đã hết hạn|đã đóng)|công việc này đã hết hạn",
                                    main_text, re.I))
    if expiry and datetime.fromisoformat(expiry) < now:
        status, reason = "closed", "source_deadline_elapsed"
    elif closed_notice:
        status, reason = "closed", "source_closed_notice"
    elif apply_nodes:
        status, reason = "open", "matching_posting_and_apply_control"
    else:
        status, reason = "unknown", "no_current_apply_control"
    location = posting.get("jobLocation", [])
    location = location if isinstance(location, list) else [location]
    cities, addresses = [], []
    for loc in location:
        address = loc.get("address", {}) if isinstance(loc, dict) else {}
        if isinstance(address, dict):
            region = address.get("addressRegion") or address.get("addressLocality")
            if region and region != "Not Available" and region not in cities:
                cities.append(region)
            if address.get("streetAddress"):
                addresses.append(address["streetAddress"])
    mode = job.get("work_mode")
    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        mode = "remote"
    org = posting.get("hiringOrganization") or {}
    company_url = job.get("company_url")
    same_as = org.get("sameAs", "")
    if isinstance(same_as, str) and urlparse(same_as).hostname in HOSTS[job["source"]]:
        company_url = same_as
    if not company_url:
        for a in soup.select('a[href*="/companies/"], a[href*="/cong-ty/"]'):
            if _same_title(a.get_text(" ", strip=True), org.get("name") or job.get("company") or ""):
                from urllib.parse import urljoin
                company_url = urljoin(job["url"], a.get("href", "")).split("?")[0]
                break
    raw_skills = posting.get("skills") or ""
    if isinstance(raw_skills, str):
        raw_skills = [v.strip() for v in raw_skills.split(",") if v.strip()]
    skills = normalize.extract_skills(job["title"], raw_skills)
    employment = posting.get("employmentType")
    if isinstance(employment, list):
        employment = ", ".join(employment)
    action = posting.get("potentialAction") or {}
    target = action.get("target") if isinstance(action, dict) else None
    if isinstance(target, dict):
        target = target.get("urlTemplate")
    if not isinstance(target, str) or urlparse(target).scheme not in ("http", "https"):
        target = job["url"]
    result = {"description": desc, "requirements": text(posting.get("qualifications") or posting.get("experienceRequirements", {}).get("text"))
              if isinstance(posting.get("experienceRequirements", {}), dict) else text(posting.get("qualifications")),
              "benefits": text(posting.get("jobBenefits")), "employment_type": employment,
              "valid_through": expiry, "status": status, "status_reason": reason,
              "detail_checked_at": now.isoformat(timespec="seconds"), "detail_error": None,
              "application_url": target, "company_url": company_url,
              "work_mode": mode}
    for field, pattern in (("requirements", r"Yêu cầu ứng viên|Your skills and experience|Job requirements"),
                           ("benefits", r"Quyền lợi ứng viên|Why you'll love working here")):
        heading = soup.find(["h2", "h3"], string=re.compile(r"^\s*(?:" + pattern + r")\s*$", re.I))
        if heading:
            block = heading.find_parent("div", class_="box-job-information-detail-item") or heading.parent
            content = block.get_text("\n", strip=True)
            if len(content) > len(heading.get_text()):
                result[field] = content
    if not result.get("work_mode"):
        if re.search(r"\bremote\b|làm việc từ xa", job.get("title", ""), re.I):
            result["work_mode"] = "remote"
        elif re.search(r"\bhybrid\b", job.get("title", ""), re.I):
            result["work_mode"] = "hybrid"
    if published:
        result.update(posted_at=published, date_source="structured")
    if cities:
        result["city"] = ", ".join(cities)
    if raw_skills:
        result["tags"] = normalize.tags_json(raw_skills)
        result["skills"] = json.dumps(skills, ensure_ascii=False)
    return result


def _detail_adapter(source: str):
    """Nguồn có API detail riêng thì dùng adapter thay vì fetch HTML + JSON-LD."""
    from . import itviec, topcv, topdev
    module = {"itviec": itviec, "topcv": topcv, "topdev": topdev}.get(source)
    return getattr(module, "fetch_detail", None) if module else None


def verify_source(conn: sqlite3.Connection, source: str, *, budget: int | None = None) -> dict:
    budget = config.JOB_DETAIL_BUDGET if budget is None else budget
    rows = conn.execute(
        """SELECT * FROM jobs WHERE source=? AND
          (detail_checked_at IS NULL OR julianday(detail_checked_at)<julianday('now','-12 hours'))
          AND (detail_attempted_at IS NULL OR julianday(detail_attempted_at)<julianday('now','-2 hours'))
          AND (posted_at IS NULL OR julianday(posted_at)>=julianday('now','-35 days') OR status='open')
          ORDER BY CASE WHEN posted_at IS NULL OR julianday(posted_at)>=julianday('now','-14 days')
                        THEN 0 ELSE 1 END,
                   detail_checked_at IS NOT NULL, detail_checked_at, relevance DESC, last_seen_at DESC
          LIMIT ?""", (source, budget)).fetchall()
    checked = opened = closed = errors = 0
    adapter = _detail_adapter(source)
    for row in rows:
        job = dict(row)
        ts = store.now_iso()
        try:
            if adapter is not None:
                # Đi qua API detail: JSON đã đủ nội dung + trạng thái, không cần
                # render HTML; http.fetch_json đã tự lưu artifact trong raw.
                detail = adapter(job)
            else:
                if urlparse(job["url"] or "").hostname not in HOSTS[source]:
                    raise ValueError("Job URL is outside source hosts")
                html = fetch(source, job["url"], kind="job")
                detail = parse_detail(html, job)
                detail["raw_artifact"] = raw.preserve(source, job["url"], html, kind="job")
            detail["detail_checked_at"] = ts
            detail["detail_attempted_at"] = ts
            merged = {**job, **detail}
            relevance.annotate(merged)
            detail.update(relevance=merged["relevance"], matched=merged["matched"])
            conn.execute("UPDATE jobs SET " + ",".join(f"{k}=?" for k in detail) +
                         ",is_active=? WHERE source=? AND source_id=?",
                         list(detail.values()) + [int(detail["status"] == "open"), source, job["source_id"]])
            store._sync_fts(conn, conn.execute("SELECT rowid FROM jobs WHERE source=? AND source_id=?",
                            (source, job["source_id"])).fetchone()[0], merged)
            from . import companies_crawl
            if detail.get("company_url"):
                companies_crawl.link_job_company(conn, source=source, company=job["company"],
                                                company_url=detail["company_url"])
            checked += 1
            opened += detail["status"] == "open"
            closed += detail["status"] == "closed"
        except Exception as exc:
            gone = isinstance(exc, SourceError) and exc.status in (404, 410)
            if gone:
                checked += 1
                closed += 1
            else:
                errors += 1
            conn.execute("UPDATE jobs SET detail_attempted_at=?, detail_error=? WHERE source=? AND source_id=?",
                         (ts, str(exc)[:300], source, job["source_id"]))
            if gone:
                conn.execute("UPDATE jobs SET status='closed',is_active=0,status_reason=?,detail_checked_at=?"
                             " WHERE source=? AND source_id=?",
                             (f"http_{exc.status}", ts, source, job["source_id"]))
            conn.commit()
            if isinstance(exc, SourceError) and exc.status in (403, 429):
                break
        conn.commit()
    return {"attempted": checked + errors, "checked": checked, "open": opened, "closed": closed, "errors": errors}


def open_condition(alias: str = "jobs") -> str:
    return (f"{alias}.status='open' AND {alias}.detail_checked_at IS NOT NULL "
            f"AND julianday({alias}.detail_checked_at)>=julianday('now','-{config.OPEN_CHECK_HOURS} hours') "
            f"AND ({alias}.valid_through IS NULL OR julianday({alias}.valid_through)>=julianday('now'))")
