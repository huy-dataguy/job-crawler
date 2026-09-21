"""summary: "Crawl TopCV HCMC listing (3 trang đầu) → SQLite qua headless Chrome"
description: |
  Cloudflare chặn HTTP thuần → dùng headless chrome (có sẵn chromium trong
  worker image). Repo mounted /workspace (ro), SQLite /data.
"""
import sys

sys.path.insert(0, "/workspace/src")

from job_crawler import config, store, topcv  # noqa: E402

conn = store.connect(config.DB_PATH)
run_id = store.start_run(conn, "topcv")
try:
    jobs, pages = topcv.crawl()
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
