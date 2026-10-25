"""Immutable source evidence and an append-only acquisition manifest."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import config


def preserve(source: str, url: str, body: str, *, kind: str = "page", status: int = 200) -> str:
    now = datetime.now(timezone.utc)
    payload = body.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    folder = config.DATA_DIR / "raw" / source / now.date().isoformat() / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{digest}.html"
    try:
        with path.open("xb") as f:
            f.write(payload)
    except FileExistsError:
        pass
    manifest = config.DATA_DIR / "raw" / "manifest.jsonl"
    record = {"source": source, "url": url, "observed_at": now.isoformat(),
              "status": status, "kind": kind, "sha256": digest,
              "path": str(path.relative_to(config.DATA_DIR)), "bytes": len(payload)}
    with manifest.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
    return str(path.relative_to(config.DATA_DIR))
