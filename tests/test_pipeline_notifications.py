from pathlib import Path

from job_crawler import pipeline


class RecordingNotifier:
    def __init__(self):
        self.jobs = []

    def send_job(self, job):
        self.jobs.append(job)
        return {"message_id": len(self.jobs)}


def _job(source_id="new-1"):
    return {
        "source": "itviec",
        "source_id": source_id,
        "title": "Data Engineer",
        "company": "Example",
        "url": "https://example.com/job",
        "city": "Hồ Chí Minh",
        "is_it": 1,
    }


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
