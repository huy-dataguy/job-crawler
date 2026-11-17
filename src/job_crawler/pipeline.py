"""Source discovery, detail verification, independent company enrichment and run manifests."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime

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


def _alert_notifier() -> TelegramNotifier | None:
    """Best-effort notifier for failures — never let alerting break the run."""
    try:
        return _notifier()
    except TelegramError:
        return None


def _maybe_raw_gc() -> dict:
    """raw.sweep() tốn I/O quét cả cây raw — chỉ chạy mỗi RAW_SWEEP_MINUTES."""
    marker = config.DATA_DIR / "raw" / ".last-sweep"
    interval = max(0.0, config.RAW_SWEEP_MINUTES) * 60
    try:
        if interval and marker.exists() and time.time() - marker.stat().st_mtime < interval:
            return {"skipped": True, "reason": "throttled"}
    except OSError:
        pass
    result = raw.sweep()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass
    return result


def alert_failure(source: str, exc: BaseException, *, stage: str = "crawl",
                  run_id: int | None = None, pages: int = 0, found: int = 0,
                  new_count: int = 0,
                  notifier: TelegramNotifier | None = None) -> bool:
    """Send one pipeline failure/crash alert. Returns False if not configured."""
    target = notifier or _alert_notifier()
    if target is None:
        return False
    try:
        target.send_pipeline_alert(source, exc, stage=stage, run_id=run_id,
                                   pages=pages, found=found, new_count=new_count)
        return True
    except Exception:
        return False


def run_source(name: str, *, notifier: TelegramNotifier | None = None,
               max_pages: int | None = None,
               detail_budget: int | None = None) -> dict:
    conn = store.connect(config.DB_PATH)
    companies_crawl.ensure_directory_tables(conn)
    run_id = store.start_run(conn, name)
    pages = found = new = upd = notified = skipped_non_it = 0
    seen_slugs: set[str] = set()
    stage = "listing"
    run_notifier = notifier
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
        run_notifier = notifier
        stage = "store"
        # Có notifier thì commit từng job (Telegram trước commit để retry được);
        # không notifier (deep) thì gom lô để giảm fsync rất nhiều.
        commit_every = 1 if notifier is not None else max(1, config.COMMIT_BATCH)
        pending = 0
        for j in jobs:
            relevance.annotate(j)  # điểm khớp profile CV (0-100 + matched)
            outcome = store.upsert_job(conn, j)
            if outcome == "new":
                # Telegram acknowledgement precedes the insert commit.  On a
                # delivery error this job remains unseen and is retried later.
                if (notifier is not None
                        and (j["relevance"] >= config.NOTIFY_MIN_RELEVANCE
                             or config.NOTIFY_MIN_RELEVANCE <= 0)):
                    stage = "notify"
                    notifier.send_job(j)
                    stage = "store"
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
            pending += 1
            if pending >= commit_every:
                conn.commit()
                pending = 0
        conn.commit()
        stage = "details"
        detail_result = details.verify_source(conn, name, budget=detail_budget)
        stage = "companies"
        companies_crawl.classify_profiles(conn, source=name)
        companies_crawl.refresh_hiring_flags(conn, name, seen_slugs)
        conn.commit()
        pruned = 0  # retain history and marks; age/status are serving filters
        store.finish_run(conn, run_id, status="partial" if detail_result["errors"] else "ok", pages=pages, found=found,
                         new_count=new, updated_count=upd,
                         note=f"telegram_notified={notified} "
                              f"skipped_non_it={skipped_non_it} details={json.dumps(detail_result)}")
        stage = "raw-gc"
        raw_gc = _maybe_raw_gc()
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
        # Tránh gửi 2 lần khi chính bước gửi Telegram là nguyên nhân lỗi.
        if stage != "notify":
            alert_failure(name, e, stage=stage, run_id=run_id, pages=pages,
                          found=found, new_count=new, notifier=run_notifier)
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
        alert_failure("companies", e, stage="companies", run_id=run_id)
        raise
    finally:
        conn.close()


def health_check(*, now: datetime | None = None,
                 notifier: TelegramNotifier | None = None) -> dict:
    """Watchdog: phát hiện pipeline chết/treo/lỗi và báo Telegram một lần.

    Chạy độc lập (CLI `health`/Windmill) nên vẫn bắt được trường hợp process bị
    kill mà không kịp gửi alert. Dùng `crawl_runs` làm nguồn sự thật.
    """
    now = now or datetime.now().astimezone()
    conn = store.connect(config.DB_PATH)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS harvest_meta ("
                     "key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        issues: list[dict] = []
        for source in (*SOURCES, "companies"):
            limit = (config.COMPANIES_STALE_MINUTES if source == "companies"
                     else config.PIPELINE_STALE_MINUTES)
            row = conn.execute(
                "SELECT id,status,started_at,finished_at FROM crawl_runs"
                " WHERE source=? ORDER BY id DESC LIMIT 1", (source,)).fetchone()
            if row is None:
                issues.append({"source": source, "reason": "never_run"})
                continue
            if row["finished_at"] is None:
                age = (now - datetime.fromisoformat(row["started_at"])).total_seconds() / 60
                if age > config.RUNNING_STALE_MINUTES:
                    issues.append({"source": source, "reason": "stuck_running",
                                   "age_minutes": age})
                continue
            age = (now - datetime.fromisoformat(row["finished_at"])).total_seconds() / 60
            if row["status"] in ("error", "interrupted"):
                issues.append({"source": source,
                               "reason": f"last_status={row['status']}",
                               "age_minutes": age})
            elif age > limit:
                issues.append({"source": source, "reason": "stale", "age_minutes": age})

        signature = json.dumps(sorted((i["source"], i["reason"]) for i in issues))
        prev = conn.execute("SELECT value FROM harvest_meta WHERE key='health:last_alert'").fetchone()
        previous = prev[0] if prev else ""
        alerted = recovered = False
        if issues and signature != previous:
            target = notifier or _alert_notifier()
            if target is not None:
                try:
                    target.send_health_issues(issues)
                    alerted = True
                except Exception:
                    pass
            # Chỉ ghi dedupe khi đã gửi được — lần chạy không có Telegram
            # (hoặc gửi lỗi) không được phép nuốt cảnh báo của lần sau.
            if alerted:
                conn.execute("INSERT INTO harvest_meta(key,value) VALUES ('health:last_alert',?)"
                             " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (signature,))
                conn.commit()
        elif not issues and previous:
            target = notifier or _alert_notifier()
            if target is not None:
                try:
                    target.send_health_issues([], recovered=True)
                    recovered = True
                except Exception:
                    pass
            if recovered:
                conn.execute("DELETE FROM harvest_meta WHERE key='health:last_alert'")
                conn.commit()
        return {"ok": not issues, "issues": issues,
                "alerted": alerted, "recovered": recovered}
    finally:
        conn.close()
