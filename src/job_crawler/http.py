"""Bounded, source-aware HTTP; errors never masquerade as empty listings.

Mọi request đi qua một token-bucket theo host: giãn cách tối thiểu + jitter để
không tạo burst pattern (nguyên nhân chính khiến TopCV trả Cloudflare challenge).
`fetch()` trả text, `fetch_json()` trả object — cùng retry/challenge/evidence.
"""
from __future__ import annotations

import json
import random
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

from curl_cffi import requests

from . import config, raw

CHALLENGE_MARKERS = (
    "Just a moment",
    "Attention Required",
    "cf-challenge",
    "Verify you are human",
)


class SourceError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None,
                 challenge: bool = False):
        super().__init__(message)
        self.status = status
        self.challenge = challenge


class _Bucket:
    """Host-scoped spacing: mỗi request cách request trước >= min_interval + jitter."""

    def __init__(self, min_interval: float, jitter: float):
        self.min_interval = max(0.0, min_interval)
        self.jitter = max(0.0, jitter)
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay > 0:
                time.sleep(delay)
            self._next = max(now, self._next) + self.min_interval + random.uniform(0, self.jitter)


_buckets: dict[str, _Bucket] = {}
_buckets_lock = threading.Lock()


def _bucket_for(source: str, url: str) -> _Bucket:
    host = urlparse(url).hostname or source
    key = f"{source}:{host}"
    with _buckets_lock:
        bucket = _buckets.get(key)
        if bucket is None:
            bucket = _Bucket(config.source_delay(source), config.SOURCE_DELAY_JITTER)
            _buckets[key] = bucket
        return bucket


def reset_limiters() -> None:
    """Test/CLI hook: bỏ mọi spacing state (giữa các run độc lập)."""
    with _buckets_lock:
        _buckets.clear()


def _is_challenge(response) -> bool:
    headers = getattr(response, "headers", None) or {}
    if str(headers.get("cf-mitigated") or "").lower() == "challenge":
        return True
    head = (response.text or "")[:15000]
    return any(marker in head for marker in CHALLENGE_MARKERS)


def request(source: str, url: str, *, session=None, kind: str = "page",
            timeout: float = 30, headers: dict | None = None,
            params: dict | None = None, suffix: str = "html"):
    """GET với retry/backoff/evidence; trả về response đã kiểm tra."""
    session = session or requests.Session(impersonate=config.IMPERSONATE)
    base_headers = {"Accept-Language": "vi,en;q=0.8"}
    if headers:
        base_headers.update(headers)
    last_error: Exception | None = None
    for attempt in range(5):
        _bucket_for(source, url).wait()
        try:
            response = session.get(url, timeout=timeout, headers=base_headers,
                                   params=params)
        except requests.RequestsError as exc:
            last_error = SourceError(f"{source}: transport {type(exc).__name__}")
            if attempt == 4:
                raise last_error from exc
            time.sleep(min(8, 2 ** attempt))
            continue
        text = response.text
        raw.preserve(source, url, text, kind=kind, status=response.status_code,
                     suffix=suffix)
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < 4:
                retry = response.headers.get("Retry-After", "")
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError):
                        delay = 2 ** (attempt + 1)
                if delay > 60:
                    raise SourceError(f"{source}: retry deferred {delay:.0f}s",
                                      status=response.status_code)
                time.sleep(max(1, delay))
                continue
        if response.status_code != 200:
            raise SourceError(f"{source}: HTTP {response.status_code} {url}",
                              status=response.status_code, challenge=_is_challenge(response))
        if _is_challenge(response):
            raise SourceError(f"{source}: challenge, source stopped", status=403,
                              challenge=True)
        return response
    raise last_error or SourceError(f"{source}: retries exhausted", status=429)


def fetch(source: str, url: str, *, session=None, kind: str = "page", timeout: float = 30,
          headers: dict | None = None, params: dict | None = None) -> str:
    return request(source, url, session=session, kind=kind, timeout=timeout,
                   headers=headers, params=params).text


def fetch_json(source: str, url: str, *, session=None, kind: str = "api",
               timeout: float = 30, headers: dict | None = None,
               params: dict | None = None) -> Any:
    response = request(source, url, session=session, kind=kind, timeout=timeout,
                       headers={**(headers or {}), "Accept": "application/json"},
                       params=params, suffix="json")
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise SourceError(f"{source}: invalid JSON from {url}") from exc


def warm_up(source: str, url: str, *, session=None, timeout: float = 30,
            headers: dict | None = None) -> bool:
    """Mở session bằng 1 trang thường để nhận cookie (cf_clearance/session).

    Lỗi không được làm chết run: crawler vẫn thử request thật ở bước sau.
    """
    try:
        request(source, url, session=session, kind="warmup", timeout=timeout,
                headers=headers)
        return True
    except SourceError:
        return False
