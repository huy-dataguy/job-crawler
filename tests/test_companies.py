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
        return ("<html><h1>Hiring Co</h1>"
                "<div>General information Company industry IT Services "
                "Company size 1000+ employees Country Vietnam</div>"
                "<div>Company overview We build data platforms.</div>"
                "<a href='/it-jobs/senior-data-engineer-hco-123?lab_feature=employer_job'>"
                "Senior Data Engineer</a></html>")

    monkeypatch.setattr(cc, "_fetch", fake_fetch)
    monkeypatch.setattr(cc.time, "sleep", lambda s: None)
    monkeypatch.setattr(cc.config, "COMPANY_ENRICH_BUDGET", 1)

    out = cc.enrich_missing(conn)  # budget 1 → chỉ công ty đang tuyển
    assert out["attempted"] == 1
    assert fetched == ["https://itviec.com/companies/hiring-co"]
    row = conn.execute("SELECT size_raw, bucket, industry, description"
                       " FROM company_directory WHERE slug='hiring-co'").fetchone()
    assert row["size_raw"] == "1000+ employees"
    assert row["bucket"] == "1000+"
    assert "IT Services" in row["industry"]
    assert "data platforms" in row["description"]
    # job đang tuyển từ trang công ty được ingest vào bảng jobs
    assert out["jobs_ingested"] == 1
    j = conn.execute("SELECT title, relevance, is_it FROM jobs"
                     " WHERE source_id='senior-data-engineer-hco-123'").fetchone()
    assert j["title"] == "Senior Data Engineer"
    # chỉ có title (không category/tags như listing) → điểm thấp hơn nhưng vẫn
    # nhận diện được nghề: DE title = 12*3 + senior +0 = 36
    assert j["relevance"] == 36


def test_detail_itviec_parses_industry_description_jobs():
    html = """
    <html><h1>FPT Software</h1>
    <section><div>General information</div>
      <div>Company type IT Service</div>
      <div>Company industry IT Services and IT Consulting</div>
      <div>Company size 1000+ employees</div>
      <div>Country Vietnam</div></section>
    <section><h2>Company overview</h2><p>The leading provider of software outsourcing.</p></section>
    <h2>4 job openings</h2>
    <a href="/it-jobs/data-engineer-fpt-0228?lab_feature=employer_job">Data Engineer</a>
    <a href="/it-jobs/data-engineer-fpt-0228?lab_feature=employer_job">Data Engineer</a>
    <a href="/it-jobs/python?click_source=Skill+tag">Python</a>
    </html>"""
    d = cc._detail_itviec(html)
    assert d["name"] == "FPT Software"
    assert d["industry"] == "IT Services and IT Consulting"
    assert d["size"] == "1000+ employees"
    assert "outsourcing" in d["description"]
    assert d["jobs"] == [("Data Engineer", "https://itviec.com/it-jobs/data-engineer-fpt-0228")]


def test_detail_topcv_parses_industry_and_meta_description():
    html = """
    <html><head><meta property="og:description" content="Công ty phần mềm NASANI làm về AI platform."></head>
    <body><h1>CÔNG TY TNHH NASANI</h1>
    <div><span>Ngành nghề kinh doanh</span><span>Lập trình máy tính khác</span></div>
    <div><label>Quy mô</label><span>25-99 nhân viên</span></div>
    </body></html>"""
    d = cc._detail_topcv(html)
    assert d["name"] == "CÔNG TY TNHH NASANI"
    assert d["industry"] == "Lập trình máy tính khác"
    assert d["size"] == "25-99 nhân viên"
    assert "NASANI" in d["description"]


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
