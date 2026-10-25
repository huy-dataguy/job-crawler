from datetime import datetime, timedelta
import json

from fastapi import HTTPException

from dashboard import main as api
from job_crawler import companies_crawl as cc, store
from test_continuous import job


def test_spa_fallback_serves_index_and_guards_api(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>săn việc SPA</html>")
    monkeypatch.setattr(api, "FRONTEND_DIST", dist)
    for path in ("", "thong-ke", "cong-ty", "cong-ty/deep/link"):
        assert "săn việc SPA" in api.spa(path).body.decode()
    try:
        api.spa("api/khong-ton-tai")
        raise AssertionError("api path must 404, not fall through to SPA")
    except HTTPException as e:
        assert e.status_code == 404


def test_recent_open_contract_and_company_size_are_shared_by_api(tmp_path,monkeypatch):
    path=tmp_path/'jobs.db'
    monkeypatch.setattr(api,'DB_PATH',path)
    conn=store.connect(path)
    now=datetime.now().astimezone()
    for ident in ('recent','old','unknown-date','future','expired','stale'):
        store.upsert_job(conn,job(source_id=ident))
    conn.execute("UPDATE jobs SET posted_at=?,date_source='structured',status='open',detail_checked_at=?",
                 ((now-timedelta(days=1)).isoformat(),now.isoformat()))
    conn.execute("UPDATE jobs SET posted_at=? WHERE source_id='old'",((now-timedelta(days=15)).isoformat(),))
    conn.execute("UPDATE jobs SET posted_at=NULL WHERE source_id='unknown-date'")
    conn.execute("UPDATE jobs SET posted_at=? WHERE source_id='future'",((now+timedelta(days=1)).isoformat(),))
    conn.execute("UPDATE jobs SET valid_through=? WHERE source_id='expired'",((now-timedelta(hours=1)).isoformat(),))
    conn.execute("UPDATE jobs SET detail_checked_at=? WHERE source_id='stale'",((now-timedelta(hours=25)).isoformat(),))
    cc.upsert_directory(conn,source='itviec',slug='example',name='Example',detail_url=job()['company_url'])
    conn.execute("UPDATE company_directory SET bucket='151-300',size_raw='151-300 employees'")
    conn.commit();conn.close()
    result=json.loads(api.api_jobs(limit=50,offset=0,company_size='151-300').body)
    assert result['total']==1 and result['jobs'][0]['source_id']=='recent'
    assert result['jobs'][0]['company_bucket']=='151-300'
    assert api.api_stats(company_size='151-300')['total']==1
    assert sum(r['n'] for r in api.api_meta(company_size='151-300')['levels'])==0
    assert json.loads(api.api_jobs(limit=50,offset=0,status='unknown').body)['jobs'][0]['source_id']=='stale'


def test_fts_quotes_and_punctuation_do_not_break_serving(tmp_path,monkeypatch):
    path=tmp_path/'jobs.db';monkeypatch.setattr(api,'DB_PATH',path)
    store.connect(path).close()
    for query in ('"','a"b','C++','* OR -'):
        assert json.loads(api.api_jobs(limit=10,offset=0,q=query).body)['total']==0
