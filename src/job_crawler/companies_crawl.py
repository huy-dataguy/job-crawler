"""Harvest thư mục công ty đầy đủ từ 3 nguồn + enrich quy mô theo ngân sách.

Phạm vi đã recon (06/10):
- topcv: sitemap companies (~247 sub × 200 ≈ 49k công ty) →
  /cong-ty/<slug>/<id>.html — nguồn ĐẦY ĐỦ.
- itviec: /companies?page=N (25 công ty/trang, không có sitemap) → crawl hết
  các trang cho tới khi hết (hard cap JC_ITVIEC_COMPANY_PAGES).
- topdev: sitemap companies trả 500 (hỏng phía server), /companies chỉ render
  trang đầu qua RSC → harvest trang đầu + TÍCH LŨY dần từ job listings
  (mỗi job crawl bổ sung công ty đang tuyển với tên + URL chính xác).

Enrich quy mô: fetch trang detail theo ngân sách mỗi run (ưu tiên công ty
đang tuyển), không dồn một cục hàng chục nghìn request.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from . import config
from . import normalize
from . import relevance
from . import store
from .http import fetch, SourceError
from . import raw
from .company_enrich import bucket_for, parse_size_range

_S = curl_requests.Session(impersonate="chrome136")

TOPCV_SITEMAP_INDEX = "https://www.topcv.vn/sitemap/companies.xml"
ITVIEC_COMPANIES_URL = "https://itviec.com/companies"
TOPDEV_COMPANIES_URL = "https://topdev.vn/companies"

_SITEMAP_DELAY = 0.4   # sitemap là file tĩnh, giãn cách nhẹ
_DETAIL_DELAY = 1.5    # trang detail công ty — lịch sự với nguồn

_META_TABLE = """
CREATE TABLE IF NOT EXISTS harvest_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS company_directory (
  source        TEXT NOT NULL,
  slug          TEXT NOT NULL,
  company_id    TEXT,
  name          TEXT NOT NULL,
  name_exact    INTEGER NOT NULL DEFAULT 0,  -- 1 = tên bóc từ nguồn (không đè)
  detail_url    TEXT,
  size_raw      TEXT,
  size_min      INTEGER,
  size_max      INTEGER,
  num_employees TEXT,
  bucket        TEXT,
  is_hiring     INTEGER NOT NULL DEFAULT 0,  -- có job trong lần crawl gần nhất
  enriched_at   TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  PRIMARY KEY (source, slug)
);
CREATE INDEX IF NOT EXISTS idx_company_dir_hiring ON company_directory (is_hiring);
CREATE INDEX IF NOT EXISTS idx_company_dir_name ON company_directory (name);
""" + _META_TABLE


def ensure_directory_tables(conn: sqlite3.Connection) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='company_directory'").fetchone():
        raise RuntimeError("Run job-crawler migrate first")


def _now() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _slug_to_name(slug: str) -> str:
    """'fpt-software' → 'Fpt Software'; 'cong-ty-cp-kids-plaza' → giữ nguyên
    dạng chữ hoá (topcv slug không dấu — tên thật sẽ có khi enrich)."""
    words = re.sub(r"[-_]+", " ", slug).split()
    return " ".join(w.capitalize() for w in words if w)


def upsert_directory(conn: sqlite3.Connection, *, source: str, slug: str,
                     name: str, detail_url: str | None = None,
                     company_id: str | None = None, name_exact: bool = False,
                     hiring: bool | None = None) -> None:
    """Thêm/cập nhật 1 công ty. Tên chỉ đè khi bản ghi chưa có tên chính xác
    (name_exact=0) — tránh slug không dấu phá tên có dấu đã bóc được."""
    ts = _now()
    cur = conn.execute(
        "SELECT name_exact FROM company_directory WHERE source=? AND slug=?",
        (source, slug)).fetchone()
    if cur is None:
        conn.execute(
            """INSERT INTO company_directory
                 (source, slug, company_id, name, name_exact, detail_url,
                  is_hiring, first_seen_at, last_seen_at)
               VALUES (?,?,?,?,?,?,?, ?, ?)""",
            (source, slug, company_id, name, 1 if name_exact else 0,
             detail_url, 1 if hiring else 0, ts, ts))
        return
    keep_name = cur["name_exact"] == 1 and not name_exact
    conn.execute(
        f"""UPDATE company_directory SET
              name = CASE WHEN ? THEN name ELSE ? END,
              name_exact = MAX(name_exact, ?),
              detail_url = COALESCE(?, detail_url),
              company_id = COALESCE(?, company_id),
              is_hiring = CASE WHEN ? IS NULL THEN is_hiring ELSE ? END,
              last_seen_at = ?
            WHERE source=? AND slug=?""",
        (1 if keep_name else 0, name, 1 if name_exact else 0,
         detail_url, company_id,
         None if hiring is None else 1, 1 if hiring else 0,
         ts, source, slug))


def link_job_company(conn: sqlite3.Connection, *, source: str,
                     company: str, company_url: str | None) -> str | None:
    """Gắn job → công ty trong directory: đặt tên chính xác + is_hiring=1.
    Trả về slug nếu link được (để pipeline reset is_hiring cho công ty hết tin)."""
    if not company or not company_url:
        # Fallback: match theo tên với công ty đã có trong directory
        # (topdev job card không luôn có link công ty) → chỉ đánh dấu đang tuyển
        if company:
            row = conn.execute(
                "SELECT slug FROM company_directory WHERE source=? AND name=?",
                (source, company)).fetchone()
            if row:
                conn.execute(
                    "UPDATE company_directory SET is_hiring=1, last_seen_at=?"
                    " WHERE source=? AND slug=?",
                    (_now(), source, row["slug"]))
                return row["slug"]
        return None
    m = re.search(r"/(?:companies|cong-ty)/([^?#]+?)(?:\.html)?(?:[?#]|$)", company_url)
    if not m:
        return None
    slug = m.group(1)
    # topcv URL dạng <slug>/<id>.html → tách id
    cid = None
    if source == "topcv":
        mm = re.match(r"(.+)/(\d+)$", slug)
        if mm:
            slug, cid = mm.group(1), mm.group(2)
    upsert_directory(conn, source=source, slug=slug, name=company,
                     detail_url=company_url, company_id=cid,
                     name_exact=True, hiring=True)
    return slug


def refresh_hiring_flags(conn: sqlite3.Connection, source: str,
                         seen_slugs: set[str]) -> None:
    """Derive hiring from retained, fresh open evidence; discovery may be partial."""
    from .details import open_condition
    conn.execute(
        "UPDATE company_directory SET is_hiring=0 WHERE source=? AND is_hiring=1",
        (source,))
    conn.execute("UPDATE company_directory SET is_hiring=1 WHERE source=? AND EXISTS ("
                 "SELECT 1 FROM jobs WHERE jobs.source=company_directory.source AND "
                 "(jobs.company_url=company_directory.detail_url OR jobs.company=company_directory.name) AND "
                 + open_condition() + ")", (source,))


# ---------- harvest: topcv (sitemap — đầy đủ) ------------------------------

def _load_done_subs(conn: sqlite3.Connection, key: str) -> set[str]:
    row = conn.execute("SELECT value FROM harvest_meta WHERE key=?", (key,)).fetchone()
    return set(json.loads(row["value"])) if row else set()


def _save_done_subs(conn: sqlite3.Connection, key: str, done: set[str]) -> None:
    conn.execute(
        """INSERT INTO harvest_meta(key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (key, json.dumps(sorted(done))))


