"""Contract tests: API/schema thật của 3 nguồn (fixture chụp từ production).

Fixture là bằng chứng: nếu site đổi shape, test này fail trước khi crawler ghi
dữ liệu rác vào DB.
"""
import json
from pathlib import Path

import pytest

from job_crawler import details, drift, http, itviec, topcv, topdev

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- TopDev JSON API -------------------------------------------------------

def test_topdev_list_contract_maps_every_supported_field():
    payload = _load("topdev_list.json")
    jobs = topdev.parse_listing(payload)
    assert len(jobs) == len(payload["data"])
    job = next(j for j in jobs if j["source_id"] == "2146167")
    assert job["source"] == "topdev"
    assert job["title"].startswith("DevOps Engineer")
    assert job["company"]
    assert job["url"].startswith("https://topdev.vn/")
    assert job["city"] == "Thành phố Hồ Chí Minh"
    assert job["experience"] == "4 năm" and job["exp_min"] == 4.0
    assert job["salary"] == "Thoả thuận" and job["salary_min"] is None
    assert job["posted_text"] == "4 days ago"
    assert job["posted_at"].startswith("2026-11-12")
    assert job["valid_through"].startswith("2026-12-12T23:59")
    assert job["level"] == "middle"  # "(Middle/Senior)" → ưu tiên middle


def test_topdev_salary_uses_unmasked_filter_values():
    payload = _load("topdev_list.json")
    job = next(j for j in topdev.parse_listing(payload) if j["source_id"] == "2146596")
    assert job["salary"] == "20 - 35 triệu"
    assert (job["salary_min"], job["salary_max"]) == (20.0, 35.0)


def test_topdev_parse_listing_dedupes_and_skips_broken_rows():
    payload = _load("topdev_list.json")
    rows = payload["data"]
    broken = {"id": None, "title": "", "company": {}}
    jobs = topdev.parse_listing({**payload, "data": rows + rows[:1] + [broken]})
    assert len(jobs) == len(rows)
    assert len({j["source_id"] for j in jobs}) == len(jobs)


def test_topdev_detail_contract(monkeypatch):
    detail_payload = _load("topdev_detail.json")
    monkeypatch.setattr(topdev, "_api", lambda *a, **k: detail_payload["data"])
    job = {"source_id": "2146596", "url": "https://topdev.vn/it-jobs/x-2146596",
           "company_url": "https://topdev.vn/companies/x-96338"}
    detail = topdev.fetch_detail(job)
    assert detail["status"] == "open"
    assert detail["description"]
    assert "requirements" in detail
    assert detail["valid_through"].startswith("2026-12-16")
    assert detail["company_url"] == job["company_url"]


def test_topdev_detail_marks_closed_when_expired(monkeypatch):
    data = dict(_load("topdev_detail.json")["data"])
    data["expires"] = {"date": "01-01-2020"}
    data["status_display"] = "Expired"
    monkeypatch.setattr(topdev, "_api", lambda *a, **k: data)
    detail = topdev.fetch_detail({"source_id": "1", "url": "https://topdev.vn/it-jobs/x-1"})
    assert detail["status"] == "closed"
    assert detail["status_reason"] == "api_status_display"


def test_topdev_crawl_stops_when_page_has_nothing_new(monkeypatch):
    payload = _load("topdev_list.json")
    calls = []

    def fake_api(path, **params):
        calls.append(params.get("page"))
        return payload

    monkeypatch.setattr(topdev, "_warm", lambda: None)
    monkeypatch.setattr(topdev, "_api", fake_api)
    jobs, pages = topdev.crawl(max_pages=4)
    assert pages == 2 and calls == [1, 2]
    assert len(jobs) == len(payload["data"])


# --- JSON-LD discovery (lớp dự phòng khi CSS đổi) ---------------------------

def test_itviec_item_list_discovery():
    html = (FIXTURES / "itviec_item_list.html").read_text(encoding="utf-8")
    pairs = itviec.parse_item_list(html)
    assert len(pairs) == 3
    assert all(url.startswith("https://itviec.com/it-jobs/") for url, _ in pairs)


def test_itviec_falls_back_to_item_list_when_cards_are_gone():
    html = (FIXTURES / "itviec_item_list.html").read_text(encoding="utf-8")
    jobs = itviec.parse_listing(html)
    assert len(jobs) == 3
    assert all(j["_fallback"] and j["source_id"] and j["title"] for j in jobs)
    assert jobs[0]["url"].startswith("https://itviec.com/it-jobs/")


def test_topcv_item_list_is_nested_in_collection_page():
    html = (FIXTURES / "topcv_item_list.html").read_text(encoding="utf-8")
    pairs = topcv.parse_item_list(html)
    assert len(pairs) == 3
    assert all(topcv._url_to_id(url).isdigit() for url, _ in pairs)


# --- Drift detection -------------------------------------------------------

def test_drift_raises_when_essentials_are_missing():
    with pytest.raises(drift.SchemaDrift):
        drift.ensure("topcv", [{"title": "", "url": "x"}] * 4)


def test_drift_passes_on_healthy_listing():
    jobs = [{"title": "DevOps", "url": "https://x", "company": "A"}] * 4
    assert drift.ensure("topdev", jobs) == 1.0


# --- Transport -------------------------------------------------------------

class _Resp:
    def __init__(self, text, status=200, headers=None):
        self.text = text
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return json.loads(self.text)


def test_challenge_header_is_detected():
    assert http._is_challenge(_Resp("ok", headers={"cf-mitigated": "challenge"}))
    assert http._is_challenge(_Resp("<title>Just a moment...</title>"))
    assert not http._is_challenge(_Resp("<html>jobs</html>"))


def test_fetch_json_preserves_body_and_decodes(monkeypatch, tmp_path):
    monkeypatch.setattr(http, "request",
                        lambda *a, **k: _Resp(json.dumps({"data": [1]})))
    assert http.fetch_json("topdev", "https://api.topdev.vn/td/v2/jobs") == {"data": [1]}


def test_detail_adapter_hook_points_at_topdev_api():
    assert details._detail_adapter("topdev") is topdev.fetch_detail
    assert details._detail_adapter("itviec") is None
