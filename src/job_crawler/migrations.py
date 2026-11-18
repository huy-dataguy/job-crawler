"""Explicit additive migrations. Existing SQLite is backed up before schema changes."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

JOB_FIELDS = {
    "company_url": "TEXT", "description": "TEXT", "requirements": "TEXT",
    "benefits": "TEXT", "employment_type": "TEXT", "work_mode": "TEXT",
    "valid_through": "TEXT", "application_url": "TEXT",
    "status": "TEXT NOT NULL DEFAULT 'unknown'", "status_reason": "TEXT",
    "detail_checked_at": "TEXT", "detail_attempted_at": "TEXT", "detail_error": "TEXT",
    "date_source": "TEXT NOT NULL DEFAULT 'listing'", "raw_artifact": "TEXT",
}
COMPANY_FIELDS = {
    "industry": "TEXT", "description": "TEXT", "website": "TEXT", "address": "TEXT",
    "company_type": "TEXT", "country": "TEXT", "working_days": "TEXT", "overtime": "TEXT",
    "tech_stack": "TEXT", "benefits": "TEXT", "logo_url": "TEXT", "public_links": "TEXT",
    "it_status": "TEXT NOT NULL DEFAULT 'unknown'", "it_evidence": "TEXT",
    "raw_artifact": "TEXT", "enrichment_error": "TEXT", "next_enrich_at": "TEXT",
}


def migrate(path: Path) -> dict:
    from . import companies_crawl, store
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        with sqlite3.connect(path) as old:
            version = old.execute("PRAGMA user_version").fetchone()[0]
            if version >= 5:
                try:
                    old.execute("PRAGMA busy_timeout=60000")
                    old.execute("PRAGMA journal_mode=WAL")
                    old.commit()
                except sqlite3.OperationalError:
                    pass
                return {"version": version, "changed": False}
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.parent / "backups" / f"{path.stem}-{stamp}.db"
            backup.parent.mkdir(exist_ok=True)
            with sqlite3.connect(backup) as target:
                old.backup(target)
    conn = store._initialize_schema(path)
    conn.executescript(companies_crawl._SCHEMA)
    # Retain the legacy company-size read model for backwards-compatible serving.
    from .company_enrich import ensure_company_tables
    ensure_company_tables(conn)
    try:
        with conn:
            for table, fields in (("jobs", JOB_FIELDS), ("company_directory", COMPANY_FIELDS)):
                existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                for field, sql_type in fields.items():
                    if field not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {field} {sql_type}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_verify ON jobs(status, detail_checked_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company_name ON jobs(source,company,status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company_url ON jobs(source,company_url,status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_company_enrich ON company_directory(it_status, next_enrich_at, enriched_at)")
            # v4: tra hồ sơ công ty theo khóa (source, name/detail_url) — EXISTS
            # filter quy mô công ty trong /api/jobs và batch lookup hồ sơ.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_company_dir_src_name ON company_directory(source, name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_company_dir_src_url ON company_directory(source, detail_url)")
            # v5: job_marks.starred — đánh dấu yêu thích job trong dashboard.
            mcols = {r[1] for r in conn.execute("PRAGMA table_info(job_marks)")}
            if "starred" not in mcols:
                conn.execute("ALTER TABLE job_marks ADD COLUMN starred INTEGER NOT NULL DEFAULT 0")
            conn.execute("PRAGMA user_version=5")
    finally:
        conn.close()
    return {"version": 5, "changed": True, "backup": str(backup) if backup else None}
