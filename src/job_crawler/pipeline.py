"""Pipeline: crawl các nguồn → làm sạch → chấm điểm liên quan → upsert SQLite
→ prune data cũ → ghi run manifest. DB chỉ giữ job IT mới + sạch, không raw."""
from __future__ import annotations

import sqlite3

from . import config, itviec, relevance, store, topcv, topdev
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
    run_id = store.start_run(conn, name)
    pages = found = new = upd = notified = skipped_non_it = 0
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
            # Commit per canonical job.  If a later Telegram call fails, jobs
            # already acknowledged are durable and will not be sent twice.
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
