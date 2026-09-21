"""summary: "Crawl itviec HCMC listing (3 trang đầu) → SQLite (idempotent)"
description: |
  Chạy trong worker jobcrawl. Repo mounted ở /workspace (ro), SQLite tại /data.
"""
import sys

sys.path.insert(0, "/workspace/src")

from job_crawler import config, itviec, store  # noqa: E402

conn = store.connect(config.DB_PATH)
run_id = store.start_run(conn, "itviec")
try:
    jobs, pages = itviec.crawl()
    new = upd = 0
    for j in jobs:
        if store.upsert_job(conn, j) == "new":
            new += 1
        else:
            upd += 1
    conn.commit()
    store.finish_run(conn, run_id, status="ok", pages=pages, found=len(jobs),
                     new_count=new, updated_count=upd)
    return {"found": len(jobs), "new": new, "updated": upd}
except Exception:
    store.finish_run(conn, run_id, status="error", pages=0, found=0,
                     new_count=0, updated_count=0)
    raise
finally:
    conn.close()
