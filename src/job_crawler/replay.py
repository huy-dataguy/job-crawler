"""Reparse retained evidence without network access or renewing source freshness."""
from __future__ import annotations

from pathlib import Path

from . import config, details, raw, relevance, store


def replay_jobs() -> dict:
    conn = store.connect(config.DB_PATH)
    updated = failed = 0
    try:
        for row in conn.execute("SELECT * FROM jobs WHERE raw_artifact IS NOT NULL").fetchall():
            job = dict(row)
            try:
                path = (config.DATA_DIR / job["raw_artifact"]).resolve()
                if not path.is_relative_to(config.DATA_DIR.resolve()):
                    raise ValueError("Raw artifact outside data root")
                observed = details.timestamp(job["detail_checked_at"])
                if not observed:
                    raise ValueError("Raw artifact has no verification timestamp")
                from datetime import datetime
                parsed = details.parse_detail(raw.read(job['raw_artifact']), job, now=datetime.fromisoformat(observed))
                parsed["detail_checked_at"] = job["detail_checked_at"]
                merged = {**job, **parsed}
                relevance.annotate(merged)
                parsed.update(relevance=merged["relevance"], matched=merged["matched"])
                conn.execute("UPDATE jobs SET " + ",".join(f"{k}=?" for k in parsed) +
                             " WHERE source=? AND source_id=?",
                             list(parsed.values()) + [job["source"], job["source_id"]])
                rowid = conn.execute("SELECT rowid FROM jobs WHERE source=? AND source_id=?",
                                     (job["source"], job["source_id"])).fetchone()[0]
                store._sync_fts(conn, rowid, merged)
                updated += 1
            except Exception:
                failed += 1
        conn.commit()
    finally:
        conn.close()
    return {"updated": updated, "failed": failed, "freshness_preserved": True}
