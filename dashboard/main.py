"""Dashboard đọc SQLite job_crawler.db — FastAPI + Jinja2, render server-side."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

FRONTEND_DIST = Path(os.environ.get(
    "JC_FRONTEND_DIST", Path(__file__).resolve().parents[1] / "frontend" / "dist"
))
DB_PATH = Path(
    os.environ.get(
        "JC_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "job_crawler.db"
    )
)
from job_crawler import store, details, config, locations, roles

app = FastAPI(title="Job Crawler Dashboard", version="2.0.0")
# JSON jobs/meta khá lớn (hàng trăm KB) — gzip giảm ~5-10x thời gian truyền.
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def _assets_immutable(request: Request, call_next):
    """Vite đặt hash tên file trong /assets — nội dung đổi là tên đổi → cache
    vĩnh viễn an toàn và tiết kiệm bandwidth."""
    response = await call_next(request)
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def db() -> sqlite3.Connection:
    conn = store.connect(DB_PATH)
    conn.create_function("province_matches", 3, locations.matches, deterministic=True)
    conn.create_function("role_matches", 3, roles.matches, deterministic=True)
    return conn


@app.get("/api/locations")
def api_locations():
    conn = db()
    try:
        observed = set()
        for row in conn.execute("SELECT DISTINCT city FROM jobs WHERE city IS NOT NULL"):
            observed.update(locations.provinces(row[0]))
        for row in conn.execute("SELECT DISTINCT address FROM company_directory WHERE address IS NOT NULL"):
            observed.update(locations.provinces(row[0], True))
        return {"provinces": locations.options(observed)}
    finally:
        conn.close()


class MarkBody(BaseModel):
    source: str
    source_id: str
    viewed: int | None = None  # 0/1, None = giữ nguyên
    hidden: int | None = None
    applied: int | None = None
    starred: int | None = None


@app.get("/", response_class=HTMLResponse)
def index():
    """SPA frontend (React build)."""
    return HTMLResponse((FRONTEND_DIST / "index.html").read_text())


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.post("/api/mark")
def api_mark(body: MarkBody):
    conn = db()
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("SELECT viewed, hidden, applied, starred FROM job_marks WHERE source=? AND source_id=?",
                       (body.source, body.source_id)).fetchone()
    viewed = body.viewed if body.viewed is not None else (cur["viewed"] if cur else 0)
    hidden = body.hidden if body.hidden is not None else (cur["hidden"] if cur else 0)
    applied = body.applied if body.applied is not None else (cur["applied"] if cur else 0)
    starred = body.starred if body.starred is not None else (cur["starred"] if cur else 0)
    conn.execute("""INSERT INTO job_marks(source, source_id, viewed, hidden, applied, starred, marked_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(source, source_id) DO UPDATE SET viewed=?, hidden=?, applied=?, starred=?, marked_at=?""",
                 (body.source, body.source_id, viewed, hidden, applied, starred, now,
                  viewed, hidden, applied, starred, now))
    conn.commit()
    conn.close()
    return {"ok": True, "viewed": viewed, "hidden": hidden, "applied": applied, "starred": starred}


def _jobs_by_company_ctes(city: str = ''):
    """CTE đếm job còn mở theo (source, company_url) và (source, company) — gom 1
    lần từ phía jobs rồi JOIN NGƯỢC bằng khóa đều đẳng (SQLite tự dựng index tạm
    cho CTE). Thay điều kiện row-value IN per-row trước đây vốn quét 65k công ty.
    Trả về (ctes_sql, from_sql, params_đã_theo_đúng_thứ_tự_placeholder)."""
    open_c = details.open_condition()
    cond = ""
    city_params: list[str] = []
    if city:
        op = "=0" if city == locations.UNKNOWN else "=1"
        cond = f" AND province_matches(jobs.city,?,0){op}"
        city_params = [city]
    ctes = (f"WITH jc_url AS (SELECT source, company_url k, count(*) n FROM jobs WHERE {open_c} AND company_url IS NOT NULL{cond} GROUP BY 1,2),"
            f" jc_name AS (SELECT source, company k, count(*) n FROM jobs WHERE {open_c} AND company IS NOT NULL{cond} GROUP BY 1,2) ")
    frm = ("company_directory d "
           "LEFT JOIN jc_url ju ON ju.source=d.source AND ju.k=d.detail_url "
           "LEFT JOIN jc_name jn ON jn.source=d.source AND jn.k=d.name")
    return ctes, frm, city_params + city_params


def _missing_company_value(column: str) -> str:
    return (f"LOWER(TRIM(COALESCE(d.{column},''), ' '||char(9)||char(10)||char(13))) "
            "IN ('','unknown','n/a','na','null','none','-','—','chưa cập nhật','đang cập nhật','chưa có thông tin')")


_COMPANY_MISSING = {field: _missing_company_value(column) for field, column in {
    'size': 'size_raw', 'industry': 'industry', 'website': 'website',
    'address': 'address', 'description': 'description',
}.items()}


def _company_filter(q='', source='', bucket='', hiring=0, it_only=0, city='', missing_fields='', missing_mode='all'):
    where, params = ['1=1'], []
    selected = list(dict.fromkeys(field.strip() for field in missing_fields.split(',') if field.strip()))
    if missing_mode not in ('all', 'any'):
        raise HTTPException(422, "missing_mode must be all or any")
    unknown = set(selected) - _COMPANY_MISSING.keys()
    if unknown:
        raise HTTPException(422, "Unknown missing field: " + ', '.join(sorted(unknown)))
    if selected:
        joiner = ' AND ' if missing_mode == 'all' else ' OR '
        where.append('(' + joiner.join('(' + _COMPANY_MISSING[field] + ')' for field in selected) + ')')
    for field,value in (('source',source),('bucket',bucket)):
        if value:
            where.append(f'd.{field}=?'); params.append(value)
    if q:
        where.append('(d.name LIKE ? OR d.slug LIKE ? OR d.industry LIKE ? OR d.description LIKE ?)')
        params.extend([f'%{q}%']*4)
    if it_only:
        where.append("d.it_status IN ('technology','it_department')")
    if city:
        # CTE (city-filtered) cho biết công ty còn job mở ở tỉnh đã chọn
        if city == locations.UNKNOWN:
            where.append("(province_matches(d.address,?,1)=1 AND COALESCE(ju.n,jn.n,0)=0)")
        else:
            where.append("(province_matches(d.address,?,1)=1 OR COALESCE(ju.n,jn.n,0)>0)")
        params.append(city)
    if hiring:
        where.append("COALESCE(ju.n, jn.n, 0) > 0")
    return ' AND '.join(where),params


def _company_row(row):
    out=dict(row)
    out['company']=out['name']; out['company_slug']=out['slug'];out['fetched_at']=out['enriched_at']
    for key in ('tech_stack','public_links'):
        try: out[key]=json.loads(out.get(key) or '[]')
        except (ValueError,TypeError):out[key]=[]
    out['completeness']=round(sum(bool(out.get(k)) for k in
        ('name_exact','website','address','industry','size_raw','description','company_type','country','working_days','tech_stack'))/10*100)
    out['is_hiring']=int(out.get('job_count',0)>0)
    return out


@app.get('/api/companies')
def api_companies(q: str='',source: str='',bucket: str='',hiring: int=0,it_only: int=0,city: str='',missing_fields: str='',missing_mode: str='all',
                  limit: int=Query(100,ge=1,le=500),offset: int=Query(0,ge=0)):
    where,params=_company_filter(q,source,bucket,hiring,it_only,city,missing_fields,missing_mode)
    conn=db()
    ctes, cfrm, cparams = _jobs_by_company_ctes(city)
    total=conn.execute(ctes+f'SELECT count(*) FROM {cfrm} WHERE {where}',cparams+params).fetchone()[0]
    rows=conn.execute(ctes + f"SELECT d.*, COALESCE(ju.n, jn.n, 0) job_count FROM {cfrm} "
                      f"WHERE {where} ORDER BY job_count DESC, (d.it_status!='unknown') DESC, d.name LIMIT ? OFFSET ?",
                      cparams + params + [limit, offset]).fetchall()
    result=[_company_row(r) for r in rows]
    _attach_hiring_roles(conn, result, city)
    conn.close()
    return {'total':total,'companies':result,
            'count_semantics':'source profiles; may overlap across sources'}


def _attach_hiring_roles(conn: sqlite3.Connection, companies: list[dict], city: str = ''):
    """Gắn `hiring_roles` (top category đang tuyển + số) và `hiring_role_tags`
    (slug hướng ứng tuyển) cho các công ty của trang hiện tại — 2 truy vấn IN
    cho ~limit công ty, không đụng vào phần phân trang/sắp xếp."""
    if not companies:
        return
    open_c = details.open_condition()
    city_cond = " AND province_matches(jobs.city,?,0)=1" if city else ""
    city_params = [city] if city else []
    name_keys: dict[str, set] = {}
    url_keys: dict[str, set] = {}
    for c in companies:
        name_keys.setdefault(c["source"], set()).add(c["name"])
        if c["detail_url"]:
            url_keys.setdefault(c["source"], set()).add(c["detail_url"])
    by_name: dict[tuple, list] = {}
    by_url: dict[tuple, list] = {}
    for col, keys, into in (("company", name_keys, by_name), ("company_url", url_keys, by_url)):
        for s, vals in keys.items():
            marks = ",".join("?" * len(vals))
            for j in conn.execute(
                    f"SELECT source, source_id, {col} AS k, title, category FROM jobs "
                    f"WHERE {open_c} AND source=? AND {col} IN ({marks}){city_cond}",
                    [s, *vals] + city_params):
                into.setdefault((j["source"], j["k"]), []).append(j)
    slugs = list(roles.names())
    for c in companies:
        js = by_url.get((c["source"], c["detail_url"] or "")) or by_name.get((c["source"], c["name"]), [])
        cats: dict[str, int] = {}
        tags: set[str] = set()
        for j in js:
            if j["category"]:
                cats[j["category"]] = cats.get(j["category"], 0) + 1
            for slug in slugs:
                if roles.matches(slug, j["title"], j["category"]):
                    tags.add(slug)
        c["hiring_roles"] = [{"name": k, "n": v} for k, v in sorted(cats.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        c["hiring_role_tags"] = sorted(tags)


@app.get('/api/companies/export')
def export_companies(q: str='',source: str='',bucket: str='',hiring: int=0,it_only: int=0,city: str='',missing_fields: str='',missing_mode: str='all'):
    import csv,io
    where,params=_company_filter(q,source,bucket,hiring,it_only,city,missing_fields,missing_mode)
    ctes, cfrm, cparams = _jobs_by_company_ctes(city)
    def generate():
        conn=db()
        try:
            fields=['source','slug','name','name_exact','detail_url','website','address','industry','size_raw',
                    'description','company_type','country','working_days','overtime','tech_stack','benefits',
                    'public_links','it_status','it_evidence','enriched_at','enrichment_error']
            buf=io.StringIO();writer=csv.writer(buf);writer.writerow(fields)
            yield '\ufeff'+buf.getvalue()
            for row in conn.execute(ctes+'SELECT '+','.join('d.'+f for f in fields)+f' FROM {cfrm} WHERE {where}',cparams+params):
                buf.seek(0);buf.truncate(0)
                # Spreadsheet-safe export of untrusted source text.
                writer.writerow([("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for v in row])
                yield buf.getvalue()
        finally:conn.close()
    return StreamingResponse(generate(),media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition':'attachment; filename="companies.csv"'})


@app.get('/api/company-stats')
def api_company_stats(q: str='',source: str='',bucket: str='',hiring: int=0,it_only: int=0,city: str='',missing_fields: str='',missing_mode: str='all'):
    where,params=_company_filter(q,source,bucket,hiring,it_only,city,missing_fields,missing_mode)
    ctes, cfrm, cparams = _jobs_by_company_ctes(city)
    conn=db()
    row=conn.execute(ctes+f"SELECT count(*) total, sum(NOT ({_COMPANY_MISSING['size']})) enriched, "
                     f"sum(NOT ({_COMPANY_MISSING['website']})) websites, "
                     f"sum(NOT ({_COMPANY_MISSING['address']})) addresses, sum(it_status!='unknown') it_profiles, "
                     f"sum(enrichment_error IS NOT NULL) errors FROM {cfrm} WHERE {where}",cparams+params).fetchone()
    result={key:(value or 0) for key,value in dict(row).items()}
    missing_counts=conn.execute(ctes+f'SELECT '+','.join(f'SUM({condition}) AS {field}' for field,condition in _COMPANY_MISSING.items())+
                               f' FROM {cfrm} WHERE {where}',cparams+params).fetchone()
    result['missing_counts']={key:(value or 0) for key,value in dict(missing_counts).items()}
    # where đã chứa điều kiện hiring (COALESCE(ju.n,jn.n,0)>0) khi hiring=1
    result['hiring']=conn.execute(ctes+f'SELECT count(*) FROM {cfrm} WHERE {where} AND COALESCE(ju.n,jn.n,0)>0',cparams+params).fetchone()[0]
    result['buckets']=[dict(r) for r in conn.execute(ctes+f"SELECT d.bucket,count(*) n FROM {cfrm} WHERE {where} AND d.bucket IS NOT NULL GROUP BY 1",cparams+params)]
    result['by_source']=[dict(r) for r in conn.execute(ctes+f'SELECT d.source,count(*) n,sum(d.enriched_at IS NOT NULL) checked FROM {cfrm} WHERE {where} GROUP BY 1',cparams+params)]
    result['count_semantics']='source profiles, not unique legal entities'
    conn.close()
    return result


# Trạng thái review của job (inbox model) — map sang điều kiện SQL trên job_marks.
# starred là lớp "yêu thích" song song: job đã sao vẫn nằm ở tab review tự nhiên
# (Cần xem/Đã xem/Đã apply) và có tab riêng để quay lại.
_MARK_CONDS = {
    "unseen": "COALESCE(job_marks.viewed,0)=0 AND COALESCE(job_marks.applied,0)=0"
              " AND COALESCE(job_marks.hidden,0)=0",
    "viewed": "COALESCE(job_marks.viewed,0)=1 AND COALESCE(job_marks.applied,0)=0"
              " AND COALESCE(job_marks.hidden,0)=0",
    "applied": "COALESCE(job_marks.applied,0)=1",
    "hidden": "COALESCE(job_marks.hidden,0)=1",
    "starred": "COALESCE(job_marks.starred,0)=1",
}


@app.get("/api/jobs")
def api_jobs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), source: str = "",
             q: str = "", category: str = "", exp: str = "", tag: str = "",
             skill: str = "", level: str = "", salary_min: float = 0,
             it_only: int = 1, show_hidden: int = 0, company_size: str = "",
             since_hours: int = 336, sort: str = "auto", relevance_min: int = 0,
             mark: str = "all", company: str = "", status: str = "open", city: str = "", work_mode: str = "",
             role: str = "", first_seen_hours: int = 0, first_seen_today: int = 0):
    """Bảng đồng nhất xuyên nguồn. `mark` = trạng thái review (unseen/viewed/
    applied/hidden/all); `relevance_min` = ngưỡng khớp profile CV;
    `role` = danh sách hướng ứng tuyển (de,backend,fullstack,ds)."""
    conn = db()
    frm, where_s, params, use_fts = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only,
        since_hours=since_hours, company_size=company_size,
        relevance_min=relevance_min, company=company, status=status, city=city, work_mode=work_mode,
        role=role, first_seen_hours=first_seen_hours, first_seen_today=first_seen_today)
    # Luôn JOIN marks: cần viewed/applied/hidden cho lọc + hiển thị
    if "job_marks" not in frm:
        frm += " LEFT JOIN job_marks ON job_marks.source=jobs.source AND job_marks.source_id=jobs.source_id"
    base_where = where_s
    if mark in _MARK_CONDS:
        base_where += f" AND {_MARK_CONDS[mark]}"
    elif not show_hidden:
        base_where += " AND COALESCE(job_marks.hidden,0)=0"
    if sort == "posted":
        order = "julianday(jobs.posted_at) DESC NULLS LAST"
    elif sort == "new":
        order = "jobs.last_seen_at DESC"
    elif sort == "salary":
        order = "jobs.salary_max DESC NULLS LAST"
    elif sort == "relevance" or (sort == "auto" and not use_fts):
        # mặc định: job khớp profile CV trước, rồi mới đăng trước
        order = "COALESCE(jobs.relevance, 0) DESC, jobs.posted_at DESC NULLS LAST"
    else:
        # search từ khóa: khớp từ khóa trước, điểm profile cộng thêm
        order = "bm25(jobs_fts), COALESCE(jobs.relevance, 0) DESC"
    total = conn.execute(f"SELECT count(*) FROM {frm} WHERE {base_where}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT jobs.source, jobs.source_id, jobs.title, jobs.company, jobs.url,
                   jobs.city, jobs.salary, jobs.experience, jobs.exp_min, jobs.category,
                   jobs.tags, jobs.skills, jobs.is_it, jobs.level,
                   jobs.salary_min, jobs.salary_max,
                   jobs.posted_text, jobs.posted_at,
                   jobs.relevance, jobs.matched,
                   jobs.first_seen_at, jobs.last_seen_at, jobs.is_new,
                   jobs.status, jobs.status_reason, jobs.valid_through, jobs.date_source,
                   jobs.detail_checked_at, jobs.work_mode, jobs.employment_type, jobs.company_url,
                   CASE WHEN {details.open_condition()} THEN 'open'
                        WHEN jobs.status='closed' OR julianday(jobs.valid_through)<julianday('now') THEN 'closed'
                        ELSE 'unknown' END AS effective_status,
                   COALESCE(job_marks.viewed,0) as viewed,
                   COALESCE(job_marks.hidden,0) as hidden,
                   COALESCE(job_marks.applied,0) as applied,
                   COALESCE(job_marks.starred,0) as starred
             FROM {frm} WHERE {base_where} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    rows = _attach_company_info(conn, rows)
    conn.close()
    return JSONResponse({
        "total": total,
        "jobs": [{**dict(r), "tags": json.loads(r["tags"] or "[]"),
                  "skills": json.loads(r["skills"] or "[]"),
                  "matched": json.loads(r["matched"] or "[]")} for r in rows],
    })


def _q_like(x: str) -> str:
    return f"%{x}%"


def _attach_company_info(conn: sqlite3.Connection, rows: list) -> list[dict]:
    """Bổ sung size_raw/bucket/num_employees cho TRANG hiện tại (≤ limit job) bằng
    2 truy vấn IN đều đẳng — thay 3 subquery tương quan trước đây vốn quét toàn bộ
    65k dòng company_directory cho từng job (nguyên nhân /api/jobs chậm ~70s)."""
    if not rows:
        return []
    url_keys: dict[str, set] = {}
    name_keys: dict[str, set] = {}
    for r in rows:
        if r["company_url"]:
            url_keys.setdefault(r["source"], set()).add(r["company_url"])
        if r["company"]:
            name_keys.setdefault(r["source"], set()).add(r["company"])
    # dict giữ bản enriched_at mới nhất trước (ORDER BY enriched_at DESC, first-wins)
    by_url: dict[tuple, sqlite3.Row] = {}
    by_name: dict[tuple, sqlite3.Row] = {}
    for col, keys, into in (("detail_url", url_keys, by_url), ("name", name_keys, by_name)):
        for s, vals in keys.items():
            marks = ",".join("?" * len(vals))
            for d in conn.execute(
                    f"SELECT source, {col} AS k, size_raw, bucket, num_employees FROM company_directory "
                    f"WHERE source=? AND {col} IN ({marks}) ORDER BY enriched_at DESC", (s, *vals)):
                into.setdefault((d["source"], d["k"]), d)
    out = []
    for r in rows:
        d = by_url.get((r["source"], r["company_url"])) or by_name.get((r["source"], r["company"]))
        out.append({**dict(r),
                    "company_size_raw": d["size_raw"] if d else None,
                    "company_bucket": d["bucket"] if d else None,
                    "company_num_employees": d["num_employees"] if d else None})
    return out


def _filtered(*, q: str = "", source: str = "", category: str = "", exp: str = "",
              tag: str = "", skill: str = "", level: str = "", salary_min: float = 0,
              it_only: int = 1, since_hours: int = 336, company_size: str = "",
              relevance_min: int = 0, company: str = "", status: str = "open", city: str = "",
              work_mode: str = "", role: str = "", first_seen_hours: int = 0,
              first_seen_today: int = 0):
    """Helper dùng chung: build FROM/WHERE cho mọi endpoint (jobs/stats/trend/meta)
    để filter nào cũng cập nhật mọi số liệu. Cột luôn prefix jobs. tránh ambiguous."""
    use_fts = bool(q.strip())
    if use_fts:
        where, params = ["jobs_fts MATCH ?"], [_fts_query(q)]
        frm = "jobs JOIN jobs_fts ON jobs.rowid = jobs_fts.rowid"
    else:
        where, params = ["1=1"], []
        frm = "jobs"
    if role:
        if not roles.split(role):
            raise HTTPException(422, "role must be a comma list of: " + ", ".join(roles.names()))
        where.append("role_matches(?, jobs.title, jobs.category)=1")
        params.append(",".join(roles.split(role)))
    if status not in ('open','closed','unknown','all'):
        raise HTTPException(422,'status must be open, closed, unknown or all')
    if status == 'open':
        where.append(details.open_condition())
    elif status == 'closed':
        where.append("(jobs.status='closed' OR (jobs.valid_through IS NOT NULL AND julianday(jobs.valid_through)<julianday('now')))")
    elif status == 'unknown':
        where.append("(jobs.status!='closed' AND NOT ("+details.open_condition()+") AND (jobs.valid_through IS NULL OR julianday(jobs.valid_through)>=julianday('now')))")
    if city:
        where.append('province_matches(jobs.city,?,0)=1');params.append(city)
    if work_mode:
        where.append('jobs.work_mode=?');params.append(work_mode)
    if it_only:
        where.append("jobs.is_it = 1")
    if relevance_min:
        where.append("COALESCE(jobs.relevance, 0) >= ?")
        params.append(relevance_min)
    if source:
        where.append("jobs.source=?")
        params.append(source)
    if company:
        where.append("jobs.company=?")
        params.append(company)
    if category:
        where.append("jobs.category=?")
        params.append(category)
    if exp:
        cond = _exp_cond(exp)
        if cond:
            where.append(cond.replace("exp_min", "jobs.exp_min", 1))
    if level:
        where.append("jobs.level=?")
        params.append(level)
    if salary_min:
        where.append("jobs.salary_max IS NOT NULL AND jobs.salary_max >= ?")
        params.append(salary_min)
    if tag:
        where.append("jobs.tags LIKE ?")
        params.append(_q_like(f'"{tag}"'))
    if skill:
        where.append("jobs.skills LIKE ?")
        params.append(_q_like(f'"{skill}"'))
    if since_hours:
        where.append("julianday(jobs.posted_at) >= julianday(?) AND julianday(jobs.posted_at)<=julianday('now')")
        params.append((datetime.now().astimezone() - timedelta(hours=since_hours)).isoformat())
        if status == "open":
            where.append("jobs.date_source='structured'")
    if first_seen_hours:
        # Lọc theo thời điểm CRAWLER phát hiện (first_seen_at), không phải ngày
        # đăng nguồn — job đăng cách đây 5 ngày nhưng hôm nay mới xuất hiện
        # trên listing vẫn thuộc nhóm này.
        where.append("julianday(jobs.first_seen_at) >= julianday(?)"
                     " AND julianday(jobs.first_seen_at) <= julianday('now')")
        params.append((datetime.now().astimezone() - timedelta(hours=first_seen_hours)).isoformat())
    if first_seen_today:
        # "Hôm nay" = từ 00:00 giờ Việt Nam (UTC+7), khác cửa sổ trượt 24h.
        where.append("julianday(jobs.first_seen_at) >= julianday("
                     "datetime('now','+7 hours','start of day','-7 hours'))"
                     " AND julianday(jobs.first_seen_at) <= julianday('now')")
    if company_size:
        # 2 EXISTS tách bạch (không OR trong 1 subquery) để mỗi nhánh dùng được
        # index (source,name)/(source,detail_url) — bộ lọc quy mô trong Inbox.
        where.append("(EXISTS (SELECT 1 FROM company_directory d WHERE d.source=jobs.source"
                     " AND d.detail_url=jobs.company_url AND d.bucket=?)"
                     " OR EXISTS (SELECT 1 FROM company_directory d WHERE d.source=jobs.source"
                     " AND d.name=jobs.company AND d.bucket=?))")
        params.extend([company_size, company_size])
    return frm, " AND ".join(where), params, use_fts


def _fts_query(q: str) -> str:
    """'java backend' → '"java" AND "backend"' (match mọi từ)."""
    terms = [t.strip('"') for t in q.split() if t.strip('" ')][:8]
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in terms) or '"__empty_search__"'


# Filter năm kinh nghiệm theo góc nhìn NGƯỜI TÌM VIỆC: chọn số năm mình có,
# hiện mọi job yêu cầu TỐI ĐA bao nhiêu năm (≤ N) — tức là việc mình đủ điều
# kiện apply. exp_min NULL (nguồn không ghi) chỉ hiện khi "Tất cả".
_EXP_BUCKETS = [
    ("0", "Fresher / Không YC", "<= 0"),
    ("1", "≤ 1 năm", "<= 1"),
    ("2", "≤ 2 năm", "<= 2"),
    ("3", "≤ 3 năm", "<= 3"),
    ("5", "≤ 5 năm", "<= 5"),
]


_LEVELS = ["intern", "fresher", "junior", "middle", "senior", "lead", "manager"]


_COMPANY_BUCKETS = ["<50", "50-100", "101-150", "151-300", "301-1000", "1000+"]


def _exp_cond(bucket: str) -> str | None:
    for value, _name, cond in _EXP_BUCKETS:
        if value == bucket:
            return f"exp_min {cond}"
    return None


@app.get("/api/meta")
def api_meta(q: str = "", source: str = "",
             category: str = "", exp: str = "", tag: str = "", skill: str = "",
             level: str = "", salary_min: float = 0, it_only: int = 1,
             since_hours: int = 336, relevance_min: int = 0, company: str = "", status: str = "open",
             city: str = "", work_mode: str = "", company_size: str = "", role: str = "",
             first_seen_hours: int = 0, first_seen_today: int = 0):
    """Facets (counts) cũng tính trên tập đã lọc — chọn filter nào, mọi số đều theo."""
    conn = db()
    frm, where_s, params, _ = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only, since_hours=since_hours, company_size=company_size,
        relevance_min=relevance_min, company=company, status=status, city=city, work_mode=work_mode,
        role=role, first_seen_hours=first_seen_hours, first_seen_today=first_seen_today)
    # Một pass duy nhất cho tags + skills (trước đây 2 pass × 5000 dòng)
    tag_counts: dict[str, int] = {}
    skill_counts: dict[str, int] = {}
    for tags_json, skills_json in conn.execute(
            f"SELECT jobs.tags, jobs.skills FROM {frm} WHERE {where_s} LIMIT 5000", params):
        try:
            for t in json.loads(tags_json or "[]"):
                t = t.strip()
                if t and len(t) > 2:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        except json.JSONDecodeError:
            pass
        try:
            for s in json.loads(skills_json or "[]"):
                skill_counts[s] = skill_counts.get(s, 0) + 1
        except json.JSONDecodeError:
            pass
    # GROUP BY gom sẵn thay 5 + 7 truy vấn per-bucket
    exp_rows = dict(conn.execute(
        f"""SELECT CASE WHEN jobs.exp_min <= 0 THEN '0' WHEN jobs.exp_min >= 5 THEN '5+'
                   ELSE CAST(CAST(jobs.exp_min AS INT) AS TEXT) END v, count(*) n
            FROM {frm} WHERE {where_s} AND jobs.exp_min IS NOT NULL GROUP BY 1""", params).fetchall())
    level_rows = dict(conn.execute(
        f"SELECT jobs.level, count(*) n FROM {frm} WHERE {where_s} AND jobs.level IS NOT NULL GROUP BY 1",
        params).fetchall())
    out = {
        "sources": [r["source"] for r in conn.execute("SELECT DISTINCT source FROM jobs")],
        "categories": [
            {"name": r["category"], "n": r["n"]}
            for r in conn.execute(
                f"SELECT jobs.category, count(*) n FROM {frm} WHERE {where_s}"
                " AND jobs.category != '' GROUP BY 1 ORDER BY n DESC LIMIT 30",
                params,
            )
        ],
        "experience": [
            {"value": value, "name": name, "n": exp_rows.get("5+" if value == "5" else value, 0)}
            for value, name, cond in _EXP_BUCKETS
        ],
        "top_tags": [{"name": k, "n": v} for k, v in
                     sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:40]],
        "top_skills": [{"name": k, "n": v} for k, v in
                       sorted(skill_counts.items(), key=lambda kv: kv[1], reverse=True)[:40]],
        "it_count": conn.execute("SELECT count(*) FROM jobs WHERE is_it=1").fetchone()[0],
        "non_it_count": conn.execute("SELECT count(*) FROM jobs WHERE is_it=0").fetchone()[0],
        "levels": [
            {"value": lv, "n": level_rows.get(lv, 0)}
            for lv in _LEVELS
        ],
        # Số job theo quy mô công ty (bucket) trên cùng bộ lọc — cho chip Quy mô
        # CT trong Inbox; mỗi bucket 1 query EXISTS đã index.
        "company_sizes": [
            {"bucket": b, "n": conn.execute(
                f"SELECT count(*) FROM {frm} WHERE {where_s} AND "
                "(EXISTS (SELECT 1 FROM company_directory d WHERE d.source=jobs.source"
                " AND d.detail_url=jobs.company_url AND d.bucket=?)"
                " OR EXISTS (SELECT 1 FROM company_directory d WHERE d.source=jobs.source"
                " AND d.name=jobs.company AND d.bucket=?))",
                params + [b, b]).fetchone()[0]}
            for b in _COMPANY_BUCKETS
        ],
    }
    # Số job theo từng hướng ứng tuyển — tính trên cùng bộ lọc NHƯNG bỏ `role`
    # để badge của từng role luôn hiển thị đúng số job sẽ nhận được khi chọn.
    frm_r, where_r, params_r, _ = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only, since_hours=since_hours,
        company_size=company_size, relevance_min=relevance_min, company=company,
        status=status, city=city, work_mode=work_mode, first_seen_hours=first_seen_hours,
        first_seen_today=first_seen_today)
    out["role_counts"] = {
        slug: conn.execute(
            f"SELECT count(*) FROM {frm_r} WHERE {where_r} AND role_matches(?, jobs.title, jobs.category)=1",
            params_r + [slug]).fetchone()[0]
        for slug in roles.names()
    }
    conn.close()
    return out


@app.get("/api/trend")
def api_trend(days: int = Query(14, ge=1, le=60), q: str = "", source: str = "",
              category: str = "", exp: str = "", tag: str = "", skill: str = "",
              level: str = "", salary_min: float = 0, it_only: int = 1, relevance_min: int = 0,
              company: str = "", status: str = "open", city: str = "", work_mode: str = "",
              company_size: str = "", since_hours: int = 336, role: str = "",
              first_seen_hours: int = 0, first_seen_today: int = 0):
    """Trend việc mới/ngày — tôn trọng filter hiện tại (trừ since_hours)."""
    since = (datetime.now().astimezone() - timedelta(days=days)).isoformat()
    conn = db()
    frm, where_s, params, _ = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only, company_size=company_size, since_hours=since_hours,
        relevance_min=relevance_min, company=company, status=status, city=city, work_mode=work_mode,
        role=role, first_seen_hours=first_seen_hours, first_seen_today=first_seen_today)
    rows = conn.execute(
        f"""SELECT date(jobs.posted_at,'+7 hours') d, jobs.source, count(*) n
           FROM {frm} WHERE {where_s} AND julianday(jobs.posted_at) >= julianday(?) GROUP BY 1, 2 ORDER BY 1""",
        params + [since],
    ).fetchall()
    sources = [r["source"] for r in conn.execute("SELECT DISTINCT source FROM jobs")]
    conn.close()
    out: dict[str, dict[str, dict[str, int]]] = {}
    for r in rows:
        out.setdefault(r["d"], {})  # type: ignore
        out[r["d"]][r["source"]] = r["n"]  # type: ignore
    return JSONResponse({
        "sources": sources,
        "days": [{**{"date": k}, **{s: v.get(s, 0) for s in sources}}
                 for k, v in sorted(out.items())],
    })


@app.get("/api/stats")
def api_stats(q: str = "", source: str = "",
              category: str = "", exp: str = "", tag: str = "", skill: str = "",
              level: str = "", salary_min: float = 0, it_only: int = 1,
              since_hours: int = 336, relevance_min: int = 0, company: str = "", status: str = "open",
              city: str = "", work_mode: str = "", company_size: str = "", role: str = "",
              first_seen_hours: int = 0, first_seen_today: int = 0):
    """Mọi KPI + chart phân bố đều tính trên tập đã lọc (giống danh sách job)."""
    conn = db()
    frm, where_s, params, _ = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only, since_hours=since_hours, company_size=company_size,
        relevance_min=relevance_min, company=company, status=status, city=city, work_mode=work_mode,
        role=role, first_seen_hours=first_seen_hours, first_seen_today=first_seen_today)
    # Lưu ý thứ tự bind params: placeholder trong SELECT đứng trước WHERE
    ts24 = (datetime.now().astimezone() - timedelta(hours=24)).isoformat()
    total, active, last24 = conn.execute(
        f"""SELECT count(*), sum(CASE WHEN {details.open_condition()} THEN 1 ELSE 0 END), sum(julianday(jobs.posted_at) >= julianday(?))
           FROM {frm} WHERE {where_s}""",
        [ts24] + params,
    ).fetchone()
    out = {"total": total, "active": active or 0, "new_24h": last24 or 0,
           "companies": conn.execute(
               f"SELECT count(DISTINCT jobs.company) FROM {frm} WHERE {where_s}"
               " AND jobs.company != ''", params).fetchone()[0],
           "generated_at": datetime.now().isoformat(timespec="seconds")}
    for label, sql in {
        "top_exp": f"""SELECT
               CASE WHEN jobs.exp_min <= 0 THEN '0' WHEN jobs.exp_min >= 5 THEN '5+'
                    ELSE CAST(CAST(jobs.exp_min AS INT) AS TEXT) END AS experience,
               count(*) n FROM {frm} WHERE {where_s} AND jobs.exp_min IS NOT NULL
               GROUP BY 1 ORDER BY MIN(jobs.exp_min)""",
        "top_categories": f"""SELECT jobs.category, count(*) n FROM {frm}
               WHERE {where_s} AND jobs.category != '' GROUP BY 1 ORDER BY n DESC LIMIT 12""",
        # giữ key cũ để frontend cũ không vỡ
        "topcv_top_exp": f"""SELECT
               CASE WHEN jobs.exp_min <= 0 THEN '0' WHEN jobs.exp_min >= 5 THEN '5+'
                    ELSE CAST(CAST(jobs.exp_min AS INT) AS TEXT) END AS experience,
               count(*) n FROM {frm} WHERE {where_s} AND jobs.exp_min IS NOT NULL
               GROUP BY 1 ORDER BY MIN(jobs.exp_min)""",
        "itviec_top_categories": f"""SELECT jobs.category, count(*) n FROM {frm}
               WHERE {where_s} AND jobs.category != '' GROUP BY 1 ORDER BY n DESC LIMIT 12""",
    }.items():
        out[label] = [dict(r) for r in conn.execute(sql, params)]
    # Queue: số job theo trạng thái review (áp filter hiện tại, không tính mark)
    queue = {}
    for k, cond in _MARK_CONDS.items():
        queue[k] = conn.execute(
            f"SELECT count(*) FROM {frm} LEFT JOIN job_marks"
            " ON job_marks.source=jobs.source AND job_marks.source_id=jobs.source_id"
            f" WHERE {where_s} AND {cond}",
            params).fetchone()[0]
    out["queue"] = queue
    conn.close()
    return out


@app.get('/api/job/{source}/{source_id}')
def api_job_detail(source: str,source_id: str):
    conn=db()
    row=conn.execute('SELECT * FROM jobs WHERE source=? AND source_id=?',(source,source_id)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404,'Job not found')
    result=dict(row)
    for field in ('tags','skills','matched'):
        result[field]=json.loads(result.get(field) or '[]')
    return result


@app.get('/api/health')
def api_health():
    conn=db()
    sources=[]
    for source in ('itviec','topcv','topdev','companies'):
        row=conn.execute("SELECT *, (julianday('now')-julianday(finished_at))*24 age_hours "
                         'FROM crawl_runs WHERE source=? AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1',(source,)).fetchone()
        result=dict(row) if row else {'source':source,'status':'never_run'}
        running=conn.execute('SELECT started_at FROM crawl_runs WHERE source=? AND finished_at IS NULL ORDER BY id DESC LIMIT 1',(source,)).fetchone()
        result['running_since']=running[0] if running else None
        result['healthy']=bool(row and row['finished_at'] and row['status'] in ('ok','partial')
                               and row['age_hours'] <= (3 if source=='companies' else 1))
        sources.append(result)
    counts=dict(conn.execute("SELECT count(*) total_jobs, sum(status='open') verified_open, "
                             'sum(detail_checked_at IS NOT NULL) detail_checked FROM jobs').fetchone())
    counts['recent_open']=conn.execute('SELECT count(*) FROM jobs WHERE '+details.open_condition()+
                                      " AND date_source='structured' AND julianday(posted_at)>=julianday('now','-14 days') AND julianday(posted_at)<=julianday('now')").fetchone()[0]
    counts['company_profiles']=conn.execute('SELECT count(*) FROM company_directory').fetchone()[0]
    conn.close()
    return {'status':'ok' if all(r['healthy'] for r in sources) else 'degraded',
            'sources':sources,'counts':counts,'generated_at':store.now_iso()}


@app.get('/api/runs')
def api_runs(limit: int=Query(30,ge=1,le=200)):
    conn=db()
    rows=[dict(r) for r in conn.execute('SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?',(limit,))]
    conn.close()
    return {'runs':rows}


# SPA fallback — đăng ký CUỐI để mọi route /api đã khớp trước. Router phía
# client (/inbox, /thong-ke, /cong-ty, deep-link có query) cần server trả
# index.html cho mọi path không phải API; refresh/F5 giữ nguyên trang.
@app.get('/{full_path:path}', response_class=HTMLResponse, include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith('api/'):
        raise HTTPException(404, 'Unknown API path')
    index = FRONTEND_DIST / 'index.html'
    if not index.is_file():
        raise HTTPException(503, 'Frontend chưa build — chạy npm run build trong frontend/')
    return HTMLResponse(index.read_text())
