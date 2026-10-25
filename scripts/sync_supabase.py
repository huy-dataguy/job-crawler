"""Sync SQLite local → Supabase Postgres cho bản production trên Vercel.

Chiến lược:
- PRECOMPUTE lúc sync: open_condition (SQL SQLite julianday), provinces
  (locations.py), roles (roles.py), search text — để API Postgres chỉ việc
  lọc bằng GIN/btree index, không phải port hàm Python sang SQL.
- Incremental: jobs upsert toàn bộ (≈2k dòng, rẻ); companies/marks/runs theo
  mốc thời gian. `--full` đẩy lại tất cả (lần đầu / sửa schema).
- Lưu ý: marks KHÔNG đẩy trong chế độ incremental — production marks (sao,
  apply từ điện thoại) là chân lý trên cloud; chỉ đẩy khi --full lần đầu.
- Bảo mật: mỗi lần sync đều ENABLE ROW LEVEL SECURITY cho 4 bảng + policy chỉ
  cho chủ sở hữu (ALLOWED_EMAIL) — vô hiệu hoá quyền SELECT mặc định của anon
  trên schema public mà không cần đụng API/sync (vai trò postgres sở hữu bảng,
  không bị RLS chặn).

Chạy: .venv/bin/python scripts/sync_supabase.py [--full]
Cấu hình: SUPABASE_DB_URL, ALLOWED_EMAIL trong .env (hoặc env).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import psycopg2
import psycopg2.extras
from psycopg2 import sql as pgsql

from job_crawler import config, locations, roles

STATE_PATH = REPO / "data" / "supabase_sync_state.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  source text NOT NULL, source_id text NOT NULL,
  title text, company text, url text, city text, salary text,
  experience text, exp_min real, category text,
  tags jsonb, skills jsonb, is_it int, level text,
  salary_min real, salary_max real, posted_text text,
  posted_at timestamptz, relevance int, matched jsonb,
  first_seen_at timestamptz, last_seen_at timestamptz, is_new int,
  status text, status_reason text, valid_through timestamptz,
  date_source text, detail_checked_at timestamptz, work_mode text,
  employment_type text, company_url text,
  description text, requirements text, benefits text, application_url text,
  effective_open boolean, effective_status text,
  provinces text[], roles text[], search text,
  PRIMARY KEY (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_pj_posted ON jobs (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_pj_roles ON jobs USING GIN (roles);
CREATE INDEX IF NOT EXISTS idx_pj_provinces ON jobs USING GIN (provinces);
CREATE INDEX IF NOT EXISTS idx_pj_status ON jobs (effective_status, date_source);
CREATE TABLE IF NOT EXISTS job_marks (
  source text NOT NULL, source_id text NOT NULL,
  viewed int NOT NULL DEFAULT 0, hidden int NOT NULL DEFAULT 0,
  applied int NOT NULL DEFAULT 0, starred int NOT NULL DEFAULT 0,
  marked_at timestamptz,
  PRIMARY KEY (source, source_id)
);
CREATE TABLE IF NOT EXISTS company_directory (
  source text NOT NULL, slug text NOT NULL,
  name text, name_exact text, detail_url text, website text, address text,
  industry text, size_raw text, size_min int, size_max int,
  num_employees text, bucket text, company_type text, country text,
  working_days text, overtime text, tech_stack jsonb, public_links jsonb,
  description text, it_status text, it_evidence text,
  enrichment_error text, enriched_at timestamptz,
  provinces text[], completeness int,
  PRIMARY KEY (source, slug)
);
CREATE INDEX IF NOT EXISTS idx_pc_name ON company_directory (source, name);
CREATE INDEX IF NOT EXISTS idx_pc_url ON company_directory (source, detail_url);
CREATE INDEX IF NOT EXISTS idx_pc_bucket ON company_directory (bucket);
CREATE TABLE IF NOT EXISTS crawl_runs (
  id bigint PRIMARY KEY, source text, started_at timestamptz,
  finished_at timestamptz, status text, pages int, found int,
  new_count int, updated_count int, note text
);
"""

