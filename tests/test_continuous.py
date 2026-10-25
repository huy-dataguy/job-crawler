from datetime import datetime, timedelta
import json

import pytest

from job_crawler import config, details, pipeline, profiles, raw, store
from job_crawler import companies_crawl as cc
from job_crawler.http import SourceError


def job(**overrides):
    return {"source":"itviec","source_id":"data-engineer-1234","title":"Data Engineer",
            "url":"https://itviec.com/it-jobs/data-engineer-1234","company":"Example",
            "company_url":"https://itviec.com/companies/example","is_it":1,
            "skills":"[]","tags":"[]",**overrides}


def page(*, posted="2026-10-10", expiry="2026-10-25", apply=True, title="Data Engineer"):
    posting={"@type":"JobPosting","title":title,"datePosted":posted,"validThrough":expiry,
             "description":"<p>Build data platforms</p>","employmentType":"FULL_TIME"}
    return '<script type="application/ld+json">'+json.dumps(posting)+'</script>'+ ('<button>Apply now</button>' if apply else '')


NOW=datetime(2026,10,21,12,tzinfo=details.LOCAL_TZ)


def test_source_date_overrides_refreshed_listing_and_deadline_includes_day():
    result=details.parse_detail(page(),job(posted_at="2026-10-21T11:59:00+07:00"),now=NOW)
    assert result["posted_at"]=="2026-10-10T00:00:00+07:00"
    assert result["date_source"]=="structured"
    assert result["valid_through"]=="2026-10-25T23:59:59+07:00"
    assert result["status"]=="open"


def test_expired_deadline_wins_over_apply_button():
    assert details.parse_detail(page(expiry="2026-10-20"),job(),now=NOW)["status"]=="closed"


def test_missing_apply_is_unknown_and_recommendation_cannot_verify_other_job():
    assert details.parse_detail(page(apply=False),job(),now=NOW)["status"]=="unknown"
    with pytest.raises(ValueError,match="matching JobPosting"):
        details.parse_detail(page(title="Senior Java Developer"),job(),now=NOW)


def test_open_filter_expires_during_outage_and_rejects_expired_deadline(tmp_path):
    conn=store.connect(tmp_path/"jobs.db")
    for ident in ("fresh","stale","expired"):
        store.upsert_job(conn,job(source_id=ident))
    now=datetime.now().astimezone()
    conn.execute("UPDATE jobs SET status='open',detail_checked_at=?",(now.isoformat(),))
    conn.execute("UPDATE jobs SET detail_checked_at=? WHERE source_id='stale'",((now-timedelta(hours=25)).isoformat(),))
    conn.execute("UPDATE jobs SET valid_through=? WHERE source_id='expired'",((now-timedelta(seconds=1)).isoformat(),))
    ids={r[0] for r in conn.execute('SELECT source_id FROM jobs WHERE '+details.open_condition())}
    assert ids=={"fresh"}


def test_listing_refresh_preserves_verified_date_and_sparse_company_fields(tmp_path):
    conn=store.connect(tmp_path/"jobs.db")
    store.upsert_job(conn,job(posted_at="2026-10-10T00:00:00+07:00",city="Hà Nội",skills='["Python"]'))
    conn.execute("UPDATE jobs SET date_source='structured',description='Full JD',status='closed'")
    store.upsert_job(conn,job(posted_at="2026-10-21T00:00:00+07:00",city=""))
    row=conn.execute("SELECT * FROM jobs").fetchone()
    assert row['posted_at']=="2026-10-10T00:00:00+07:00"
    assert row['city']=="Hà Nội" and row['description']=="Full JD"
    assert row['skills']=='["Python"]' and row['status']=='closed'
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0]==1


def test_partial_listing_does_not_mark_unseen_employer_closed(tmp_path):
    conn=store.connect(tmp_path/"jobs.db")
    cc.link_job_company(conn,source='itviec',company='Example',company_url=job()['company_url'])
    store.upsert_job(conn,job())
    conn.execute("UPDATE jobs SET status='open',detail_checked_at=?",(store.now_iso(),))
    cc.refresh_hiring_flags(conn,'itviec',set())
    assert conn.execute('SELECT is_hiring FROM company_directory').fetchone()[0]==1


def test_failed_source_does_not_skip_other_sources(monkeypatch):
    called=[]
    def run(source):
        called.append(source)
        if source=='itviec':raise RuntimeError('blocked')
        return {'source':source,'found':1}
    monkeypatch.setattr(pipeline,'run_source',run)
    result=pipeline.run_all()
    assert called==['itviec','topcv','topdev'] and 'error' in result[0]
    assert result[2]['found']==1


