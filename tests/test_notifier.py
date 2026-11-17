import json

import pytest

from job_crawler.notifier import (
    TelegramError,
    TelegramNotifier,
    format_health_issues,
    format_job,
    format_pipeline_alert,
)


def test_format_job_escapes_source_data_and_keeps_link():
    message = format_job(
        {
            "source": "itviec",
            "title": "Data & AI <Lead>",
            "company": "A&B",
            "city": "Hồ Chí Minh",
            "salary": "$1,000",
            "experience": "2 năm",
            "skills": json.dumps(["Python", "SQL"]),
            "url": "https://example.com/jobs/1?a=1&b=2",
        }
    )

    assert "Data &amp; AI &lt;Lead&gt;" in message
    assert "A&amp;B" in message
    assert "Python, SQL" in message
    assert 'href="https://example.com/jobs/1?a=1&amp;b=2"' in message


def test_disabled_notifier_never_exposes_token():
    notifier = TelegramNotifier("", "")
    with pytest.raises(TelegramError, match="chưa được cấu hình"):
        notifier.send_test()


def test_pipeline_alert_escapes_error_and_has_context():
    message = format_pipeline_alert(
        "topcv", RuntimeError("challenge <403> & retry"), stage="details",
        run_id=9, pages=2, found=40, new_count=3)
    assert "PIPELINE LỖI" in message and "TOPCV" in message
    assert "challenge &lt;403&gt; &amp; retry" in message
    assert "details" in message and "#9" in message


def test_health_alert_lists_sources_and_recovery():
    issues = [{"source": "itviec", "reason": "stale", "age_minutes": 90},
              {"source": "topdev", "reason": "last_status=error", "age_minutes": 5}]
    message = format_health_issues(issues)
    assert "ITVIEC" in message and "stale" in message and "90 phút" in message
    assert "TOPDEV" in message
    assert "hồi phục" in format_health_issues([], recovered=True)
