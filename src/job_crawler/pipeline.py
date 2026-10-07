"""Pipeline: crawl các nguồn → làm sạch → chấm điểm liên quan → upsert SQLite
→ prune data cũ → ghi run manifest. DB chỉ giữ job IT mới + sạch, không raw.

Ngoài ra: mỗi job gắn công ty vào company_directory (tên chính xác + đang
tuyển), và lệnh `companies` harvest thư mục công ty đầy đủ từ 3 nguồn."""
from __future__ import annotations

import json
import sqlite3

from . import companies_crawl, config, itviec, relevance, store, topcv, topdev
from .notifier import TelegramError, TelegramNotifier

SOURCES = {"itviec": itviec, "topcv": topcv, "topdev": topdev}


def _notifier() -> TelegramNotifier | None:
    if not config.TELEGRAM_ENABLED:
        return None
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise TelegramError(
            "JC_TELEGRAM_ENABLED đang bật nhưng thiếu TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID"
        )
    return TelegramNotifier(
        config.TELEGRAM_BOT_TOKEN,
        config.TELEGRAM_CHAT_ID,
        timeout_seconds=config.TELEGRAM_TIMEOUT_SECONDS,
        min_interval_seconds=config.TELEGRAM_MIN_INTERVAL_SECONDS,
    )


def run_source(name: str, *, notifier: TelegramNotifier | None = None) -> dict:
    conn = store.connect(config.DB_PATH)
    companies_crawl.ensure_directory_tables(conn)
    run_id = store.start_run(conn, name)
    pages = found = new = upd = notified = skipped_non_it = 0
    seen_slugs: set[str] = set()
    try:
        raw_jobs, pages = SOURCES[name].crawl()
        # DB chỉ giữ job IT (topcv trộn job phi IT — bỏ trước khi lưu)
        skipped_non_it = sum(1 for j in raw_jobs if not j.get("is_it", 1))
        jobs = [j for j in raw_jobs if j.get("is_it", 1)]
        found = len(jobs)
        notifier = _notifier() if notifier is None else notifier
        for j in jobs:
            relevance.annotate(j)  # điểm khớp profile CV (0-100 + matched)
            outcome = store.upsert_job(conn, j)
            if outcome == "new":
                # Telegram acknowledgement precedes the insert commit.  On a
                # delivery error this job remains unseen and is retried later.
                if (notifier is not None
                        and (j["relevance"] >= config.NOTIFY_MIN_RELEVANCE
                             or config.NOTIFY_MIN_RELEVANCE <= 0)):
                    notifier.send_job(j)
                    notified += 1
                new += 1
            else:
                upd += 1
            # Gắn công ty vào thư mục (tên chính xác + đang tuyển)
            slug = companies_crawl.link_job_company(
                conn, source=j["source"], company=j.get("company") or "",
                company_url=j.get("company_url"))
            if slug:
                seen_slugs.add(slug)
            # Commit per canonical job.  If a later Telegram call fails, jobs
            # already acknowledged are durable and will not be sent twice.
            conn.commit()
        companies_crawl.refresh_hiring_flags(conn, name, seen_slugs)
        conn.commit()
        pruned = store.prune(conn, keep_days=config.KEEP_DAYS,
                             stale_days=config.STALE_DAYS)
        store.finish_run(conn, run_id, status="ok", pages=pages, found=found,
                         new_count=new, updated_count=upd,
                         note=f"telegram_notified={notified} "
                              f"skipped_non_it={skipped_non_it} pruned={pruned}")
        return {
            "source": name,
            "found": found,
            "pages": pages,
            "new": new,
            "updated": upd,
            "notified": notified,
            "skipped_non_it": skipped_non_it,
            "pruned": pruned,
        }
    except Exception as e:
        # In particular, remove the current uncommitted new job when Telegram
        # fails so it remains new and retryable on the next crawl.
        conn.rollback()
        store.finish_run(conn, run_id, status="error", pages=pages, found=found,
                         new_count=new, updated_count=upd, note=repr(e)[:300])
        raise
    finally:
        conn.close()


def run_all() -> list[dict]:
    return [run_source(s) for s in ("itviec", "topcv", "topdev")]


def run_companies(*, harvest: bool = True) -> dict:
    """Harvest thư mục công ty (3 nguồn) + enrich quy mô theo ngân sách.
    Chạy hằng ngày (systemd timer) — tách khỏi nhịp 15 phút của job crawl."""
    conn = store.connect(config.DB_PATH)
    companies_crawl.ensure_directory_tables(conn)
    run_id = store.start_run(conn, "companies")
    results: dict = {}
    try:
        if harvest:
            for src, fn in (("itviec", companies_crawl.harvest_itviec),
                            ("topcv", companies_crawl.harvest_topcv),
                            ("topdev", companies_crawl.harvest_topdev)):
                try:
                    results[src] = fn(conn)
                except Exception as e:
                    results[src] = {"error": repr(e)[:200]}
        try:
            # Row enrich bằng parser cũ (chỉ size) → cho fetch lại 1 lần để
            # bọc nốt ngành nghề/mô tả/job itviec; sentinel '' chống lặp
            conn.execute(
                """UPDATE company_directory SET enriched_at=NULL
                   WHERE detail_url IS NOT NULL AND industry IS NULL
                     AND enriched_at IS NOT NULL""")
            conn.commit()
            results["enrich"] = companies_crawl.enrich_missing(conn)
        except Exception as e:
            results["enrich"] = {"error": repr(e)[:200]}
        found = sum(
            r.get("companies", r.get("rows_touched", 0))
            for r in results.values() if isinstance(r, dict))
        store.finish_run(conn, run_id, status="ok", pages=0, found=found,
                         new_count=0, updated_count=0,
                         note=json.dumps(results, ensure_ascii=False)[:280])
        return results
    except Exception as e:
        conn.rollback()
        store.finish_run(conn, run_id, status="error", pages=0, found=0,
                         new_count=0, updated_count=0, note=repr(e)[:300])
        raise
    finally:
        conn.close()
