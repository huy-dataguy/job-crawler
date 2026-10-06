"""CLI: python -m job_crawler [itviec|topcv|topdev|all]"""
from __future__ import annotations

import sys

from . import config, pipeline
from .notifier import TelegramNotifier


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target == "telegram-test":
        notifier = TelegramNotifier(
            config.TELEGRAM_BOT_TOKEN,
            config.TELEGRAM_CHAT_ID,
            timeout_seconds=config.TELEGRAM_TIMEOUT_SECONDS,
            min_interval_seconds=config.TELEGRAM_MIN_INTERVAL_SECONDS,
        )
        message = notifier.send_test()
        print({"ok": True, "message_id": message.get("message_id")})
    elif target == "companies":
        print(pipeline.run_companies())
    elif target == "enrich":
        print(pipeline.run_companies(harvest=False))
    elif target in pipeline.SOURCES:
        print(pipeline.run_source(target))
    else:
        for r in pipeline.run_all():
            print(r)


if __name__ == "__main__":
    main()
