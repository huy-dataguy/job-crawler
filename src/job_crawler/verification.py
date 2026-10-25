"""Read-only boot gate against real persisted data, not mocked success."""
from __future__ import annotations

import json

from . import config, store
from .details import open_condition


def verify() -> dict:
    conn = store.connect(config.DB_PATH)
    try:
        counts = dict(conn.execute(
            "SELECT count(*) jobs, sum(detail_checked_at IS NOT NULL) checked,"
            " sum(raw_artifact IS NOT NULL) with_raw FROM jobs").fetchone())
        counts["recent_open"] = conn.execute("SELECT count(*) FROM jobs WHERE " + open_condition() +
            " AND date_source='structured' AND julianday(posted_at)>=julianday('now','-14 days') AND julianday(posted_at)<=julianday('now')").fetchone()[0]
        counts["companies"] = conn.execute("SELECT count(*) FROM company_directory").fetchone()[0]
        counts["it_company_profiles"] = conn.execute("SELECT count(*) FROM company_directory WHERE it_status!='unknown'").fetchone()[0]
        counts["full_company_profiles"] = conn.execute("SELECT count(*) FROM company_directory WHERE raw_artifact IS NOT NULL").fetchone()[0]
        failures = []
        if not counts["recent_open"]:
            failures.append("no recent, freshly verified open job")
        if not counts["with_raw"] or not counts["full_company_profiles"]:
            failures.append("missing raw-linked job/company evidence")
        invalid = conn.execute("SELECT count(*) FROM jobs WHERE status NOT IN ('open','closed','unknown') "
                               "OR (posted_at IS NOT NULL AND julianday(posted_at) IS NULL)").fetchone()[0]
        if invalid:
            failures.append(f"{invalid} invalid canonical records")
        sources = []
        for source in ("itviec", "topcv", "topdev", "companies"):
            row = conn.execute("SELECT source,status,finished_at,found,note FROM crawl_runs WHERE source=? "
                               "AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1", (source,)).fetchone()
            sources.append(dict(row) if row else {"source":source,"status":"never_run"})
            fresh = row and conn.execute("SELECT julianday(?)>=julianday('now','-2 hours')", (row['finished_at'],)).fetchone()[0]
            if not fresh or row['status'] not in ('ok','partial'):
                failures.append(f"{source}: no recent completed crawl")
        if conn.execute("SELECT count(*) FROM jobs_fts").fetchone()[0] != counts['jobs']:
            failures.append("FTS count differs from canonical jobs")
        plan = [tuple(r) for r in conn.execute("EXPLAIN QUERY PLAN SELECT source,source_id FROM jobs WHERE " + open_condition())]
        result = {"ok":not failures,"counts":counts,"sources":sources,"failures":failures,"query_plan":plan}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        conn.close()
