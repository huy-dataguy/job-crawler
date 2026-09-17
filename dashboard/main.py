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
             since_hours: int = 0, sort: str = "posted"):
    conn = db()
    where, params = ["1=1"], []
    if source:
        where.append("source=?")
        params.append(source)
    if q:
        where.append("(title LIKE ? OR company LIKE ?)")
        params += [_q_like(q), _q_like(q)]
    if category:
        where.append("category=?")
        params.append(category)
    if exp:
        where.append("experience=?")
        params.append(exp)
    if tag:
        where.append("tags LIKE ?")
        params.append(_q_like(f'"{tag}"'))
    if since_hours:
        where.append("posted_at >= ?")
        params.append((datetime.now() - timedelta(hours=since_hours)).isoformat())
    order = "posted_at DESC NULLS LAST" if sort != "new" else "last_seen_at DESC"
    where_s = " AND ".join(where)
    total = conn.execute(f"SELECT count(*) FROM jobs WHERE {where_s}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT source, source_id, title, company, url, city, salary, experience,
                   category, tags, posted_text, posted_at, first_seen_at, last_seen_at
            FROM jobs WHERE {where_s} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return JSONResponse({
        "total": total,
        "jobs": [{**dict(r), "tags": json.loads(r["tags"] or "[]")} for r in rows],
    })


def _q_like(x: str) -> str:
    return f"%{x}%"


@app.get("/api/meta")
def api_meta():
    """Danh sách facets cho filter UI."""
    conn = db()
    tag_counts: dict[str, int] = {}
    for (tags_json,) in conn.execute("SELECT tags FROM jobs WHERE tags != ''"):
        try:
            for t in json.loads(tags_json or "[]"):
                t = t.strip()
                if t and len(t) > 2:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
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
            {"name": r["experience"], "n": r["n"]}
            for r in conn.execute(
                "SELECT experience, count(*) n FROM jobs WHERE experience != '' GROUP BY experience ORDER BY n DESC LIMIT 20"
            )
        ],
        "top_tags": [{"name": k, "n": v} for k, v in
                     sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:40]],
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
           "generated_at": datetime.now().isoformat(timespec="seconds")}
    for label, sql in {
        "topcv_top_exp": "SELECT experience, count(*) n FROM jobs WHERE source='topcv' GROUP BY experience ORDER BY n DESC",
        "itviec_top_categories": "SELECT category, count(*) n FROM jobs WHERE source='itviec' AND category != '' GROUP BY category ORDER BY n DESC LIMIT 10",
    }.items():
        out[label] = [dict(r) for r in conn.execute(sql)]
    conn.close()
    return out
