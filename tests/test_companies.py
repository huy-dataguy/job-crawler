"""Tests company_directory: harvest parse + link từ job + enrich theo ngân sách."""
from pathlib import Path

from job_crawler import companies_crawl as cc
from job_crawler import store


def _conn(tmp_path: Path):
    conn = store.connect(tmp_path / "jobs.db")
    cc.ensure_directory_tables(conn)
    return conn


def test_slug_to_name():
    assert cc._slug_to_name("fpt-software") == "Fpt Software"
    assert cc._slug_to_name("cong-ty-cp-kids-plaza") == "Cong Ty Cp Kids Plaza"


def test_parse_itviec_directory():
    html = """
    <a href="/companies/fpt-software">FPT Software</a>
    <a href="/companies/fpt-software">FPT Software</a>
    <a href="/companies/mb-bank/review">review</a>
    <a href="/companies/bosch">Bosch </a>
    """
    out = cc.parse_itviec_directory(html)
    assert out == [("FPT Software", "fpt-software"), ("Bosch", "bosch")]


def test_link_job_company_sets_exact_name_and_hiring(tmp_path: Path):
    conn = _conn(tmp_path)
    # directory có sẵn tên slug (không dấu)
    cc.upsert_directory(conn, source="topcv", slug="cong-ty-vlast",
                        name="Cong Ty Vlast",
                        detail_url="https://www.topcv.vn/cong-ty/cong-ty-vlast/1.html",
                        company_id="1")
    # job crawl link lại với tên chính xác (có dấu)
    slug = cc.link_job_company(
        conn, source="topcv", company="Công Ty Vlast",
        company_url="https://www.topcv.vn/cong-ty/cong-ty-vlast/200306.html")
    assert slug == "cong-ty-vlast"
    row = conn.execute("SELECT name, name_exact, is_hiring, company_id"
                       " FROM company_directory WHERE slug='cong-ty-vlast'").fetchone()
    assert row["name"] == "Công Ty Vlast"
    assert row["name_exact"] == 1
    assert row["is_hiring"] == 1
    assert row["company_id"] == "200306"


def test_link_job_company_itviec_and_refresh(tmp_path: Path):
    conn = _conn(tmp_path)
    slug = cc.link_job_company(
        conn, source="itviec", company="FPT Software",
        company_url="https://itviec.com/companies/fpt-software")
    assert slug == "fpt-software"
    cc.refresh_hiring_flags(conn, "itviec", set())  # hết tin
    assert conn.execute(
        "SELECT is_hiring FROM company_directory").fetchone()["is_hiring"] == 0


def test_upsert_keeps_exact_name_over_slug_name(tmp_path: Path):
    conn = _conn(tmp_path)
    cc.link_job_company(conn, source="itviec", company="FPT Software",
                        company_url="https://itviec.com/companies/fpt-software")
    # harvest lại với tên từ slug — không được đè tên chính xác
    cc.upsert_directory(conn, source="itviec", slug="fpt-software",
                        name="Fpt Software")
    assert conn.execute(
        "SELECT name FROM company_directory").fetchone()["name"] == "FPT Software"


def test_harvest_topcv_sitemap(tmp_path: Path, monkeypatch):
    conn = _conn(tmp_path)
    index_xml = ("<sitemapindex><loc>https://x/companies_0.xml</loc></sitemapindex>")
    page_xml = ("<?xml?><urlset>"
                "<loc>https://www.topcv.vn/cong-ty/fpt-software/3.html</loc>"
                "<loc>https://www.topcv.vn/cong-ty/cong-ty-cp-kids-plaza/13.html</loc>"
                "</urlset>")

    class FakeResp:
        def __init__(self, text, status=200):
            self.text, self.status_code = text, status
        def raise_for_status(self):
            pass

    def fake_get(url, **kw):
        return FakeResp(index_xml if "sitemap/companies.xml" in url else page_xml)
    monkeypatch.setattr(cc._S, "get", fake_get)
    monkeypatch.setattr(cc.time, "sleep", lambda s: None)

    out = cc.harvest_topcv(conn)
    assert out["rows_touched"] == 2
    names = {r["name"] for r in conn.execute("SELECT name FROM company_directory")}
    assert names == {"Fpt Software", "Cong Ty Cp Kids Plaza"}


def test_enrich_missing_budget_and_priority(tmp_path: Path, monkeypatch):
    conn = _conn(tmp_path)
    cc.upsert_directory(conn, source="itviec", slug="hiring-co", name="Hiring Co",
                        detail_url="https://itviec.com/companies/hiring-co")
    cc.upsert_directory(conn, source="itviec", slug="sleepy-co", name="Sleepy Co",
                        detail_url="https://itviec.com/companies/sleepy-co")
    cc.refresh_hiring_flags(conn, "itviec", {"hiring-co"})

    fetched: list[str] = []

    def fake_fetch(url):
        fetched.append(url)
        return "<html><h1>Hiring Co</h1><div>Company size</div><div>1000+ employees</div></html>"

    monkeypatch.setattr(cc, "_fetch", fake_fetch)
    monkeypatch.setattr(cc.time, "sleep", lambda s: None)
    monkeypatch.setattr(cc.config, "COMPANY_ENRICH_BUDGET", 1)

    out = cc.enrich_missing(conn)  # budget 1 → chỉ công ty đang tuyển
    assert out["attempted"] == 1
    assert fetched == ["https://itviec.com/companies/hiring-co"]
    row = conn.execute("SELECT size_raw, bucket FROM company_directory"
                       " WHERE slug='hiring-co'").fetchone()
    assert row["size_raw"] == "1000+ employees"
    assert row["bucket"] == "1000+"


def test_prune_keeps_directory(tmp_path: Path):
    conn = _conn(tmp_path)
    cc.upsert_directory(conn, source="itviec", slug="old-co", name="Old Co",
                        detail_url="https://itviec.com/companies/old-co")
    from datetime import datetime, timedelta
    conn.execute(
        "UPDATE company_directory SET last_seen_at=?",
        ((datetime.now().astimezone() - timedelta(days=90)).isoformat(timespec="seconds"),))
    conn.commit()
    store.prune(conn, keep_days=30, stale_days=7)  # không được xoá directory
    assert conn.execute("SELECT count(*) FROM company_directory").fetchone()[0] == 1