def harvest_topcv(conn: sqlite3.Connection, *, max_pages: int | None = None) -> dict:
    from datetime import datetime, timedelta
    cap = max_pages if max_pages is not None else config.TOPCV_SITEMAP_PAGES
    html = fetch('topcv', TOPCV_SITEMAP_INDEX, session=_S, kind='sitemap', timeout=40)
    subs = re.findall(r'<loc>([^<]*companies[^<]*)</loc>',html)
    if not subs:
        raise ValueError('TopCV company sitemap has no child sitemaps')
    cycle = conn.execute("SELECT value FROM harvest_meta WHERE key='topcv_cycle_at'").fetchone()
    if not cycle or datetime.fromisoformat(cycle[0]) < datetime.now().astimezone()-timedelta(days=7):
        done = set()
        conn.execute("INSERT INTO harvest_meta(key,value) VALUES ('topcv_cycle_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(_now(),))
    else:
        done = _load_done_subs(conn,'topcv_subs_done')
    pending = [u for u in subs if u not in done][:cap]
    updated = failed = processed = 0
    for sub in pending:
        try:
            page = fetch('topcv',sub,session=_S,kind='sitemap')
            locs = re.findall(r'<loc>([^<]+/cong-ty/[^<]+)</loc>',page)
            if not locs:
                raise ValueError('Company sub-sitemap empty or changed')
            for url in locs:
                m = re.search(r'/cong-ty/(.+)/(\d+)\.html?$',url)
                if not m:
                    continue
                slug,cid=m.groups()
                upsert_directory(conn,source='topcv',slug=slug,name=_slug_to_name(slug),detail_url=url,company_id=cid)
                updated += 1
            done.add(sub)
            _save_done_subs(conn,'topcv_subs_done',done)
            conn.commit()
            processed += 1
        except SourceError as exc:
            failed += 1
            if exc.status in (403,429):
                break
        except Exception:
            failed += 1
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    conn.commit()
    return {'source':'topcv','pages':processed,'subs_total':len(subs),'subs_done':len(done & set(subs)),
            'subs_remaining':len(set(subs)-done),'subs_failed':failed,'rows_touched':updated}


# ---------- harvest: itviec (directory phân trang) -------------------------

def parse_itviec_directory(html: str) -> list[tuple[str, str]]:
    """[(name, slug)] từ trang /companies — thẻ <a href='/companies/x'> tên </a>."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a[href^='/companies/']"):
        href = a.get("href", "")
        m = re.match(r"^/companies/([^/?#]+)$", href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        name = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if not name or len(name) < 2:
            continue
        seen.add(slug)
        out.append((name, slug))
    return out


def harvest_itviec(conn: sqlite3.Connection, *, max_pages: int | None = None) -> dict:
    # robots.txt advertises this sitemap index; the directory landing page now
    # repeats featured companies and cannot provide exhaustive pagination.
    html = fetch('itviec','https://itviec.com/twinnings_companies_en.xml',session=_S,kind='sitemap')
    urls = re.findall(r'<loc>(https://itviec.com/companies/[^<]+)</loc>',html)
    if not urls:
        raise ValueError('ITviec company sitemap empty or changed')
    seen = set()
    for url in urls:
        m = re.match(r'https://itviec.com/companies/([^/?#]+)$',url)
        if not m or m.group(1)=='review-company':
            continue
        slug=m.group(1)
        seen.add(slug)
        upsert_directory(conn,source='itviec',slug=slug,name=_slug_to_name(slug),detail_url=url)
    conn.commit()
    return {'source':'itviec','pages':1,'companies':len(seen),'coverage':'public company sitemap'}


# ---------- harvest: topdev (trang đầu + tích lũy job) ---------------------

def parse_topdev_directory(html: str) -> dict[str, tuple[str,bool]]:
    soup=BeautifulSoup(html,'html.parser')
    pairs={}
    for card in soup.select('div.bg-card'):
        a=card.select_one('a[href*="/companies/"]')
        if not a:continue
        m=re.search(r'/companies/([a-z0-9-]+-\d+)',a.get('href',''))
        if not m:continue
        slug=m.group(1)
        heading=card.select_one('span.font-semibold') or card.find(['h2','h3','h4'])
        name=heading.get_text(' ',strip=True) if heading else _slug_to_name(slug)
        pairs[slug]=(name,heading is not None)
    return pairs


def harvest_topdev(conn: sqlite3.Connection) -> dict:
    import os
    from datetime import datetime,timedelta
    cap=int(os.environ.get('JC_TOPDEV_COMPANY_PAGES','10'))
    row=conn.execute("SELECT value FROM harvest_meta WHERE key='topdev_next_page'").fetchone()
    page=int(row[0]) if row else 1
    cycle=conn.execute("SELECT value FROM harvest_meta WHERE key='topdev_cycle_done_at'").fetchone()
    if page==1 and cycle and datetime.fromisoformat(cycle[0])>datetime.now().astimezone()-timedelta(days=7):
        return {'source':'topdev','pages':0,'companies':0,'next_page':1,'coverage':'cycle complete; refresh weekly'}
    previous=conn.execute("SELECT value FROM harvest_meta WHERE key='topdev_previous_slugs'").fetchone()
    previous=set(json.loads(previous[0])) if previous else set()
    touched=pages=0
    for _ in range(cap):
        url=TOPDEV_COMPANIES_URL+(f'?page={page}' if page>1 else '')
        html=fetch('topdev',url,session=_S,kind='directory')
        pairs=parse_topdev_directory(html)
        if not pairs:
            raise ValueError(f'TopDev company page {page} empty or changed')
        if set(pairs)==previous:
            page=1
            conn.execute("INSERT INTO harvest_meta(key,value) VALUES ('topdev_cycle_done_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(_now(),))
            break
        for slug,(name,exact) in pairs.items():
            # Native page 2 currently links to saramin.vn; retain the source's
            # topdev.vn canonical profile path so one profile has one identity.
            upsert_directory(conn,source='topdev',slug=slug,name=name,
                             detail_url=f'https://topdev.vn/companies/{slug}',name_exact=exact)
            touched+=1
        pages+=1;page+=1;previous=set(pairs)
        conn.execute("INSERT INTO harvest_meta(key,value) VALUES ('topdev_next_page',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(page),))
        conn.execute("INSERT INTO harvest_meta(key,value) VALUES ('topdev_previous_slugs',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(sorted(previous)),))
        conn.commit()
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    conn.execute("INSERT INTO harvest_meta(key,value) VALUES ('topdev_next_page',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(page),))
    conn.commit()
    return {'source':'topdev','pages':pages,'companies':touched,'next_page':page,
            'coverage':'public paginated directory + accumulated job profiles'}


# ---------- enrich quy mô (ngân sách mỗi run) ------------------------------

def _fetch(url: str) -> str:
    from urllib.parse import urlparse
    source = 'topcv' if 'topcv' in (urlparse(url).hostname or '') else ('topdev' if 'topdev' in url else 'itviec')
    return fetch(source,url,session=_S,kind='company')


def _label_sibling(soup: BeautifulSoup, label_re: str, max_len: int = 300) -> str | None:
    """Giá trị đứng cạnh label (vd 'Ngành nghề kinh doanh' → 'Lập trình...')."""
    import re as _re
    node = soup.find(string=_re.compile(label_re, _re.I))
    if not node:
        return None
    p = node.find_parent(["div", "span", "li", "dt"])
    if p is None:
        return None
    sib = p.find_next_sibling()
    if sib is None:
        return None
    txt = re.sub(r"\s+", " ", sib.get_text(" ", strip=True))
    return txt[:max_len] if txt else None


def _meta_description(soup: BeautifulSoup) -> str | None:
    m = (soup.find("meta", attrs={"property": "og:description"})
         or soup.find("meta", attrs={"name": "description"}))
    if m and m.get("content"):
        return re.sub(r"\s+", " ", m["content"]).strip()[:1500]
    return None


def _detail_topcv(html: str) -> dict:
    """Trang công ty topcv: quy mô, tên thật, ngành nghề, mô tả."""
    soup = BeautifulSoup(html, "html.parser")
    name = None
    h1 = soup.find("h1")
    if h1:
        name = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
    size = None
    for node in soup.find_all(string=re.compile(r"Quy mô", re.I)):
        sib = node.parent.find_next_sibling() if node.parent else None
        if sib:
            raw = sib.get_text(" ", strip=True)
            if raw and re.search(r"\d", raw):
                size = raw
                break
    return {
        "size": size,
        "name": name,
        "industry": _label_sibling(soup, r"Ngành nghề"),
        "description": _meta_description(soup),
        "jobs": [],
    }


def _detail_itviec(html: str) -> dict:
    """Trang công ty itviec (UI EN): Company overview / General information /
    'N job openings' chứa link việc đang tuyển (?lab_feature=employer_job)."""
    soup = BeautifulSoup(html, "html.parser")
    name = size = industry = description = None
    h1 = soup.find("h1")
    if h1:
        name = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
    # General information là các cặp label/value — regex trên full text để
    # không phụ thuộc nesting DOM (section/div đổi cấu trúc vẫn bắt được)
    txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    m = re.search(r"Company industry\s+(.{3,120}?)(?:Company size|Country|Working days|$)", txt)
    if m:
        industry = m.group(1).strip()
    m = re.search(r"Company size\s+([\d\+\- ]+employees)", txt, re.I)
    if m:
        size = m.group(1).strip()
    ov = soup.find(string=re.compile(r"Company overview", re.I))
    if ov is not None:
        sec = ov.find_parent(["section", "div"])
        if sec is not None:
            description = re.sub(r"\s+", " ", sec.get_text(" ", strip=True))
            description = description.replace("Company overview", "", 1).strip()[:1500] or None
    jobs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a[href*='lab_feature=employer_job']"):
        slug_m = re.match(r"^/it-jobs/([^?\"']+)", a.get("href", ""))
        title = a.get_text(" ", strip=True)
        if not slug_m or not title or slug_m.group(1) in seen:
            continue
        seen.add(slug_m.group(1))
        jobs.append((title, f"https://itviec.com/it-jobs/{slug_m.group(1)}"))
    return {"size": size, "name": name, "industry": industry,
            "description": description, "jobs": jobs}


def _detail_topdev(html: str) -> dict:
    # Decode Flight string envelopes before matching JSON strings. Matching escaped
    # HTML directly previously swallowed the remaining payload into company names.
    soup=BeautifulSoup(html,'html.parser')
    decoded=[]
    for script in soup.select('script'):
        body=script.get_text()
        for match in re.finditer(r'self\.__next_f\.push\((\[.*?\])\)',body,re.S):
            try:
                envelope=json.loads(match.group(1))
                if len(envelope)>1 and isinstance(envelope[1],str):decoded.append(envelope[1])
            except (ValueError,TypeError):pass
    payload='\n'.join(decoded)
    def value(field):
        match=re.search(r'"'+field+r'"\s*:\s*("(?:[^"\\]|\\.)*")',payload)
        if match:
            try:return json.loads(match.group(1))
            except ValueError:return None
        return None
    meta=soup.select_one('meta[property="og:title"]')
    name=None
    if meta:
        match=re.match(r'IT Jobs at (.+?)(?: \[|$)',meta.get('content',''))
        if match:name=match.group(1).strip()
    return {'size':value('company_size'),'name':name or value('display_name'),
            'industry':value('industry_name'),'description':None,'jobs':[]}


_ENRICHERS = {"topcv": _detail_topcv, "itviec": _detail_itviec,
              "topdev": _detail_topdev}


def classify_profiles(conn: sqlite3.Connection, *, source: str | None = None) -> None:
    from .profiles import classify
    rows = conn.execute("SELECT source,slug,name,industry,description,it_status,it_evidence FROM company_directory"
                        + (" WHERE source=?" if source else ""), (source,) if source else ()).fetchall()
    job_names = {(r[0], r[1]) for r in conn.execute("SELECT DISTINCT source,company FROM jobs WHERE is_it=1")}
    changes = []
    for row in rows:
        status, evidence = classify(dict(row), has_it_jobs=(row["source"],row["name"]) in job_names)
        if status != row["it_status"] or evidence != row["it_evidence"]:
            changes.append((status,evidence,row["source"],row["slug"]))
    conn.executemany("UPDATE company_directory SET it_status=?,it_evidence=? WHERE source=? AND slug=?", changes)
    conn.commit()


def enrich_missing(conn: sqlite3.Connection, *, budget: int | None = None) -> dict:
    from datetime import datetime, timedelta
    from .profiles import parse, classify
    budget = budget if budget is not None else config.COMPANY_ENRICH_BUDGET
    # Round-robin sources and reserve 1/5 of the queue for general employers.
    rows = conn.execute(
        """SELECT *, ROW_NUMBER() OVER (PARTITION BY source, (it_status='unknown')
           ORDER BY is_hiring DESC, enriched_at IS NOT NULL, enriched_at, last_seen_at DESC) AS rank
           FROM company_directory WHERE detail_url IS NOT NULL
           AND (next_enrich_at IS NULL OR julianday(next_enrich_at)<=julianday('now'))
           ORDER BY rank, (it_status='unknown'), source LIMIT ?""", (budget,)).fetchall()
    done = errors = jobs_ingested = 0
    blocked_sources = set()
    for row in rows:
        r = dict(row)
        if r['source'] in blocked_sources:
            continue
        try:
            from urllib.parse import urlparse
            from .details import HOSTS
            if urlparse(r['detail_url']).hostname not in HOSTS[r['source']]:
                raise ValueError('Company URL outside source hosts')
            html = _fetch(r['detail_url'])
            if not html:
                raise ValueError('Company fetch failed')
            base = _ENRICHERS[r['source']](html)
            detail = parse(html, r['source'], base)
            detail['source'] = r['source']
            status, evidence = classify(detail, has_it_jobs=bool(r['is_hiring']))
            lo, hi = parse_size_range(detail.get('size') or '')
            fields = {k: detail.get(k) for k in ('industry','description','website','address',
                      'company_type','country','working_days','overtime','tech_stack','benefits','logo_url','public_links')}
            fields.update(size_raw=detail.get('size'), size_min=lo, size_max=hi,
                          bucket=bucket_for(lo,hi) if lo is not None else None,
                          it_status=status,it_evidence=evidence,
                          enriched_at=_now(), enrichment_error=None,
                          next_enrich_at=(datetime.now().astimezone()+timedelta(days=14)).isoformat(timespec='seconds'),
                          raw_artifact=raw.preserve(r['source'],r['detail_url'],html,kind='company'))
            # Keep useful existing fields if a source temporarily omits them.
            fields = {k:v for k,v in fields.items() if v not in (None,'','[]') or k=='enrichment_error'}
            conn.execute('UPDATE company_directory SET '+','.join(f'{k}=?' for k in fields)
                         +' WHERE source=? AND slug=?',list(fields.values())+[r['source'],r['slug']])
            if detail.get('name'):
                conn.execute('UPDATE company_directory SET name=?,name_exact=1 WHERE source=? AND slug=?',
                             (detail['name'],r['source'],r['slug']))
            for title,url in detail.get('jobs') or []:
                job = {'source':'itviec','source_id':url.rsplit('/',1)[-1],'title':title,
                       'company':detail.get('name') or r['name'],'company_url':r['detail_url'],
                       'url':url,'city':'','is_it':1,'level':normalize.parse_level(title),
                       'tags':'[]','skills':'[]','category':''}
                relevance.annotate(job)
                store.upsert_job(conn,job)
                jobs_ingested += 1
            done += 1
        except Exception as exc:
            errors += 1
            conn.execute('UPDATE company_directory SET enrichment_error=?,next_enrich_at=? WHERE source=? AND slug=?',
                         (str(exc)[:300],(datetime.now().astimezone()+timedelta(hours=6)).isoformat(timespec='seconds'),
                          r['source'],r['slug']))
            if isinstance(exc,SourceError) and exc.status in (403,429):
                blocked_sources.add(r['source'])
        conn.commit()
        time.sleep(config.DELAY_BETWEEN_REQUESTS)
    return {'budget':budget,'attempted':done+errors,'enriched':done,'fetch_errors':errors,'jobs_ingested':jobs_ingested}