def test_challenge_never_renews_open_freshness(tmp_path,monkeypatch):
    conn=store.connect(tmp_path/"jobs.db")
    store.upsert_job(conn,job())
    previous=(datetime.now().astimezone()-timedelta(days=2)).isoformat()
    conn.execute("UPDATE jobs SET status='open',detail_checked_at=?",(previous,));conn.commit()
    def blocked(*args,**kwargs):raise SourceError('challenge',status=403)
    monkeypatch.setattr(details,'fetch',blocked)
    result=details.verify_source(conn,'itviec',budget=3)
    assert result['errors']==1
    assert conn.execute('SELECT detail_checked_at FROM jobs').fetchone()[0]==previous
    assert conn.execute('SELECT count(*) FROM jobs WHERE '+details.open_condition()).fetchone()[0]==0


def test_company_it_classification_does_not_exclude_banks():
    assert profiles.classify({'source':'topcv','name':'Example Bank'},has_it_jobs=True)[0]=='it_department'
    assert profiles.classify({'source':'topcv','name':'Factory'},has_it_jobs=False)[0]=='unknown'
    assert profiles.classify({'source':'topcv','industry':'Software products'})[0]=='technology'


def test_raw_evidence_is_immutable_gzipped_with_manifest():
    a=raw.preserve('itviec','https://itviec.com/x','first')
    b=raw.preserve('itviec','https://itviec.com/x','second')
    from job_crawler import config as cfg
    assert a!=b and raw.read(a)=='first' and raw.read(b)=='second'
    assert (cfg.DATA_DIR/a).suffix=='.gz'  # nén trên đĩa, content-addressed
    assert len((cfg.DATA_DIR/'raw/manifest.jsonl').read_text().splitlines())==2


def test_raw_sweep_removes_expired_and_prunes_manifest(monkeypatch):
    import os, time
    from job_crawler import config as cfg
    old=raw.preserve('itviec','https://itviec.com/old','old-body')
    fresh=raw.preserve('itviec','https://itviec.com/fresh','fresh-body')
    os.utime(cfg.DATA_DIR/old,(time.time()-49*3600,)*2)  # quá TTL 48h
    result=raw.sweep()  # config mặc định 48h
    assert not (cfg.DATA_DIR/old).exists() and (cfg.DATA_DIR/fresh).exists()
    assert result['removed']>=1 and result['pruned_manifest']>=1
    manifest=(cfg.DATA_DIR/'raw/manifest.jsonl').read_text()
    assert 'old-body' not in raw.read(fresh)  # sanity
    assert '/old' not in manifest.replace('fresh','')


def test_topdev_directory_reads_card_name_without_global_heading():
    html='''<h1>Discover Companies</h1><div class="bg-card">
    <span class="font-semibold">Example Technology</span>
    <a href="https://saramin.vn/companies/example-123">View company</a></div>'''
    assert cc.parse_topdev_directory(html)=={'example-123':('Example Technology',True)}


def test_topdev_flight_strings_do_not_corrupt_company_name():
    payload='1:'+json.dumps({'company_size':'200+ employees','display_name':'Example Co'})+'\n'
    html='<meta property="og:title" content="IT Jobs at Example Co [Updated today]">'
    html+='<script>self.__next_f.push('+json.dumps([1,payload])+')</script>'
    result=cc._detail_topdev(html)
    assert result['name']=='Example Co' and result['size']=='200+ employees'


def test_offline_replay_preserves_original_verification_freshness(tmp_path,monkeypatch):
    from job_crawler.replay import replay_jobs
    path=tmp_path/'jobs.db';monkeypatch.setattr(config,'DB_PATH',path)
    conn=store.connect(path)
    store.upsert_job(conn,job())
    artifact=raw.preserve('itviec',job()['url'],page())
    observed=(datetime.now().astimezone()-timedelta(days=2)).isoformat(timespec='seconds')
    conn.execute('UPDATE jobs SET raw_artifact=?,detail_checked_at=?',(artifact,observed));conn.commit()
    result=replay_jobs()
    row=conn.execute('SELECT detail_checked_at,description FROM jobs').fetchone()
    assert result=={'updated':1,'failed':0,'freshness_preserved':True}
    assert row[0]==observed and 'Build data platforms' in row[1]
    assert conn.execute('SELECT count(*) FROM jobs WHERE '+details.open_condition()).fetchone()[0]==0
