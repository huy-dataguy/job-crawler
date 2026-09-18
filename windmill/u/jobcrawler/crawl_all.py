"""summary: "Crawl cả 3 nguồn itviec + topcv + topdev → SQLite (script cho schedule)"
description: |
  Được schedule chạy lúc 09:00 / 11:00 / 14:00 / 16:00 / 21:00 (Asia/Ho_Chi_Minh).
  Idempotent: chạy lại chỉ cập nhật last_seen, không pha dữ liệu.
"""
import sys

sys.path.insert(0, "/workspace/src")

from job_crawler.pipeline import run_source  # noqa: E402

results = []
import time  # noqa: E402
for source in ("itviec", "topcv", "topdev"):
    try:
        results.append(run_source(source))
    except Exception as e:
        results.append({"source": source, "error": repr(e)[:200]})
    time.sleep(5)

ok = [r for r in results if "error" not in r]
return {"ok": len(ok), "results": results}
