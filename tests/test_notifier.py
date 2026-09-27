import json

import pytest

from job_crawler.notifier import TelegramError, TelegramNotifier, format_job


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
