"""Dashboard đọc SQLite job_crawler.db — FastAPI + Jinja2, render server-side."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

FRONTEND_DIST = Path(os.environ.get(
    "JC_FRONTEND_DIST", Path(__file__).resolve().parents[1] / "frontend" / "dist"
))
DB_PATH = Path(
    os.environ.get(
        "JC_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "job_crawler.db"
    )
)
app = FastAPI(title="Job Crawler Dashboard")


def db() -> sqlite3.Connection:
    # KHÔNG dùng mode=ro: kết nối read-only trên DB WAL từng trả kết quả
    # chập chờn (lúc 0 lúc đủ) khi có WAL chưa checkpoint. App local 1 user,
    # crawler ghi ngắn → kết nối thường + busy_timeout là đủ an toàn.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    # đảm bảo bảng job_marks tồn tại (phòng khi DB tạo trước migration)
    conn.execute("""CREATE TABLE IF NOT EXISTS job_marks (
        source TEXT NOT NULL, source_id TEXT NOT NULL,
        viewed INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0,
        applied INTEGER NOT NULL DEFAULT 0,
        marked_at TEXT NOT NULL, PRIMARY KEY (source, source_id))""")
    mcols = {r[1] for r in conn.execute("PRAGMA table_info(job_marks)")}
    if "applied" not in mcols:
        conn.execute("ALTER TABLE job_marks ADD COLUMN applied INTEGER NOT NULL DEFAULT 0")
    try:
        from job_crawler.company_enrich import ensure_company_tables

        ensure_company_tables(conn)
        from job_crawler.companies_crawl import ensure_directory_tables

        ensure_directory_tables(conn)
    except Exception:
        pass
    return conn


class MarkBody(BaseModel):
    source: str
    source_id: str
    viewed: int | None = None  # 0/1, None = giữ nguyên
    hidden: int | None = None
    applied: int | None = None


@app.get("/", response_class=HTMLResponse)
def index():
    """SPA frontend (React build)."""
    return HTMLResponse((FRONTEND_DIST / "index.html").read_text())


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.post("/api/mark")
def api_mark(body: MarkBody):
    conn = db()
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("SELECT viewed, hidden, applied FROM job_marks WHERE source=? AND source_id=?",
                       (body.source, body.source_id)).fetchone()
    viewed = body.viewed if body.viewed is not None else (cur["viewed"] if cur else 0)
    hidden = body.hidden if body.hidden is not None else (cur["hidden"] if cur else 0)
    applied = body.applied if body.applied is not None else (cur["applied"] if cur else 0)
    conn.execute("""INSERT INTO job_marks(source, source_id, viewed, hidden, applied, marked_at)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(source, source_id) DO UPDATE SET viewed=?, hidden=?, applied=?, marked_at=?""",
                 (body.source, body.source_id, viewed, hidden, applied, now,
                  viewed, hidden, applied, now))
    conn.commit()
    conn.close()
    return {"ok": True, "viewed": viewed, "hidden": hidden, "applied": applied}


@app.get("/api/companies")
def api_companies(
    q: str = "",
    source: str = "",
    bucket: str = "",
    hiring: int = 0,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    """Thư mục công ty đầy đủ (harvest từ sitemap/directory 3 nguồn)."""
    conn = db()
    where = ["1=1"]
    params: list = []
    if source:
        where.append("d.source=?")
        params.append(source)
    if bucket:
        where.append("d.bucket=?")
        params.append(bucket)
    if hiring:
        where.append("d.is_hiring=1")
    if q:
        where.append("(d.name LIKE ? OR d.slug LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_s = " AND ".join(where)
    frm = ("""company_directory d LEFT JOIN
              (SELECT source, company, count(*) n FROM jobs WHERE is_it=1 GROUP BY 1, 2) j
              ON j.source = d.source AND j.company = d.name""")
    total = conn.execute(f"SELECT count(*) FROM {frm} WHERE {where_s}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT d.source, d.name AS company, d.slug AS company_slug, d.detail_url,
                   d.size_raw, d.size_min, d.size_max, d.num_employees, d.bucket,
                   d.enriched_at AS fetched_at, d.is_hiring,
                   COALESCE(j.n, 0) AS job_count
            FROM {frm} WHERE {where_s}
            ORDER BY (d.is_hiring OR COALESCE(j.n, 0) > 0) DESC, job_count DESC, d.name
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    out = [dict(r) for r in rows]
    conn.close()
    return {"total": total, "companies": out}


@app.get("/api/company-stats")
def api_company_stats():
    conn = db()
    rows = conn.execute(
        "SELECT bucket, count(*) as n FROM company_directory"
        " WHERE bucket IS NOT NULL AND bucket != '' GROUP BY bucket"
    ).fetchall()
    bucket_map = {r["bucket"]: r["n"] for r in rows}
    total = conn.execute("SELECT count(*) FROM company_directory").fetchone()[0]
    enriched = conn.execute(
        "SELECT count(*) FROM company_directory WHERE size_raw IS NOT NULL").fetchone()[0]
    hiring = conn.execute(
        "SELECT count(*) FROM company_directory WHERE is_hiring=1").fetchone()[0]
    buckets = [{"bucket": b, "n": bucket_map.get(b, 0)} for b in _COMPANY_BUCKETS]
    by_source = [
        dict(r) for r in conn.execute(
            "SELECT source, count(*) as n FROM company_directory GROUP BY source")
    ]
    conn.close()
    return {"total": total, "enriched": enriched, "hiring": hiring,
            "buckets": buckets, "by_source": by_source}


# Trạng thái review của job (inbox model) — map sang điều kiện SQL trên job_marks.
_MARK_CONDS = {
    "unseen": "COALESCE(job_marks.viewed,0)=0 AND COALESCE(job_marks.applied,0)=0"
              " AND COALESCE(job_marks.hidden,0)=0",
    "viewed": "COALESCE(job_marks.viewed,0)=1 AND COALESCE(job_marks.applied,0)=0"
              " AND COALESCE(job_marks.hidden,0)=0",
    "applied": "COALESCE(job_marks.applied,0)=1",
    "hidden": "COALESCE(job_marks.hidden,0)=1",
}


@app.get("/api/jobs")
def api_jobs(limit: int = Query(100, le=500), offset: int = 0, source: str = "",
             q: str = "", category: str = "", exp: str = "", tag: str = "",
             skill: str = "", level: str = "", salary_min: float = 0,
             it_only: int = 1, show_hidden: int = 0, company_size: str = "",
             since_hours: int = 0, sort: str = "auto", relevance_min: int = 0,
             mark: str = "all"):
    """Bảng đồng nhất xuyên nguồn. `mark` = trạng thái review (unseen/viewed/
    applied/hidden/all); `relevance_min` = ngưỡng khớp profile CV."""
    conn = db()
    frm, where_s, params, use_fts = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only,
        since_hours=since_hours, company_size=company_size,
        relevance_min=relevance_min)
    # Luôn JOIN marks: cần viewed/applied/hidden cho lọc + hiển thị
    if "job_marks" not in frm:
        frm += " LEFT JOIN job_marks ON job_marks.source=jobs.source AND job_marks.source_id=jobs.source_id"
    base_where = where_s
    if mark in _MARK_CONDS:
        base_where += f" AND {_MARK_CONDS[mark]}"
    elif not show_hidden:
        base_where += " AND COALESCE(job_marks.hidden,0)=0"
    if "companies" not in frm:
        frm += " LEFT JOIN companies ON companies.source=jobs.source AND companies.company=jobs.company"
    if sort == "posted":
        order = "jobs.posted_at DESC NULLS LAST"
    elif sort == "new":
        order = "jobs.last_seen_at DESC"
    elif sort == "salary":
        order = "jobs.salary_max DESC NULLS LAST"
    elif sort == "relevance" or (sort == "auto" and not use_fts):
        # mặc định: job khớp profile CV trước, rồi mới đăng trước
        order = "COALESCE(jobs.relevance, 0) DESC, jobs.posted_at DESC NULLS LAST"
    else:
        # search từ khóa: khớp từ khóa trước, điểm profile cộng thêm
        order = "bm25(jobs_fts), COALESCE(jobs.relevance, 0) DESC"
    total = conn.execute(f"SELECT count(*) FROM {frm} WHERE {base_where}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT jobs.source, jobs.source_id, jobs.title, jobs.company, jobs.url,
                   jobs.city, jobs.salary, jobs.experience, jobs.exp_min, jobs.category,
                   jobs.tags, jobs.skills, jobs.is_it, jobs.level,
                   jobs.salary_min, jobs.salary_max,
                   jobs.posted_text, jobs.posted_at,
                   jobs.relevance, jobs.matched,
                   jobs.first_seen_at, jobs.last_seen_at, jobs.is_new,
                   COALESCE(job_marks.viewed,0) as viewed,
                   COALESCE(job_marks.hidden,0) as hidden,
                   COALESCE(job_marks.applied,0) as applied,
                   companies.size_raw as company_size_raw,
                   companies.bucket as company_bucket,
                   companies.num_employees as company_num_employees
             FROM {frm} WHERE {base_where} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return JSONResponse({
        "total": total,
        "jobs": [{**dict(r), "tags": json.loads(r["tags"] or "[]"),
                  "skills": json.loads(r["skills"] or "[]"),
                  "matched": json.loads(r["matched"] or "[]")} for r in rows],
    })


def _q_like(x: str) -> str:
    return f"%{x}%"


def _filtered(*, q: str = "", source: str = "", category: str = "", exp: str = "",
              tag: str = "", skill: str = "", level: str = "", salary_min: float = 0,
              it_only: int = 1, since_hours: int = 0, company_size: str = "",
              relevance_min: int = 0):
    """Helper dùng chung: build FROM/WHERE cho mọi endpoint (jobs/stats/trend/meta)
    để filter nào cũng cập nhật mọi số liệu. Cột luôn prefix jobs. tránh ambiguous."""
    use_fts = bool(q.strip())
    if use_fts:
        where, params = ["jobs_fts MATCH ?"], [_fts_query(q)]
        frm = "jobs JOIN jobs_fts ON jobs.rowid = jobs_fts.rowid"
    else:
        where, params = ["1=1"], []
        frm = "jobs"
    if it_only:
        where.append("jobs.is_it = 1")
    if relevance_min:
        where.append("COALESCE(jobs.relevance, 0) >= ?")
        params.append(relevance_min)
    if source:
        where.append("jobs.source=?")
        params.append(source)
    if category:
        where.append("jobs.category=?")
        params.append(category)
    if exp:
        cond = _exp_cond(exp)
        if cond:
            where.append(cond.replace("exp_min", "jobs.exp_min", 1))
    if level:
        where.append("jobs.level=?")
        params.append(level)
    if salary_min:
        where.append("jobs.salary_max IS NOT NULL AND jobs.salary_max >= ?")
        params.append(salary_min)
    if tag:
        where.append("jobs.tags LIKE ?")
        params.append(_q_like(f'"{tag}"'))
    if skill:
        where.append("jobs.skills LIKE ?")
        params.append(_q_like(f'"{skill}"'))
    if since_hours:
        where.append("jobs.posted_at >= ?")
        params.append((datetime.now() - timedelta(hours=since_hours)).isoformat())
    if company_size:
        # JOIN companies để lọc theo bucket; LEFT JOIN để không mất job chưa có bucket khi không lọc? nhưng khi lọc thì cần INNER effect => dùng LEFT rồi WHERE bucket=...
        if "companies" not in frm:
            frm += " LEFT JOIN companies ON companies.source=jobs.source AND companies.company=jobs.company"
        where.append("companies.bucket=?")
        params.append(company_size)
    return frm, " AND ".join(where), params, use_fts


def _fts_query(q: str) -> str:
    """'java backend' → '"java" AND "backend"' (match mọi từ)."""
    terms = [t.strip('"') for t in q.split() if t.strip('" ')][:8]
    return " AND ".join(f'"{t}"' for t in terms)


# Filter năm kinh nghiệm theo góc nhìn NGƯỜI TÌM VIỆC: chọn số năm mình có,
# hiện mọi job yêu cầu TỐI ĐA bao nhiêu năm (≤ N) — tức là việc mình đủ điều
# kiện apply. exp_min NULL (nguồn không ghi) chỉ hiện khi "Tất cả".
_EXP_BUCKETS = [
    ("0", "Fresher / Không YC", "<= 0"),
    ("1", "≤ 1 năm", "<= 1"),
    ("2", "≤ 2 năm", "<= 2"),
    ("3", "≤ 3 năm", "<= 3"),
    ("5", "≤ 5 năm", "<= 5"),
]


_LEVELS = ["intern", "fresher", "junior", "middle", "senior", "lead", "manager"]


_COMPANY_BUCKETS = ["<50", "50-100", "101-150", "151-300", "301-1000", "1000+"]


def _exp_cond(bucket: str) -> str | None:
    for value, _name, cond in _EXP_BUCKETS:
        if value == bucket:
            return f"exp_min {cond}"
    return None


@app.get("/api/meta")
def api_meta(q: str = "", source: str = "",
             category: str = "", exp: str = "", tag: str = "", skill: str = "",
             level: str = "", salary_min: float = 0, it_only: int = 1,
             since_hours: int = 0, relevance_min: int = 0):
    """Facets (counts) cũng tính trên tập đã lọc — chọn filter nào, mọi số đều theo."""
    conn = db()
    frm, where_s, params, _ = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only, since_hours=since_hours,
        relevance_min=relevance_min)
    tag_counts: dict[str, int] = {}
    for (tags_json,) in conn.execute(
            f"SELECT jobs.tags FROM {frm} WHERE {where_s} LIMIT 5000", params):
        try:
            for t in json.loads(tags_json or "[]"):
                t = t.strip()
                if t and len(t) > 2:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        except json.JSONDecodeError:
            continue
    skill_counts: dict[str, int] = {}
    for (skills_json,) in conn.execute(
            f"SELECT jobs.skills FROM {frm} WHERE {where_s} LIMIT 5000", params):
        try:
            for s in json.loads(skills_json or "[]"):
                skill_counts[s] = skill_counts.get(s, 0) + 1
        except json.JSONDecodeError:
            continue
    out = {
        "sources": [r["source"] for r in conn.execute("SELECT DISTINCT source FROM jobs")],
        "categories": [
            {"name": r["category"], "n": r["n"]}
            for r in conn.execute(
                f"SELECT jobs.category, count(*) n FROM {frm} WHERE {where_s}"
                " AND jobs.category != '' GROUP BY 1 ORDER BY n DESC LIMIT 30",
                params,
            )
        ],
        "experience": [
            {"value": value, "name": name, "n": conn.execute(
                f"SELECT count(*) FROM {frm} WHERE {where_s}"
                f" AND jobs.exp_min IS NOT NULL AND jobs.exp_min {cond}",
                params,
            ).fetchone()[0]}
            for value, name, cond in _EXP_BUCKETS
        ],
        "top_tags": [{"name": k, "n": v} for k, v in
                     sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:40]],
        "top_skills": [{"name": k, "n": v} for k, v in
                       sorted(skill_counts.items(), key=lambda kv: kv[1], reverse=True)[:40]],
        "it_count": conn.execute("SELECT count(*) FROM jobs WHERE is_it=1").fetchone()[0],
        "non_it_count": conn.execute("SELECT count(*) FROM jobs WHERE is_it=0").fetchone()[0],
        "levels": [
            {"value": lv, "n": conn.execute(
                f"SELECT count(*) FROM {frm} WHERE {where_s} AND jobs.level=?",
                params + [lv]).fetchone()[0]}
            for lv in _LEVELS
        ],
    }
    conn.close()
    return out


@app.get("/api/trend")
def api_trend(days: int = Query(14, le=60), q: str = "", source: str = "",
              category: str = "", exp: str = "", tag: str = "", skill: str = "",
              level: str = "", salary_min: float = 0, it_only: int = 1, relevance_min: int = 0):
    """Trend việc mới/ngày — tôn trọng filter hiện tại (trừ since_hours)."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = db()
    frm, where_s, params, _ = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only,
        relevance_min=relevance_min)
    rows = conn.execute(
        f"""SELECT date(jobs.posted_at) d, jobs.source, count(*) n
           FROM {frm} WHERE {where_s} AND jobs.posted_at >= ? GROUP BY 1, 2 ORDER BY 1""",
        params + [since],
    ).fetchall()
    sources = [r["source"] for r in conn.execute("SELECT DISTINCT source FROM jobs")]
    conn.close()
    out: dict[str, dict[str, dict[str, int]]] = {}
    for r in rows:
        out.setdefault(r["d"], {})  # type: ignore
        out[r["d"]][r["source"]] = r["n"]  # type: ignore
    return JSONResponse({
        "sources": sources,
        "days": [{**{"date": k}, **{s: v.get(s, 0) for s in sources}}
                 for k, v in sorted(out.items())],
    })


