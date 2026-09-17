"""Dashboard đọc SQLite job_crawler.db — FastAPI + Jinja2, render server-side."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

DB_PATH = Path(
    os.environ.get(
        "JC_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "job_crawler.db"
    )
)
app = FastAPI(title="Job Crawler Dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


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
def index(
    request: Request,
    q: str = "",
    source: str = "",
    category: str = "",
    exp: str = "",
    tag: str = "",
):
    conn = db()
    where, params = ["1=1"], []

    if q:
        where.append("(title LIKE ? OR company LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if source:
        where.append("source = ?")
        params.append(source)
    if category:
        where.append("category = ?")
        params.append(category)
    if exp:
        where.append("experience LIKE ?")
        params.append(f"%{exp}%")
    if tag:
        where.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    where_s = " AND ".join(where)
    jobs = conn.execute(
        f"""SELECT * FROM jobs WHERE {where_s}
            ORDER BY posted_at DESC NULLS LAST LIMIT 300""",
        params,
    ).fetchall()
    stats = conn.execute(
        f"""SELECT count(*) total,
                   sum(is_active) active,
                   sum(posted_at >= ?) new24h,
                   sum(is_new=1) new_flag
            FROM jobs WHERE {where_s}""",
        params + [(datetime.now() - timedelta(hours=24)).isoformat()],
    ).fetchone()
    by_source = conn.execute(
        f"SELECT source, count(*) n FROM jobs WHERE {where_s} GROUP BY source", params
    ).fetchall()
    by_category = conn.execute(
        "SELECT category, count(*) n FROM jobs WHERE category != '' GROUP BY category ORDER BY n DESC LIMIT 12"
    ).fetchall()
    conn.close()

    return templates.TemplateResponse(
        request,
        "index.html",
        dict(jobs=jobs, stats=stats, by_source=by_source, by_category=by_category,
             q=q, source=source, category=category, exp=exp, tag=tag),
    )


@app.get("/api/jobs")
def api_jobs(limit: int = Query(100, le=500), offset: int = 0, source: str = "",
             q: str = ""):
    conn = db()
    where, params = ["1=1"], []
    if source:
        where.append("source=?")
        params.append(source)
    if q:
        where.append("(title LIKE ? OR company LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    rows = conn.execute(
        f"""SELECT source, source_id, title, company, url, city, salary, experience,
                   category, tags, posted_text, posted_at, first_seen_at, last_seen_at
            FROM jobs WHERE {' AND '.join(where)} ORDER BY posted_at DESC NULLS LAST LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return JSONResponse([
        {**dict(r), "tags": json.loads(r["tags"] or "[]")} for r in rows
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
           "generated_at": datetime.now().isoformat(timespec="seconds")}
    for label, sql in {
        "topcv_top_exp": "SELECT experience, count(*) n FROM jobs WHERE source='topcv' GROUP BY experience ORDER BY n DESC",
        "itviec_top_categories": "SELECT category, count(*) n FROM jobs WHERE source='itviec' AND category != '' GROUP BY category ORDER BY n DESC LIMIT 10",
    }.items():
        out[label] = [dict(r) for r in conn.execute(sql)]
    conn.close()
    return out
