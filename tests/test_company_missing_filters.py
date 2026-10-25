import asyncio
import csv
import io

import pytest
from fastapi import HTTPException

from dashboard import main as api
from job_crawler import companies_crawl as cc, store


@pytest.fixture
def company_profiles(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    monkeypatch.setattr(api, "DB_PATH", path)
    conn = store.connect(path)
    full = {"size_raw": "51-150 employees", "industry": "Software", "website": "https://example.com",
            "address": "Cầu Giấy, Hà Nội", "description": "Software company"}
    records = {
        "complete": full,
        "no-size": {**full, "size_raw": None},
        "no-industry": {**full, "industry": " \t\n "},
        "both": {**full, "size_raw": "N/A", "industry": "", "website": None, "description": "—"},
        "empty": {"size_raw": " \t\n ", "industry": None, "website": "", "address": None, "description": "   "},
    }
    for name, fields in records.items():
        cc.upsert_directory(conn, source="itviec", slug=name, name=name,
                            detail_url=f"https://itviec.com/companies/{name}")
        conn.execute("UPDATE company_directory SET " + ",".join(f"{field}=?" for field in fields) +
                     " WHERE slug=?", [*fields.values(), name])
    conn.commit()
    conn.close()


def names(**filters):
    return {c["company"] for c in api.api_companies(limit=50, offset=0, **filters)["companies"]}


def test_missing_fields_include_null_blank_and_placeholder_values(company_profiles):
    assert names(missing_fields="size") == {"no-size", "both", "empty"}
    assert names(missing_fields="industry") == {"no-industry", "both", "empty"}
    assert names(missing_fields="website") == {"both", "empty"}
    assert names(missing_fields="address") == {"empty"}
    assert names(missing_fields="description") == {"both", "empty"}
    stats = api.api_company_stats(missing_fields="size")
    assert stats["total"] == 3 and stats["enriched"] == 0
    assert stats["websites"] == 1 and stats["addresses"] == 2
    assert stats["missing_counts"]["size"] == 3 and stats["missing_counts"]["industry"] == 2


def test_missing_all_any_and_location_apply_to_list_stats_and_csv(company_profiles):
    assert names(missing_fields="size,industry") == {"both", "empty"}
    assert names(missing_fields="size,industry", missing_mode="any") == {"no-size", "no-industry", "both", "empty"}
    assert names(missing_fields=" size,industry,size ", city="Hà Nội") == {"both"}
    filters = {"missing_fields": "size,industry", "missing_mode": "all", "city": "Hà Nội"}
    stats = api.api_company_stats(**filters)
    assert stats["total"] == 1 and sum(r["n"] for r in stats["by_source"]) == 1

    async def read_csv():
        response = api.export_companies(**filters)
        return "".join([chunk async for chunk in response.body_iterator])
    rows = list(csv.DictReader(io.StringIO(asyncio.run(read_csv()).lstrip("\ufeff"))))
    assert [r["name"] for r in rows] == ["both"]
    empty = api.api_company_stats(q="no-such-profile", missing_fields="size")
    assert empty["total"] == 0 and set(empty["missing_counts"].values()) == {0}


@pytest.mark.parametrize("filters", [{"missing_fields": "size,bad_field"}, {"missing_mode": "invalid"}])
def test_invalid_missing_filters_are_rejected_before_export_streaming(filters):
    for endpoint in (api.api_companies, api.api_company_stats, api.export_companies):
        with pytest.raises(HTTPException) as error:
            endpoint(**filters)
        assert error.value.status_code == 422
