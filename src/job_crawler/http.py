"""Bounded, source-aware HTTP; errors never masquerade as empty listings."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from curl_cffi import requests

from . import raw


class SourceError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def fetch(source: str, url: str, *, session=None, kind: str = "page", timeout: float = 30,
          headers: dict | None = None) -> str:
    session = session or requests.Session(impersonate="chrome124")
    base_headers = {"Accept-Language": "vi,en;q=0.8"}
    if headers:
        base_headers.update(headers)
    for attempt in range(3):
        try:
            response = session.get(url, timeout=timeout,
                                   headers=base_headers)
        except requests.RequestsError as exc:
            if attempt == 2:
                raise SourceError(f"{source}: transport {type(exc).__name__}") from exc
            time.sleep(2 ** attempt)
            continue
        text = response.text
        raw.preserve(source, url, text, kind=kind, status=response.status_code)
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < 2:
                retry = response.headers.get("Retry-After", "")
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError):
                        delay = 2 ** (attempt + 1)
                if delay > 60:
                    raise SourceError(f"{source}: retry deferred {delay:.0f}s", status=response.status_code)
                time.sleep(max(1, delay))
                continue
        if response.status_code != 200:
            raise SourceError(f"{source}: HTTP {response.status_code} {url}", status=response.status_code)
        if "Just a moment" in text[:15000] or "Attention Required" in text[:15000]:
            raise SourceError(f"{source}: challenge, source stopped", status=403)
        return text
    raise SourceError(f"{source}: retries exhausted", status=429)
