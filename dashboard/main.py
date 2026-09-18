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
    for _ in range(10):  # SQLite có thể busy nếu crawler đang write
        try:
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
            break
        except sqlite3.OperationalError:
            import time

            time.sleep(0.5)
    else:
        raise RuntimeError(f"Không mở được DB {DB_PATH}")
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/", response_class=HTMLResponse)
def index():
    """SPA frontend (React build)."""
    return HTMLResponse((FRONTEND_DIST / "index.html").read_text())


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.get("/api/jobs")
def api_jobs(limit: int = Query(100, le=500), offset: int = 0, source: str = "",
             q: str = "", category: str = "", exp: str = "", tag: str = "",
             skill: str = "", level: str = "", salary_min: float = 0,
             it_only: int = 1,
             since_hours: int = 0, sort: str = "auto"):
    """Bảng đồng nhất xuyên nguồn: mọi filter (q/exp/level/category/skill/salary)
    đều chạy cho cả itviec + topcv. exp itviec là ước tính từ level trong title."""
    conn = db()
    use_fts = bool(q.strip())
    if use_fts:
        where, params = ["jobs_fts MATCH ?"], [_fts_query(q)]
        frm = "jobs JOIN jobs_fts ON jobs.rowid = jobs_fts.rowid"
    else:
        where, params = ["1=1"], []
        frm = "jobs"
    if it_only:
        where.append("jobs.is_it = 1" if use_fts else "is_it = 1")
    if source:
        where.append("source=?")
        params.append(source)
    if category:
        where.append("category=?")
        params.append(category)
    if exp:
        cond = _exp_cond(exp)
        if cond:
            where.append(cond)
    if level:
        where.append("level=?")
        params.append(level)
    if salary_min:
        where.append("salary_max IS NOT NULL AND salary_max >= ?")
        params.append(salary_min)
    if source:
        where.append("source=?")
        params.append(source)
    if category:
        where.append("category=?")
        params.append(category)
    if exp:
        cond = _exp_cond(exp)
        if cond:
            where.append(cond)
    if tag:
        where.append("tags LIKE ?")
        params.append(_q_like(f'"{tag}"'))
    if skill:
        where.append("skills LIKE ?")
        params.append(_q_like(f'"{skill}"'))
    if since_hours:
        where.append("posted_at >= ?")
        params.append((datetime.now() - timedelta(hours=since_hours)).isoformat())
    if sort == "posted" or (sort == "auto" and not use_fts):
        order = "posted_at DESC NULLS LAST"
    elif sort == "new":
        order = "last_seen_at DESC"
    elif sort == "salary":
        order = "salary_max DESC NULLS LAST"
    else:
        order = "bm25(jobs_fts)"  # relevance khi search từ khóa
    where_s = " AND ".join(where)
    total = conn.execute(f"SELECT count(*) FROM {frm} WHERE {where_s}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT jobs.source, jobs.source_id, jobs.title, jobs.company, jobs.url,
                   jobs.city, jobs.salary, jobs.experience, jobs.exp_min, jobs.category,
                   jobs.tags, jobs.skills, jobs.is_it, jobs.level,
                   jobs.salary_min, jobs.salary_max,
                   jobs.posted_text, jobs.posted_at,
                   jobs.first_seen_at, jobs.last_seen_at, jobs.is_new
            FROM {frm} WHERE {where_s} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return JSONResponse({
        "total": total,
        "jobs": [{**dict(r), "tags": json.loads(r["tags"] or "[]"),
                  "skills": json.loads(r["skills"] or "[]")} for r in rows],
    })


def _q_like(x: str) -> str:
    return f"%{x}%"


def _fts_query(q: str) -> str:
    """'java backend' → '"java" AND "backend"' (match mọi từ)."""
    terms = [t.strip('"') for t in q.split() if t.strip('" ')][:8]
    return " AND ".join(f'"{t}"' for t in terms)


_EXP_BUCKETS = [
    ("0", "Fresher / Không YC", "= 0"),
    ("1", "1 năm", "= 1"),
    ("2", "2 năm", "= 2"),
    ("3", "3 năm", "= 3"),
    ("4", "4 năm", "= 4"),
    ("5+", "5+ năm", ">= 5"),
]


_LEVELS = ["intern", "fresher", "junior", "middle", "senior", "lead", "manager"]


def _exp_cond(bucket: str) -> str | None:
    for value, _name, cond in _EXP_BUCKETS:
        if value == bucket:
            return f"exp_min {cond}"
    return None


@app.get("/api/meta")
def api_meta():
    """Danh sách facets cho filter UI."""
    conn = db()
    tag_counts: dict[str, int] = {}
    for (tags_json,) in conn.execute("SELECT tags FROM jobs WHERE is_it=1 AND tags != ''"):
        try:
            for t in json.loads(tags_json or "[]"):
                t = t.strip()
                if t and len(t) > 2:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        except json.JSONDecodeError:
            continue
    skill_counts: dict[str, int] = {}
    for (skills_json,) in conn.execute("SELECT skills FROM jobs WHERE is_it=1 AND skills != ''"):
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
                "SELECT category, count(*) n FROM jobs WHERE category != '' GROUP BY category ORDER BY n DESC LIMIT 30"
            )
        ],
        "experience": [
            {"value": value, "name": name, "n": conn.execute(
                f"SELECT count(*) FROM jobs WHERE exp_min IS NOT NULL AND exp_min {cond}"
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
                "SELECT count(*) FROM jobs WHERE is_it=1 AND level=?", [lv]).fetchone()[0]}
            for lv in _LEVELS
        ],
    }
    conn.close()
    return out


@app.get("/api/trend")
def api_trend(days: int = Query(14, le=60)):
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = db()
    rows = conn.execute(
        """SELECT date(posted_at) d, source, count(*) n
           FROM jobs WHERE posted_at >= ? GROUP BY 1, 2 ORDER BY 1""",
        [since],
    ).fetchall()
    conn.close()
    out: dict[str, dict[str, dict[str, int]]] = {}
    for r in rows:
        out.setdefault(r["d"], {})  # type: ignore
        out[r["d"]][r["source"]] = r["n"]  # type: ignore
    return JSONResponse([
        {"date": k, "itviec": v.get("itviec", 0), "topcv": v.get("topcv", 0)}
        for k, v in sorted(out.items())
    ])


@app.get("/api/stats")
def api_stats():
    conn = db()
    total, active, last24 = conn.execute(
        """SELECT count(*), sum(is_active), sum(posted_at >= ?)
           FROM jobs""",
        [(datetime.now() - timedelta(hours=24)).isoformat()],
    ).fetchone()
    out = {"total": total, "active": active, "new_24h": last24,
           "it_total": conn.execute("SELECT count(*) FROM jobs WHERE is_it=1").fetchone()[0],
           "generated_at": datetime.now().isoformat(timespec="seconds")}
    for label, sql in {
        "topcv_top_exp": """SELECT
               CASE WHEN exp_min <= 0 THEN '0' WHEN exp_min >= 5 THEN '5+'
                    ELSE CAST(CAST(exp_min AS INT) AS TEXT) END AS experience,
               count(*) n FROM jobs WHERE exp_min IS NOT NULL
               GROUP BY 1 ORDER BY MIN(exp_min)""",
        "itviec_top_categories": "SELECT category, count(*) n FROM jobs WHERE source='itviec' AND category != '' GROUP BY category ORDER BY n DESC LIMIT 10",
    }.items():
        out[label] = [dict(r) for r in conn.execute(sql)]
    conn.close()
    return out