JOB_COLS = [
    "source", "source_id", "title", "company", "url", "city", "salary",
    "experience", "exp_min", "category", "tags", "skills", "is_it", "level",
    "salary_min", "salary_max", "posted_text", "posted_at", "relevance",
    "matched", "first_seen_at", "last_seen_at", "is_new", "status",
    "status_reason", "valid_through", "date_source", "detail_checked_at",
    "work_mode", "employment_type", "company_url", "description",
    "requirements", "benefits", "application_url", "effective_open",
    "effective_status", "provinces", "roles", "search",
]

CO_COLS = [
    "source", "slug", "name", "name_exact", "detail_url", "website",
    "address", "industry", "size_raw", "size_min", "size_max",
    "num_employees", "bucket", "company_type", "country", "working_days",
    "overtime", "tech_stack", "public_links", "description", "it_status",
    "it_evidence", "enrichment_error", "enriched_at", "provinces",
    "completeness",
]

_TS_COLS = {"posted_at", "valid_through", "detail_checked_at", "first_seen_at",
            "last_seen_at", "enriched_at", "marked_at", "started_at", "finished_at"}


def _ts(v):
    if v is None:
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _jlist(v):
    if not v:
        return []
    try:
        out = json.loads(v)
        return out if isinstance(out, list) else []
    except (TypeError, ValueError):
        return []


def effective_status(row, now):
    """Port details.open_condition() + CASE effective_status sang Python."""
    checked = _ts(row["detail_checked_at"])
    valid_through = _ts(row["valid_through"])
    open_ = (row["status"] == "open" and checked is not None
             and now - checked <= timedelta(hours=config.OPEN_CHECK_HOURS)
             and (valid_through is None or valid_through >= now))
    if open_:
        return True, "open"
    closed = row["status"] == "closed" or (valid_through is not None and valid_through < now)
    return False, ("closed" if closed else "unknown")


def build_job(row, now):
    tags, skills = _jlist(row["tags"]), _jlist(row["skills"])
    open_, status_ = effective_status(row, now)
    provs = sorted(locations.provinces(row["city"], False))
    role_slugs = [s for s in roles.names() if roles.matches(s, row["title"], row["category"])]
    search = " ".join(filter(None, [
        row["title"] or "", row["company"] or "", row["category"] or "",
        *[str(t) for t in tags], *[str(s) for s in skills]])).lower()
    out = {c: row[c] for c in JOB_COLS if c in row.keys()}
    out.update({
        "tags": json.dumps(tags, ensure_ascii=False),
        "skills": json.dumps(skills, ensure_ascii=False),
        "matched": row["matched"] or "[]",
        "provinces": provs,
        "roles": role_slugs,
        "search": search,
        "effective_open": open_,
        "effective_status": status_,
        "exp_min": row["exp_min"],
    })
    for c in _TS_COLS & set(out):
        out[c] = _ts(out[c])
    return out


def build_company(row):
    row = dict(row)
    provs = sorted(locations.provinces(row.get("address"), True))
    present = sum(bool(row.get(k)) for k in (
        "name_exact", "website", "address", "industry", "size_raw",
        "description", "company_type", "country", "working_days", "tech_stack"))
    out = {c: row[c] for c in CO_COLS if c in row.keys()}
    out.update({
        "tech_stack": row["tech_stack"] or "[]",
        "public_links": row["public_links"] or "[]",
        "provinces": provs,
        "completeness": round(present / 10 * 100),
        "size_min": row["size_min"], "size_max": row["size_max"],
    })
    for c in _TS_COLS & set(out):
        out[c] = _ts(out[c])
    return out


def upsert(pg, table, cols, rows, conflict: tuple[str, ...], page=500):
    if not rows:
        return 0
    update_cols = [c for c in cols if c not in conflict]
    tmpl = (f"INSERT INTO {table} ({','.join(cols)}) VALUES %s "
            f"ON CONFLICT ({','.join(conflict)}) DO UPDATE SET "
            + ",".join(f"{c}=EXCLUDED.{c}" for c in update_cols))
    for i in range(0, len(rows), page):
        psycopg2.extras.execute_values(
            pg.cursor(), tmpl, rows[i:i + page], page_size=page, fetch=False)
    return len(rows)


RLS_TABLES = ("jobs", "job_marks", "company_directory", "crawl_runs")


