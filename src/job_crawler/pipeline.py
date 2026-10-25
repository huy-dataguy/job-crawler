"""Source discovery, detail verification, independent company enrichment and run manifests."""
from __future__ import annotations

import json
import sqlite3

from . import companies_crawl, config, itviec, raw, relevance, store, topcv, topdev
from .notifier import TelegramError, TelegramNotifier
from . import details

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


def run_source(name: str, *, notifier: TelegramNotifier | None = None,
               max_pages: int | None = None) -> dict:
    conn = store.connect(config.DB_PATH)
    companies_crawl.ensure_directory_tables(conn)
    run_id = store.start_run(conn, name)
    pages = found = new = upd = notified = skipped_non_it = 0
    seen_slugs: set[str] = set()
    try:
        if max_pages is None:
            raw_jobs, pages = SOURCES[name].crawl()
        else:
            raw_jobs, pages = SOURCES[name].crawl(max_pages=max_pages)
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
        conn.commit()
        detail_result = details.verify_source(conn, name)
        companies_crawl.classify_profiles(conn, source=name)
        companies_crawl.refresh_hiring_flags(conn, name, seen_slugs)
        conn.commit()
        pruned = 0  # retain history and marks; age/status are serving filters
        store.finish_run(conn, run_id, status="partial" if detail_result["errors"] else "ok", pages=pages, found=found,
                         new_count=new, updated_count=upd,
                         note=f"telegram_notified={notified} "
                              f"skipped_non_it={skipped_non_it} details={json.dumps(detail_result)}")
        raw_gc = raw.sweep()
        return {
            "source": name,
            "found": found,
            "pages": pages,
            "new": new,
            "updated": upd,
            "notified": notified,
            "skipped_non_it": skipped_non_it,
            "pruned": pruned,
            "raw_gc": raw_gc,
            "details": detail_result,
        }
    except BaseException as e:
        # In particular, remove the current uncommitted new job when Telegram
        # fails so it remains new and retryable on the next crawl.
        conn.rollback()
        store.finish_run(conn, run_id, status="interrupted" if isinstance(e, (SystemExit, KeyboardInterrupt)) else "error", pages=pages, found=found,
                         new_count=new, updated_count=upd, note=repr(e)[:300])
        raise
    finally:
        conn.close()


def run_all() -> list[dict]:
    results = []
    for source in ("itviec", "topcv", "topdev"):
        try:
            result = run_source(source)
        except Exception as exc:
            result = {"source": source, "error": str(exc)[:300]}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return results


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
            results["enrich"] = companies_crawl.enrich_missing(conn)
        except Exception as e:
            results["enrich"] = {"error": repr(e)[:200]}
        found = sum(
            r.get("companies", r.get("rows_touched", 0))
            for r in results.values() if isinstance(r, dict))
        companies_crawl.classify_profiles(conn)
        for source in SOURCES:
            companies_crawl.refresh_hiring_flags(conn, source, set())
        partial = any(isinstance(r, dict) and (r.get("error") or r.get("fetch_errors") or r.get("subs_failed"))
                      for r in results.values())
        store.finish_run(conn, run_id, status="partial" if partial else "ok", pages=0, found=found,
                         new_count=0, updated_count=0,
                         note=json.dumps(results, ensure_ascii=False)[:280])
        return results
    except BaseException as e:
        conn.rollback()
        store.finish_run(conn, run_id, status="interrupted" if isinstance(e, (SystemExit, KeyboardInterrupt)) else "error", pages=0, found=0,
                         new_count=0, updated_count=0, note=repr(e)[:300])
        raise
    finally:
        conn.close()