@app.get("/api/stats")
def api_stats(q: str = "", source: str = "",
              category: str = "", exp: str = "", tag: str = "", skill: str = "",
              level: str = "", salary_min: float = 0, it_only: int = 1,
              since_hours: int = 0, relevance_min: int = 0):
    """Mọi KPI + chart phân bố đều tính trên tập đã lọc (giống danh sách job)."""
    conn = db()
    frm, where_s, params, _ = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only, since_hours=since_hours,
        relevance_min=relevance_min)
    # Lưu ý thứ tự bind params: placeholder trong SELECT đứng trước WHERE
    ts24 = (datetime.now() - timedelta(hours=24)).isoformat()
    total, active, last24 = conn.execute(
        f"""SELECT count(*), sum(jobs.is_active), sum(jobs.posted_at >= ?)
           FROM {frm} WHERE {where_s}""",
        [ts24] + params,
    ).fetchone()
    out = {"total": total, "active": active, "new_24h": last24,
           "companies": conn.execute(
               f"SELECT count(DISTINCT jobs.company) FROM {frm} WHERE {where_s}"
               " AND jobs.company != ''", params).fetchone()[0],
           "generated_at": datetime.now().isoformat(timespec="seconds")}
    for label, sql in {
        "top_exp": f"""SELECT
               CASE WHEN jobs.exp_min <= 0 THEN '0' WHEN jobs.exp_min >= 5 THEN '5+'
                    ELSE CAST(CAST(jobs.exp_min AS INT) AS TEXT) END AS experience,
               count(*) n FROM {frm} WHERE {where_s} AND jobs.exp_min IS NOT NULL
               GROUP BY 1 ORDER BY MIN(jobs.exp_min)""",
        "top_categories": f"""SELECT jobs.category, count(*) n FROM {frm}
               WHERE {where_s} AND jobs.category != '' GROUP BY 1 ORDER BY n DESC LIMIT 12""",
        # giữ key cũ để frontend cũ không vỡ
        "topcv_top_exp": f"""SELECT
               CASE WHEN jobs.exp_min <= 0 THEN '0' WHEN jobs.exp_min >= 5 THEN '5+'
                    ELSE CAST(CAST(jobs.exp_min AS INT) AS TEXT) END AS experience,
               count(*) n FROM {frm} WHERE {where_s} AND jobs.exp_min IS NOT NULL
               GROUP BY 1 ORDER BY MIN(jobs.exp_min)""",
        "itviec_top_categories": f"""SELECT jobs.category, count(*) n FROM {frm}
               WHERE {where_s} AND jobs.category != '' GROUP BY 1 ORDER BY n DESC LIMIT 12""",
    }.items():
        out[label] = [dict(r) for r in conn.execute(sql, params)]
    # Queue: số job theo trạng thái review (áp filter hiện tại, không tính mark)
    queue = {}
    for k, cond in _MARK_CONDS.items():
        queue[k] = conn.execute(
            f"SELECT count(*) FROM {frm} LEFT JOIN job_marks"
            " ON job_marks.source=jobs.source AND job_marks.source_id=jobs.source_id"
            f" WHERE {where_s} AND {cond}",
            params).fetchone()[0]
    out["queue"] = queue
    conn.close()
    return out
