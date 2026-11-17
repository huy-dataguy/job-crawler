"""Telegram notifications for newly discovered jobs.

The notifier deliberately uses Telegram's small HTTP Bot API directly.  A job
is sent before its SQLite insert is committed; if Telegram rejects the
message, the insert can be rolled back and the next crawl will retry it.
"""
from __future__ import annotations

import html
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramError(RuntimeError):
    """A redacted Telegram API failure (never contains the bot token)."""


def _text(value: object, fallback: str = "Chưa rõ") -> str:
    value = str(value or "").strip()
    return html.escape(value if value else fallback)


def _list_text(value: object) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = value
    else:
        parsed = value
    if isinstance(parsed, list):
        return ", ".join(str(item) for item in parsed if item)
    return str(parsed)


def format_job(job: dict) -> str:
    """Render one canonical job as Telegram-safe HTML."""
    source = _text(str(job.get("source") or "job").upper())
    lines = [
        f"🚨 <b>JOB MỚI · {source}</b>",
        "",
        f"<b>{_text(job.get('title'))}</b>",
        f"🏢 {_text(job.get('company'))}",
        f"📍 {_text(job.get('city'))}",
        f"💰 {_text(job.get('salary'), 'Không công khai')}",
        f"🧭 {_text(job.get('experience') or job.get('level'))}",
    ]

    skills = _list_text(job.get("skills") or job.get("tags"))
    if skills:
        lines.append(f"🛠 {_text(skills)}")
    # Điểm khớp profile CV (relevance.py) + các term làm nên điểm
    rel = job.get("relevance")
    if rel is not None:
        matched = _list_text(job.get("matched"))
        tail = f" — {_text(matched)}" if matched else ""
        lines.append(f"🎯 Khớp profile: {int(rel)}%{tail}")
    if job.get("posted_text"):
        lines.append(f"🕒 {_text(job.get('posted_text'))}")

    url = str(job.get("url") or "").strip()
    if url.startswith(("https://", "http://")):
        lines.extend(["", f'<a href="{html.escape(url, quote=True)}">Xem và ứng tuyển →</a>'])

    # Individual canonical fields are short in this project.  Keep a hard
    # safety margin below Telegram's 4096-character sendMessage limit.
    message = "\n".join(lines)
    if len(message) > 3900:
        message = message[:3890] + "…"
    return message


def format_pipeline_alert(source: str, exc: BaseException, *, stage: str = "crawl",
                          run_id: int | None = None, pages: int = 0,
                          found: int = 0, new_count: int = 0) -> str:
    """Render a pipeline failure/crash alert without leaking secrets."""
    when = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S %Z")
    crashed = isinstance(exc, (SystemExit, KeyboardInterrupt))
    title = "PIPELINE DỪNG" if crashed else "PIPELINE LỖI"
    lines = [
        f"🛑 <b>{title} · {_text(source.upper())}</b>",
        "",
        f"Bước: <b>{_text(stage)}</b>",
        f"Lỗi: <code>{_text(type(exc).__name__)}</code> — {_text(str(exc)[:400], 'không có thông điệp')}",
    ]
    if run_id is not None:
        lines.append(f"Run: #{int(run_id)}")
    if pages or found or new_count:
        lines.append(f"Tiến độ: {int(pages)} trang · {int(found)} job · {int(new_count)} mới")
    lines.extend(["", f"🕒 {_text(when)}"])
    return "\n".join(lines)[:3900]


def format_health_issues(issues: list[dict], *, recovered: bool = False) -> str:
    """Render the watchdog result. One message for all unhealthy sources."""
    when = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S %Z")
    if recovered:
        return ("✅ <b>Job Crawler đã hồi phục</b>\n\n"
                "Tất cả pipeline nguồn đã có lượt chạy thành công gần đây.\n"
                f"🕒 {_text(when)}")
    lines = ["⚠️ <b>Pipeline cần kiểm tra</b>", ""]
    for issue in issues[:12]:
        reason = issue.get("reason") or "unknown"
        age = issue.get("age_minutes")
        tail = f" · {int(age)} phút" if age is not None else ""
        lines.append(f"• <b>{_text(str(issue.get('source') or '?').upper())}</b>: "
                     f"{_text(reason)}{tail}")
    lines.extend(["", "Mở Windmill → Runs để xem log từng pipeline.", f"🕒 {_text(when)}"])
    return "\n".join(lines)[:3900]


@dataclass
class TelegramNotifier:
    token: str
    chat_id: str
    timeout_seconds: float = 15.0
    min_interval_seconds: float = 1.05
    max_attempts: int = 3
    _last_sent_at: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _post(self, text: str, *, sleep: Callable[[float], None] = time.sleep) -> dict:
        if not self.enabled:
            raise TelegramError("Telegram chưa được cấu hình")

        elapsed = time.monotonic() - self._last_sent_at
        if self._last_sent_at and elapsed < self.min_interval_seconds:
            sleep(self.min_interval_seconds - elapsed)

        payload = json.dumps(
            {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            }
        ).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        last_error = "unknown error"
        for attempt in range(1, self.max_attempts + 1):
            retry_after = 0.0
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    result = json.loads(response.read().decode("utf-8"))
                if result.get("ok"):
                    self._last_sent_at = time.monotonic()
                    return result["result"]
                last_error = str(result.get("description") or "Telegram API rejected the message")
                retry_after = float((result.get("parameters") or {}).get("retry_after") or 0)
            except HTTPError as exc:
                # HTTPError's default repr contains the request URL, including
                # the secret token, so only retain status and Telegram's body.
                last_error = f"HTTP {exc.code}"
                try:
                    body = json.loads(exc.read().decode("utf-8"))
                    last_error = str(body.get("description") or last_error)
                    retry_after = float((body.get("parameters") or {}).get("retry_after") or 0)
                except (ValueError, TypeError, UnicodeDecodeError):
                    pass
                if exc.code < 500 and exc.code != 429:
                    break
            except (URLError, TimeoutError, OSError) as exc:
                last_error = type(exc).__name__

            if attempt < self.max_attempts:
                sleep(max(retry_after, min(2 ** (attempt - 1), 4)))

        raise TelegramError(f"Gửi Telegram thất bại sau {self.max_attempts} lần: {last_error}")

    def send_job(self, job: dict) -> dict:
        return self._post(format_job(job))

    def send_pipeline_alert(self, source: str, exc: BaseException, **kw) -> dict:
        return self._post(format_pipeline_alert(source, exc, **kw))

    def send_health_issues(self, issues: list[dict], *, recovered: bool = False) -> dict:
        return self._post(format_health_issues(issues, recovered=recovered))

    def send_test(self) -> dict:
        now = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S %Z")
        return self._post(
            "✅ <b>Job Crawler đã kết nối Telegram</b>\n\n"
            "Từ bây giờ, job mới từ ITviec, TopCV và TopDev sẽ được gửi vào đây.\n"
            f"🕒 {_text(now)}"
        )