def apply_rls(cur, email: str):
    """Idempotent: ENABLE RLS + policy SELECT chỉ cho đúng email chủ.

    - Policy áp cho role `authenticated` (qua PostgREST với publishable key);
      `anon` bị REVOKE hoàn toàn. Không có policy INSERT/UPDATE/DELETE →
      PostgREST không thể ghi, chỉ API (kết nối postgres trực tiếp) ghi được.
    - DROP+CREATE lại mỗi lần sync: cửa sổ giữa 2 câu lệnh fail-closed
      (authenticated mất SELECT trong tích tắc, an toàn hơn thiếu policy).
    """
    for t in RLS_TABLES:
        ident = pgsql.Identifier("public", t)
        cur.execute(pgsql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(ident))
        cur.execute(pgsql.SQL("DROP POLICY IF EXISTS only_owner_select ON {}").format(ident))
        cur.execute(pgsql.SQL(
            "CREATE POLICY only_owner_select ON {} FOR SELECT TO authenticated"
            " USING ((auth.jwt() ->> 'email') = {})").format(ident, pgsql.Literal(email)))
        cur.execute(pgsql.SQL("REVOKE ALL ON {} FROM anon").format(ident))


def main(full: bool = False):
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("Thiếu SUPABASE_DB_URL (xem .env)")
    allowed_email = (os.environ.get("ALLOWED_EMAIL") or "").strip().lower()
    if not allowed_email:
        raise SystemExit("Thiếu ALLOWED_EMAIL trong .env — cần cho RLS Supabase")
    local = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    local.row_factory = sqlite3.Row
    pg = psycopg2.connect(db_url, connect_timeout=15)
    pg.autocommit = False
    now = datetime.now().astimezone()
    state = {}
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text())
    try:
        with pg.cursor() as cur:
            cur.execute(SCHEMA)
            apply_rls(cur, allowed_email)
        pg.commit()

        jobs = [build_job(r, now) for r in local.execute("SELECT * FROM jobs")]
        upsert(pg, "jobs", JOB_COLS, [[j[c] for c in JOB_COLS] for j in jobs], ("source", "source_id"))
        n_jobs = len(jobs)

        if full:
            marks = [{"source": r["source"], "source_id": r["source_id"],
                      "viewed": r["viewed"], "hidden": r["hidden"],
                      "applied": r["applied"], "starred": r["starred"],
                      "marked_at": _ts(r["marked_at"])}
                     for r in local.execute("SELECT * FROM job_marks")]
            upsert(pg, "job_marks",
                   ["source", "source_id", "viewed", "hidden", "applied",
                    "starred", "marked_at"],
                   [[m[c] for c in ("source", "source_id", "viewed", "hidden",
                                    "applied", "starred", "marked_at")] for m in marks],
                   ("source", "source_id"))
            n_marks = len(marks)
        else:
            n_marks = 0

        # companies incremental theo enriched_at/last_seen_at — 65k dòng không
        # cần đẩy lại toàn bộ mỗi 15 phút.
        since = state.get("companies_since")
        cond = "" if full or not since else "WHERE enriched_at > ? OR last_seen_at > ?"
        params = [] if full or not since else [since, since]
        companies = [build_company(r) for r in local.execute(
            f"SELECT * FROM company_directory {cond}", params)]
        upsert(pg, "company_directory", CO_COLS,
               [[c[c0] for c0 in CO_COLS] for c in companies], ("source", "slug"))

        runs = [dict(r) | {"started_at": _ts(r["started_at"]),
                           "finished_at": _ts(r["finished_at"])}
                for r in local.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 200")]
        upsert(pg, "crawl_runs",
               ["id", "source", "started_at", "finished_at", "status", "pages",
                "found", "new_count", "updated_count", "note"],
               [[r[c] for c in ("id", "source", "started_at", "finished_at",
                                "status", "pages", "found", "new_count",
                                "updated_count", "note")] for r in runs],
               ("id",))
        pg.commit()
        STATE_PATH.write_text(json.dumps({
            "last_sync": now.isoformat(timespec="seconds"),
            "companies_since": now.isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=1))
        print(f"sync OK: jobs={n_jobs} (+{n_marks} marks nếu full) "
              f"companies={len(companies)} runs={len(runs)}")
    finally:
        local.close()
        pg.close()


if __name__ == "__main__":
    main(full="--full" in sys.argv)
