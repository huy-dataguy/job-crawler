"""Immutable source evidence and an append-only acquisition manifest.

Vòng đời (production): mọi response được lưu nén gzip (HTML/JSON ~7×), đánh
mã nội dung sha256 của payload GỐC nên trùng nội dung vẫn dedupe được; sau khi
dữ liệu đã vào SQLite, `sweep()` xoá file quá TTL theo env JC_RAW_RETENTION_HOURS
(và prune manifest) — raw chỉ là bằng chứng điều tra ngắn hạn, không phải lưu
trữ dài hạn.
"""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config


def preserve(source: str, url: str, body: str, *, kind: str = "page", status: int = 200) -> str:
    now = datetime.now(timezone.utc)
    payload = body.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    folder = config.DATA_DIR / "raw" / source / now.date().isoformat() / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{digest}.html.gz"
    try:
        with path.open("xb") as f:
            f.write(gzip.compress(payload, compresslevel=6))
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


def read(rel_path: str) -> str:
    """Đọc artifact theo relative path (tương thích file cũ .html và mới .html.gz)."""
    path = config.DATA_DIR / rel_path
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            return f.read()
    return path.read_text(encoding="utf-8", errors="replace")


def sweep(retention_hours: float | None = None) -> dict:
    """Xoá artifact quá TTL (giây mtime), prune manifest, dọn thư mục rỗng.

    retention_hours <= 0 = tắt sweep (giữ mọi thứ). Chạy sau mỗi lượt crawl —
    dữ liệu đã vào SQLite thì raw cũ không còn giá trị nào ngoài điều tra lỗi
    parser trong vài ngày đầu.
    """
    hours = config.RAW_RETENTION_HOURS if retention_hours is None else retention_hours
    raw_dir = config.DATA_DIR / "raw"
    manifest = raw_dir / "manifest.jsonl"
    if hours <= 0 or not raw_dir.is_dir():
        return {"removed": 0, "pruned_manifest": 0, "retention_hours": hours, "disabled": hours <= 0}
    cutoff = time.time() - hours * 3600
    removed = 0
    for p in list(raw_dir.rglob("*")):
        if not p.is_file() or p.name == "manifest.jsonl":
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    # Prune manifest: giữ đúng dòng còn file tương ứng. Lock EX cùng kiểu với
    # phía preserve (append) để không mất dòng khi crawl đang ghi song song.
    pruned = 0
    if manifest.exists():
        kept: list[str] = []
        with manifest.open("a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rel = json.loads(line).get("path", "")
                except json.JSONDecodeError:
                    pruned += 1
                    continue
                if (config.DATA_DIR / rel).exists():
                    kept.append(line)
                else:
                    pruned += 1
            if pruned:
                tmp = manifest.with_suffix(".jsonl.tmp")
                tmp.write_text("\n".join(kept) + ("\n" if kept else ""))
                tmp.replace(manifest)
            fcntl.flock(f, fcntl.LOCK_UN)
    # Thư mục rỗng sau xoá
    for d in sorted((p for p in raw_dir.rglob("*") if p.is_dir()), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    return {"removed": removed, "pruned_manifest": pruned, "retention_hours": hours}
