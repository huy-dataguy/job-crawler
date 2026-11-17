"""Stable local/Windmill entrypoints, guarded by a shared advisory writer lock."""
from __future__ import annotations

import argparse
import fcntl
import json
import signal

from . import config, pipeline, store


def main() -> None:
    def stop(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, stop)
    parser = argparse.ArgumentParser(description="Continuous Vietnam IT jobs and company discovery")
    parser.add_argument("target", nargs="?", default="all",
                        choices=["all", *pipeline.SOURCES, "companies", "enrich", "recheck", "replay", "migrate", "verify", "health", "telegram-test", "raw-gc"])
    args = parser.parse_args()
    if args.target == "verify":
        from .verification import verify
        raise SystemExit(0 if verify()["ok"] else 1)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.target == "health":
        # Watchdog chạy độc lập: đọc crawl_runs, gửi Telegram một lần/sự cố.
        result = pipeline.health_check()
        print(json.dumps(result, ensure_ascii=False), flush=True)
        raise SystemExit(0 if result["ok"] else 1)
    if args.target == "raw-gc":  # chỉ file raw + flock manifest riêng — khỏi writer.lock
        from . import raw as _raw
        print(json.dumps(_raw.sweep(), ensure_ascii=False), flush=True)
        raise SystemExit(0)

    # Mỗi nguồn một lock riêng để 3 pipeline chạy song song được; SQLite WAL tự
    # serialize ghi. `all` vẫn dùng writer.lock toàn cục.
    def _lock_name(target: str) -> str:
        if target in pipeline.SOURCES:
            return f"source-{target}.lock"
        if target in ("companies", "enrich"):
            return "companies.lock"
        if target == "recheck":
            return "recheck.lock"
        return "writer.lock"

    with (config.DATA_DIR / _lock_name(args.target)).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status":"skipped", "reason":"another writer is running"}))
            # Bận lock = đã có writer khác làm việc này; không phải lỗi.
            # Exit 0 để Windmill/systemd không đánh dấu fail; nhịp sau tự chạy.
            raise SystemExit(0)
        if args.target == "migrate":
            from .migrations import migrate
            result = migrate(config.DB_PATH)
        elif args.target == "telegram-test":
            from .notifier import TelegramNotifier
            result = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID).send_test()
        elif args.target in ("companies", "enrich"):
            result = pipeline.run_companies(harvest=args.target == "companies")
        elif args.target == "recheck":
            from .details import verify_source
            conn = store.connect(config.DB_PATH)
            try:
                result = {source:verify_source(conn, source) for source in pipeline.SOURCES}
            finally:
                conn.close()
        elif args.target == "replay":
            from .replay import replay_jobs
            result = replay_jobs()
        elif args.target in pipeline.SOURCES:
            result = pipeline.run_source(args.target)
        else:
            result = pipeline.run_all()
        print(json.dumps(result, ensure_ascii=False), flush=True)
        failures = (any("error" in r for r in result) if isinstance(result,list)
                    else any(isinstance(r,dict) and (r.get("error") or r.get("subs_failed"))
                             for r in result.values()))
        if failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
