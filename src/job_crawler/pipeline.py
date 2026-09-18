"""Pipeline: crawl các nguồn → upsert SQLite → ghi run manifest."""
from __future__ import annotations

import sqlite3

from . import config, itviec, store, topcv, topdev

SOURCES = {"itviec": itviec, "topcv": topcv, "topdev": topdev}


def run_source(name: str) -> dict:
    conn = store.connect(config.DB_PATH)
    run_id = store.start_run(conn, name)
    try:
        jobs = SOURCES[name].crawl()
        new = upd = 0
        for j in jobs:
            if store.upsert_job(conn, j) == "new":
                new += 1
            else:
                upd += 1
        conn.commit()
        store.finish_run(conn, run_id, status="ok", pages=0, found=len(jobs),
                         new_count=new, updated_count=upd)
        return {"source": name, "found": len(jobs), "new": new, "updated": upd}
    except Exception as e:
        store.finish_run(conn, run_id, status="error", pages=0, found=0,
                         new_count=0, updated_count=0, note=repr(e)[:300])
        raise
    finally:
        conn.close()


def run_all() -> list[dict]:
    return [run_source(s) for s in ("itviec", "topcv", "topdev")]
