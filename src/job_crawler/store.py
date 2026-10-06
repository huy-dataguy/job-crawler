"""SQLite store — bản ghi job đã làm sạch, dedup theo (source, source_id).

Không lưu raw HTML (ít dung lượng). Idempotent: crawl lại upsert last_seen.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

_SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS jobs (
  source        TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  title         TEXT NOT NULL,
  company       TEXT,
  url           TEXT,
  city          TEXT,
  salary        TEXT,
  experience    TEXT,
  exp_min       REAL,          -- năm kinh nghiệm tối thiểu (số); NULL = nguồn không ghi
  category      TEXT,
  tags          TEXT,          -- JSON array (chỉ tag kỹ năng, đã loại tag trùng experience)
  skills        TEXT,          -- JSON array skill IT chuẩn (bóc từ title+tags+category)
  is_it         INTEGER NOT NULL DEFAULT 1,  -- 1 = job IT, 0 = non-IT (chủ yếu topcv)
  -- Canonical đồng nhất xuyên nguồn (mọi job đều có, filter nào cũng chạy):
  level         TEXT,          -- intern|fresher|junior|middle|senior|lead|manager (bóc từ title)
  salary_min    REAL,          -- triệu VND/tháng (parse từ salary text; NULL = không công khai)
  salary_max    REAL,
  posted_text   TEXT,
  posted_at     TEXT,          -- ISO 8601 (ước tính từ "N hours ago")
  relevance     INTEGER,       -- 0-100: độ khớp profile CV (relevance.py)
  matched       TEXT,          -- JSON array term khớp (vd ["Python","SQL"])
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  seen_count    INTEGER NOT NULL DEFAULT 1,
  is_active     INTEGER NOT NULL DEFAULT 1,
  is_new        INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (source, source_id)
);
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

_SCHEMA_MARKS = """
CREATE TABLE IF NOT EXISTS job_marks (
  source    TEXT NOT NULL,
  source_id TEXT NOT NULL,
  viewed    INTEGER NOT NULL DEFAULT 0,
  hidden    INTEGER NOT NULL DEFAULT 0,
  marked_at TEXT NOT NULL,
  PRIMARY KEY (source, source_id)
);
"""

_SCHEMA_REST = """
CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs (category);
CREATE INDEX IF NOT EXISTS idx_jobs_exp ON jobs (exp_min);

-- Full-text search cho ô tìm từ khóa: title + company + category + tags + skills.
-- Bảng FTS standalone (KHÔNG dùng content-sync + trigger: trigger 'delete'
-- với dữ liệu index từ schema cũ từng gây corrupt index khi UPDATE).
CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
  title, company, category, tags, skills
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_TABLES)
    # Migration nhẹ cho DB cũ: thêm cột mới nếu thiếu (phải trước index/FTS)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    for col, ddl in [("exp_min", "REAL"),
                     ("skills", "TEXT"),
                     ("is_it", "INTEGER NOT NULL DEFAULT 1"),
                     ("level", "TEXT"),
                     ("salary_min", "REAL"),
                     ("salary_max", "REAL"),
                     ("relevance", "INTEGER"),
                     ("matched", "TEXT")]:
        if col not in cols:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
    # Drop FTS cũ nếu là bản content-sync/trigger (từng gây corrupt khi UPDATE)
    # hoặc thiếu cột skills (bản phân loại IT)
    fts_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='jobs_fts'").fetchone()
    if fts_sql and ("tags_text" in (fts_sql[0] or "") or "content=" in (fts_sql[0] or "")
                    or ", skills" not in (fts_sql[0] or "")):
        conn.executescript("""
            DROP TRIGGER IF EXISTS jobs_fts_ai;
            DROP TRIGGER IF EXISTS jobs_fts_ad;
            DROP TRIGGER IF EXISTS jobs_fts_au;
            DROP TABLE IF EXISTS jobs_fts;
        """)
    # Backfill điểm liên quan cho data cũ (chạy 1 lần sau khi thêm cột)
    if conn.execute("SELECT 1 FROM jobs WHERE relevance IS NULL LIMIT 1").fetchone():
        from . import relevance as _rel

        rows = conn.execute(
            "SELECT rowid, title, category, tags, skills, level, exp_min"
            " FROM jobs WHERE relevance IS NULL"
        ).fetchall()
        for r in rows:
            score, matched = _rel.backfill_row(
                r["title"], r["category"], r["tags"], r["skills"],
                r["level"], r["exp_min"])
            conn.execute(
                "UPDATE jobs SET relevance=?, matched=? WHERE rowid=?",
                (score, matched, r["rowid"]),
            )
    conn.executescript(_SCHEMA_MARKS)
    conn.executescript(_SCHEMA_REST)
    # Backfill FTS standalone cho dữ liệu hiện có
    n_jobs = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
    n_fts = conn.execute("SELECT count(*) FROM jobs_fts").fetchone()[0]
    if n_jobs and not n_fts:
        conn.execute(
            "INSERT INTO jobs_fts(rowid, title, company, category, tags, skills)"
            " SELECT rowid, title, company, category, tags, skills FROM jobs")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    return conn


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


