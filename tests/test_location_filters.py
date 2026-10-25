import asyncio
import csv
from datetime import datetime, timedelta
import io
import json

from dashboard import main as api
from job_crawler import companies_crawl as cc, locations, store
from test_continuous import job


def test_province_aliases_multicity_and_address_street_names():
    assert locations.matches("Ho Chi Minh - Ha Noi", "Hà Nội")
    assert locations.matches("Hồ Chí Minh (mới)", "TP.HCM")
    assert locations.matches("Da Nang - Ho Chi Minh", "Đà Nẵng")
    assert not locations.matches("Bắc Giang", "Bắc Ninh")
    address = "123 Xa lộ Hà Nội, TP. Hồ Chí Minh"
    assert locations.matches(address, "Hồ Chí Minh", 1)
    assert not locations.matches(address, "Hà Nội", 1)
    assert locations.matches(address + "\nCầu Giấy, Hanoi", "Hà Nội", 1)
    assert locations.matches(None, locations.UNKNOWN, 1)


def test_province_applies_to_jobs_charts_companies_stats_and_export(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    monkeypatch.setattr(api, "DB_PATH", path)
    conn = store.connect(path)
    now = datetime.now().astimezone()
    cities = {"a": "Ha Noi", "b": "Hà Nội", "c": "TP.HCM", "d": "Da Nang - Ha Noi"}
    addresses = {"b": "Quận 1, TP.HCM", "c": "Cầu Giấy, Hà Nội"}
    for ident in ("a", "b", "c", "d", "unknown"):
        url = f"https://itviec.com/companies/{ident}"
        cc.upsert_directory(conn, source="itviec", slug=ident, name=ident, detail_url=None if ident == "unknown" else url)
        if ident in addresses:
            conn.execute("UPDATE company_directory SET address=? WHERE slug=?", (addresses[ident], ident))
        if ident in cities:
            store.upsert_job(conn, job(source_id=ident, company=ident, company_url=url, city=cities[ident], category="Data Engineer"))
    conn.execute("UPDATE jobs SET status='open', date_source='structured', detail_checked_at=?, posted_at=?",
                 (now.isoformat(), (now - timedelta(days=1)).isoformat()))
    conn.execute("UPDATE jobs SET company_url=NULL WHERE source_id='a'")
    conn.commit()
    conn.close()

    result = json.loads(api.api_jobs(limit=50, offset=0, city="Hà Nội").body)
    assert {j["source_id"] for j in result["jobs"]} == {"a", "b", "d"}
    assert api.api_stats(city="Hanoi")["total"] == 3
    meta = api.api_meta(city="Ha Noi")
    assert sum(c["n"] for c in meta["categories"]) == 3
    trend = json.loads(api.api_trend(days=14, city="Hà Nội").body)
    assert sum(day.get("itviec", 0) for day in trend["days"]) == 3

    companies = api.api_companies(limit=50, offset=0, city="Hà Nội")
    assert {c["company"] for c in companies["companies"]} == {"a", "b", "c", "d"}
    assert {c["company"]: c["job_count"] for c in companies["companies"]} == {"a": 1, "b": 1, "c": 0, "d": 1}
    stats = api.api_company_stats(city="Hà Nội")
    assert stats["total"] == 4 and stats["hiring"] == 3
    assert sum(s["n"] for s in stats["by_source"]) == 4
    hiring = api.api_companies(limit=50, offset=0, city="Hà Nội", hiring=1)
    assert {c["company"] for c in hiring["companies"]} == {"a", "b", "d"}
    assert api.api_company_stats(city="Hà Nội", hiring=1)["total"] == hiring["total"]
    unknown = api.api_companies(limit=50, offset=0, city=locations.UNKNOWN)
    assert [c["company"] for c in unknown["companies"]] == ["unknown"]

    async def read_export():
        response = api.export_companies(city="Hà Nội")
        return "".join([chunk async for chunk in response.body_iterator])
    rows = list(csv.DictReader(io.StringIO(asyncio.run(read_export()).lstrip("\ufeff"))))
    assert {r["name"] for r in rows} == {"a", "b", "c", "d"}
    assert {p["value"] for p in api.api_locations()["provinces"]} == {"Hà Nội", "Hồ Chí Minh", "Đà Nẵng"}
