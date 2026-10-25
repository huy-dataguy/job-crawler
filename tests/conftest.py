import pytest

from job_crawler import config


@pytest.fixture(autouse=True)
def isolate_runtime(monkeypatch, tmp_path):
    # Tests must not acquire live pages or append to the owner's evidence lake.
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "JOB_DETAIL_BUDGET", 0)
    monkeypatch.setattr(config, "TELEGRAM_ENABLED", False)
