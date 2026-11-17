from datetime import datetime, timedelta
from pathlib import Path

from job_crawler import pipeline, store


class RecordingAlert:
    def __init__(self):
        self.errors = []
        self.health = []

    def send_pipeline_alert(self, source, exc, **kw):
        self.errors.append((source, exc, kw))
        return {"ok": True}

    def send_health_issues(self, issues, *, recovered=False):
        self.health.append((issues, recovered))
        return {"ok": True}


class FailingAlert(RecordingAlert):
    def send_health_issues(self, issues, *, recovered=False):
        raise RuntimeError("telegram 502")


def _db(tmp_path: Path) -> Path:
    return tmp_path / "jobs.db"


def _insert_run(db: Path, *, source: str, status: str, finished_at: str | None,
                started_at: str | None = None) -> None:
    conn = store.connect(db)
    now = started_at or finished_at or store.now_iso()
    cur = conn.execute(
        "INSERT INTO crawl_runs (source, started_at, finished_at, status)"
        " VALUES (?,?,?,?)", (source, now, finished_at, status))
    conn.commit()
    conn.close()


def test_alert_failure_formats_source_and_stage():
    notifier = RecordingAlert()
    pipeline.alert_failure("topcv", RuntimeError("cloudflare challenge"),
                           stage="details", run_id=42, pages=2, found=10,
                           new_count=3, notifier=notifier)
    assert len(notifier.errors) == 1
    source, exc, kw = notifier.errors[0]
    assert source == "topcv" and isinstance(exc, RuntimeError)
    assert kw["stage"] == "details" and kw["run_id"] == 42


def test_health_check_alerts_once_then_recovers(monkeypatch, tmp_path: Path):
    db = _db(tmp_path)
    monkeypatch.setattr(pipeline.config, "DB_PATH", db)
    now = datetime(2026, 11, 17, 12, tzinfo=datetime.now().astimezone().tzinfo)
    old = (now - timedelta(hours=30)).isoformat(timespec="seconds")
    fresh = now.isoformat(timespec="seconds")
    _insert_run(db, source="itviec", status="ok", finished_at=fresh)
    _insert_run(db, source="topcv", status="error", finished_at=old)
    _insert_run(db, source="topdev", status="ok", finished_at=old)
    _insert_run(db, source="companies", status="ok", finished_at=fresh)

    notifier = RecordingAlert()
    first = pipeline.health_check(now=now, notifier=notifier)
    assert first["ok"] is False
    assert {i["source"] for i in first["issues"]} == {"topcv", "topdev"}
    assert first["alerted"] is True and len(notifier.health) == 1

    second = pipeline.health_check(now=now, notifier=notifier)
    assert second["alerted"] is False and len(notifier.health) == 1

    conn = store.connect(db)
    conn.execute("UPDATE crawl_runs SET status='ok', finished_at=? WHERE finished_at=?",
                 (fresh, old))
    conn.commit()
    conn.close()
    recovered = pipeline.health_check(now=now, notifier=notifier)
    assert recovered["ok"] is True and recovered["recovered"] is True
    assert notifier.health[-1][1] is True


def test_health_check_flags_stuck_running_run(monkeypatch, tmp_path: Path):
    db = _db(tmp_path)
    monkeypatch.setattr(pipeline.config, "DB_PATH", db)
    now = datetime(2026, 11, 17, 12, tzinfo=datetime.now().astimezone().tzinfo)
    started = (now - timedelta(hours=3)).isoformat(timespec="seconds")
    _insert_run(db, source="topdev", status="running", finished_at=None,
                started_at=started)
    for source in ("itviec", "topcv", "companies"):
        _insert_run(db, source=source, status="ok",
                    finished_at=now.isoformat(timespec="seconds"))

    result = pipeline.health_check(now=now, notifier=RecordingAlert())
    assert result["ok"] is False
    assert result["issues"] == [{"source": "topdev", "reason": "stuck_running",
                                 "age_minutes": 180.0}]


def test_health_failed_alert_is_retried(monkeypatch, tmp_path: Path):
    db = _db(tmp_path)
    monkeypatch.setattr(pipeline.config, "DB_PATH", db)
    now = datetime(2026, 11, 17, 12, tzinfo=datetime.now().astimezone().tzinfo)
    fresh = now.isoformat(timespec="seconds")
    old = (now - timedelta(hours=30)).isoformat(timespec="seconds")
    _insert_run(db, source="itviec", status="ok", finished_at=fresh)
    _insert_run(db, source="topcv", status="error", finished_at=old)
    _insert_run(db, source="topdev", status="ok", finished_at=fresh)
    _insert_run(db, source="companies", status="ok", finished_at=fresh)

    bad = pipeline.health_check(now=now, notifier=FailingAlert())
    assert bad["alerted"] is False
    # Không được ghi dedupe khi gửi lỗi, nếu không cảnh báo bị nuốt vĩnh viễn.
    good = RecordingAlert()
    retried = pipeline.health_check(now=now, notifier=good)
    assert retried["alerted"] is True and len(good.health) == 1
