from pathlib import Path

from job_crawler import pipeline


class RecordingNotifier:
    def __init__(self):
        self.jobs = []

    def send_job(self, job):
        self.jobs.append(job)
        return {"message_id": len(self.jobs)}


def _job(source_id="new-1", **kw):
    base = {
        "source": "itviec",
        "source_id": source_id,
        "title": "Junior Data Engineer",
        "company": "Example",
        "url": "https://example.com/job",
        "city": "Hồ Chí Minh",
        "is_it": 1,
        "category": "Data Engineer",
        "tags": '["Python","SQL","Airflow"]',
        "skills": '["Python","SQL","Data Engineer"]',
        "level": "junior",
        "exp_min": 1.0,
    }
    base.update(kw)
    return base


def test_new_job_is_notified_once(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr(pipeline.config, "DB_PATH", db_path)
    monkeypatch.setattr(pipeline.SOURCES["itviec"], "crawl", lambda: ([_job()], 1))
    notifier = RecordingNotifier()

    first = pipeline.run_source("itviec", notifier=notifier)
    second = pipeline.run_source("itviec", notifier=notifier)

    assert first["new"] == 1
    assert first["notified"] == 1
    assert second["new"] == 0
    assert second["notified"] == 0
    assert len(notifier.jobs) == 1


def test_failed_notification_keeps_job_retryable(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr(pipeline.config, "DB_PATH", db_path)
    monkeypatch.setattr(pipeline.SOURCES["itviec"], "crawl", lambda: ([_job()], 1))

    class FailingNotifier:
        def send_job(self, job):
            raise RuntimeError("telegram unavailable")

    try:
        pipeline.run_source("itviec", notifier=FailingNotifier())
    except RuntimeError:
        pass

    retry_notifier = RecordingNotifier()
    result = pipeline.run_source("itviec", notifier=retry_notifier)
    assert result["new"] == 1
    assert result["notified"] == 1


def test_non_it_job_is_skipped_not_stored(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr(pipeline.config, "DB_PATH", db_path)
    jobs = [_job("it-1"), _job("sale-1", title="Nhân viên bán hàng phần mềm",
                               is_it=0, category="", tags="[]", skills="[]")]
    monkeypatch.setattr(pipeline.SOURCES["itviec"], "crawl", lambda: (jobs, 1))

    result = pipeline.run_source("itviec", notifier=RecordingNotifier())

    assert result["skipped_non_it"] == 1
    assert result["new"] == 1
    import sqlite3
    conn = sqlite3.connect(db_path)
    ids = {r[0] for r in conn.execute("SELECT source_id FROM jobs")}
    conn.close()
    assert ids == {"it-1"}


def test_low_relevance_job_stored_but_not_notified(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr(pipeline.config, "DB_PATH", db_path)
    low = _job("java-1", title="Senior Java Developer (Spring)",
               category="Backend Developer",
               tags='["Java","Spring"]', skills='["Java","Spring"]',
               level="senior", exp_min=3.0)
    monkeypatch.setattr(pipeline.SOURCES["itviec"], "crawl", lambda: ([low], 1))
    notifier = RecordingNotifier()

    result = pipeline.run_source("itviec", notifier=notifier)

    assert result["new"] == 1        # vẫn lưu DB
    assert result["notified"] == 0   # nhưng không push Telegram
    assert notifier.jobs == []
