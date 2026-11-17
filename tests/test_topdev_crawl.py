from job_crawler import topdev


def _row(job_id: int) -> dict:
    return {
        "id": job_id,
        "title": f"Data Engineer {job_id}",
        "detail_url": f"https://topdev.vn/detail-jobs/data-engineer-{job_id}",
        "company": {"display_name": "Example Co"},
        "addresses": {},
    }


def _fake_api(pages: dict[int, list[dict]], last_page: int):
    calls = []

    def fake(path, **params):
        calls.append(params["page"])
        return pages.get(params["page"], []), {"total": 3, "last_page": last_page}

    return fake, calls


def test_full_sweep_reads_to_last_page_even_when_ids_repeat(monkeypatch):
    monkeypatch.setattr(topdev, "_warm", lambda: None)
    fake, calls = _fake_api({1: [_row(1)], 2: [_row(1)], 3: [_row(1)]}, last_page=3)
    monkeypatch.setattr(topdev, "_api_page", fake)

    jobs, pages = topdev.crawl(max_pages=0)

    assert [j["source_id"] for j in jobs] == ["1"]
    assert pages == 3 and calls == [1, 2, 3]


def test_incremental_stops_when_whole_page_is_known(monkeypatch):
    monkeypatch.setattr(topdev, "_warm", lambda: None)
    fake, calls = _fake_api({1: [_row(1)], 2: [_row(1)], 3: [_row(2)]}, last_page=10)
    monkeypatch.setattr(topdev, "_api_page", fake)

    jobs, pages = topdev.crawl(max_pages=5)

    assert [j["source_id"] for j in jobs] == ["1"]
    assert pages == 2 and calls == [1, 2]


def test_page_cap_limits_quick_run(monkeypatch):
    monkeypatch.setattr(topdev, "_warm", lambda: None)
    fake, calls = _fake_api({1: [_row(1)], 2: [_row(2)], 3: [_row(3)]}, last_page=10)
    monkeypatch.setattr(topdev, "_api_page", fake)

    jobs, pages = topdev.crawl(max_pages=2)

    assert {j["source_id"] for j in jobs} == {"1", "2"}
    assert pages == 2 and calls == [1, 2]


def test_full_sweep_stops_at_first_empty_page(monkeypatch):
    monkeypatch.setattr(topdev, "_warm", lambda: None)
    # meta.last_page là toàn quốc → region 79 hết job ở trang 2.
    fake, calls = _fake_api({1: [_row(1)], 2: [_row(2)]}, last_page=9)
    monkeypatch.setattr(topdev, "_api_page", fake)

    jobs, pages = topdev.crawl(max_pages=0)

    assert {j["source_id"] for j in jobs} == {"1", "2"}
    assert pages == 2 and calls == [1, 2, 3]
