"""SQLite store — bản ghi job đã làm sạch, dedup theo (source, source_id).

Không lưu raw HTML (ít dung lượng). Idempotent: crawl lại upsert last_seen.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  source        TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  title         TEXT NOT NULL,
  company       TEXT,
  url           TEXT,
  city          TEXT,
  salary        TEXT,
  experience    TEXT,
  category      TEXT,
  tags          TEXT,          -- JSON array
  posted_text   TEXT,
  posted_at     TEXT,          -- ISO 8601 (ước tính từ "N hours ago")
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  seen_count    INTEGER NOT NULL DEFAULT 1,
  is_active     INTEGER NOT NULL DEFAULT 1,
  is_new        INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs (category);

CREATE TABLE IF NOT EXISTS crawl_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT NOT NULL,
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  status        TEXT,          -- ok | error
  pages         INTEGER,
  found         INTEGER,
  new_count     INTEGER,
  updated_count INTEGER,
  note          TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


_JOB_COLS = [
    "source", "source_id", "title", "company", "url", "city", "salary",
    "experience", "category", "tags", "posted_text", "posted_at",
]


def upsert_job(conn: sqlite3.Connection, job: dict) -> str:
    """INSERT hoặc UPDATE last_seen. Trả về 'new' | 'updated'."""
    ts = now_iso()
    cur = conn.execute(
        "SELECT 1, is_new FROM jobs WHERE source=? AND source_id=?",
        (job["source"], job["source_id"]),
    ).fetchone()
    if cur is None:
        cols = _JOB_COLS + ["first_seen_at", "last_seen_at"]
        vals = [job.get(c) for c in _JOB_COLS] + [ts, ts]
        conn.execute(
            f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({', '.join('?' * len(vals))})",
            vals,
        )
        conn.execute("UPDATE jobs SET is_new=0 WHERE source=? AND source_id=? AND is_new=1",
                     (job["source"], job["source_id"]))
        return "new"
    conn.execute(
        """UPDATE jobs SET title=?, company=?, url=?, city=?, salary=?, experience=?,
             category=?, tags=?, posted_text=?, posted_at=?, last_seen_at=?,
             seen_count=seen_count+1, is_active=1 WHERE source=? AND source_id=?""",
        (
            job.get("title"), job.get("company"), job.get("url"), job.get("city"),
            job.get("salary"), job.get("experience"), job.get("category"),
            job.get("tags"), job.get("posted_text"), job.get("posted_at"),
            ts, job["source"], job["source_id"],
        ),
    )
    return "updated"


def start_run(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute(
        "INSERT INTO crawl_runs (source, started_at) VALUES (?, ?)",
        (source, now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, *, status: str, pages: int,
               found: int, new_count: int, updated_count: int, note: str = "") -> None:
    conn.execute(
        """UPDATE crawl_runs SET finished_at=?, status=?, pages=?, found=?,
             new_count=?, updated_count=?, note=? WHERE id=?""",
        (now_iso(), status, pages, found, new_count, updated_count, note, run_id),
    )
    conn.commit()