_JOB_COLS = [
    "source", "source_id", "title", "company", "url", "city", "salary",
    "experience", "exp_min", "category", "tags", "skills", "is_it",
    "level", "salary_min", "salary_max", "posted_text", "posted_at",
    "relevance", "matched",
]


def _sync_fts(conn: sqlite3.Connection, rowid: int, job: dict) -> None:
    """Sync tay 1 doc vào FTS standalone (delete theo rowid + insert lại)."""
    conn.execute("DELETE FROM jobs_fts WHERE rowid=?", (rowid,))
    conn.execute(
        "INSERT INTO jobs_fts(rowid, title, company, category, tags, skills)"
        " VALUES (?,?,?,?,?,?)",
        (rowid, job.get("title"), job.get("company"), job.get("category"),
         job.get("tags"), job.get("skills")),
    )


def upsert_job(conn: sqlite3.Connection, job: dict) -> str:
    """INSERT hoặc UPDATE last_seen. Trả về 'new' | 'updated'."""
    ts = now_iso()
    cur = conn.execute(
        "SELECT rowid FROM jobs WHERE source=? AND source_id=?",
        (job["source"], job["source_id"]),
    ).fetchone()
    if cur is None:
        cols = _JOB_COLS + ["first_seen_at", "last_seen_at"]
        vals = [job.get(c) for c in _JOB_COLS] + [ts, ts]
        cur = conn.execute(
            f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({', '.join('?' * len(vals))})",
            vals,
        )
        _sync_fts(conn, int(cur.lastrowid), job)
        return "new"
    conn.execute(
        """UPDATE jobs SET title=?, company=?, url=?, city=?, salary=?, experience=?,
             exp_min=?, category=?, tags=?, posted_text=?, posted_at=?, last_seen_at=?,
             relevance=?, matched=?,
             seen_count=seen_count+1, is_active=1 WHERE source=? AND source_id=?""",
        (
            job.get("title"), job.get("company"), job.get("url"), job.get("city"),
            job.get("salary"), job.get("experience"), job.get("exp_min"),
            job.get("category"),
            job.get("tags"), job.get("posted_text"), job.get("posted_at"),
            ts,
            job.get("relevance"), job.get("matched"),
            job["source"], job["source_id"],
        ),
    )
    _sync_fts(conn, int(cur[0]), job)
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


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def prune(conn: sqlite3.Connection, *, keep_days: int, stale_days: int) -> int:
    """Giữ DB gọn: xoá job đăng lâu hơn `keep_days` ngày (theo posted_at,
    fallback first_seen_at) và job không thấy lại trên nguồn sau `stale_days`
    ngày (tin đã gỡ). Dọn kèm FTS + marks + company enrichment mồ côi, rồi
    VACUUM để file DB thật sự nhỏ lại. Trả về số job đã xoá.

    So sánh thời gian qua julianday() để đúng với timestamp có offset (+07:00).
    """
    now = datetime.now().astimezone()
    keep_cut = (now - timedelta(days=keep_days)).isoformat(timespec="seconds")
    stale_cut = (now - timedelta(days=stale_days)).isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT rowid, source, source_id FROM jobs
           WHERE julianday(COALESCE(NULLIF(posted_at, ''), first_seen_at)) < julianday(?)
              OR julianday(last_seen_at) < julianday(?)""",
        (keep_cut, stale_cut),
    ).fetchall()
    if not rows:
        return 0
    rowids = [r["rowid"] for r in rows]
    marks = [(r["source"], r["source_id"]) for r in rows]
    qm = ",".join("?" * len(rowids))
    conn.execute(f"DELETE FROM jobs_fts WHERE rowid IN ({qm})", rowids)
    conn.executemany(
        "DELETE FROM job_marks WHERE source=? AND source_id=?", marks)
    conn.execute(f"DELETE FROM jobs WHERE rowid IN ({qm})", rowids)
    if _table_exists(conn, "companies"):
        conn.execute(
            """DELETE FROM companies WHERE NOT EXISTS (
                 SELECT 1 FROM jobs WHERE jobs.source=companies.source
                   AND jobs.company=companies.company)""")
    deleted = len(rowids)
    conn.commit()
    conn.execute("VACUUM")  # đòi hỏi không có transaction mở — vừa commit ở trên
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return deleted
