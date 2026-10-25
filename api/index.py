"""API production cho Vercel serverless — Postgres (Supabase) thay SQLite.

Cùng contract với dashboard/main.py local để frontend dùng nguyên: mọi endpoint
/api/*, tham số và ngữ nghĩa lọc giữ nguyên. Khác biệt kiến trúc:
- Các hàm Python SQLite (province_matches/role_matches/open_condition) đã được
  sync script precompute thành cột: provinces text[], roles text[],
  effective_status/effective_open → ở đây chỉ lọc bằng index.
- Tìm từ khóa dùng ILIKE trên cột search (đủ cho quy mô ~vài nghìn job).
- Kết nối pooler Supabase qua env DATABASE_URL (IPv4-friendly cho serverless).
- Bảo mật: mọi request phải mang Bearer token do Supabase Auth cấp và đúng
  ALLOWED_EMAIL — xem require_user bên dưới. Đây là lớp enforce thật sự;
  AuthGate phía frontend chỉ là UX.

Chạy local: DATABASE_URL=... uvicorn api.index:app --port 8131
(bỏ qua login khi dev: AUTH_DISABLED=1 — chỉ có tác dụng ngoài Vercel)
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel


# ---- Xác thực: duy nhất email trong ALLOWED_EMAIL được gọi API --------------
#
# Verify bằng cách hỏi trực tiếp Supabase Auth (GET /auth/v1/user) với token —
# nguồn sự thật phía server, không phải tự giải JWT nên không phụ thuộc thuật
# toán ký (HS256 cũ hay signing key bất đối xứng mới). Kết quả dương tính được
# cache theo token (token sống ~1h) để một phiên dashboard chỉ gọi vài lần.

_TOKEN_CACHE: dict[str, tuple[float, str]] = {}  # token -> (hạn cache, email)
_TOKEN_TTL = 300.0  # giây


def _auth_config() -> tuple[str, str, str]:
    url = (os.environ.get("SUPABASE_URL")
           or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or ""
    email = (os.environ.get("ALLOWED_EMAIL") or "").strip().lower()
    if not (url and key and email):
        raise HTTPException(
            503, "API chưa cấu hình auth: cần SUPABASE_URL, "
                 "SUPABASE_PUBLISHABLE_KEY, ALLOWED_EMAIL")
    return url, key, email


def _verify_token(token: str) -> str:
    """Trả về email nếu token hợp lệ VÀ đúng allowlist; ngược lại 401.

    Fail-closed: Supabase không trả lời được thì coi như không hợp lệ.
    """
    url, key, allowed = _auth_config()
    now = time.monotonic()
    if len(_TOKEN_CACHE) > 256:  # dọn cache trước khi phình
        for t, (exp, _e) in list(_TOKEN_CACHE.items()):
            if exp <= now:
                _TOKEN_CACHE.pop(t, None)
    cached = _TOKEN_CACHE.get(token)
    if cached and cached[0] > now:
        return cached[1]
    req = urllib.request.Request(
        f"{url}/auth/v1/user",
        headers={"apikey": key, "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            user = json.loads(r.read().decode("utf-8"))
        email = str(user.get("email") or "").strip().lower()
    except (urllib.error.URLError, OSError, ValueError):
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn",
                            headers={"WWW-Authenticate": "Bearer"})
    if email != allowed:
        raise HTTPException(401, "Tài khoản không có quyền truy cập",
                            headers={"WWW-Authenticate": "Bearer"})
    _TOKEN_CACHE[token] = (now + _TOKEN_TTL, email)
    return email


def require_user(authorization: str = Header(default="")) -> str:
    """Dependency gắn cho mọi route — trả về email đã verify, hoặc 401."""
    if os.environ.get("AUTH_DISABLED") == "1" and os.environ.get("VERCEL") != "1":
        return "local"  # chỉ để dev máy cá nhân khỏi đặt token
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Thiếu Bearer token — hãy đăng nhập",
                            headers={"WWW-Authenticate": "Bearer"})
    return _verify_token(token.strip())


app = FastAPI(title="Săn Việc API", version="1.0.0",
              dependencies=[Depends(require_user)])

ROLE_SLUGS = ["de", "backend", "fullstack", "ds"]
EXP_BUCKETS = [("0", "Fresher / Không YC", 0), ("1", "≤ 1 năm", 1),
               ("2", "≤ 2 năm", 2), ("3", "≤ 3 năm", 3), ("5", "≤ 5 năm", 5)]
LEVELS = ["intern", "fresher", "junior", "middle", "senior", "lead", "manager"]
COMPANY_BUCKETS = ["<50", "50-100", "101-150", "151-300", "301-1000", "1000+"]
PROVINCE_PRIORITY = {"Hồ Chí Minh": 0, "Hà Nội": 1, "Đà Nẵng": 2}

MARK_CONDS = {
    "unseen": "COALESCE(m.viewed,0)=0 AND COALESCE(m.applied,0)=0 AND COALESCE(m.hidden,0)=0",
    "viewed": "COALESCE(m.viewed,0)=1 AND COALESCE(m.applied,0)=0 AND COALESCE(m.hidden,0)=0",
    "applied": "COALESCE(m.applied,0)=1",
    "hidden": "COALESCE(m.hidden,0)=1",
    "starred": "COALESCE(m.starred,0)=1",
}


class _DictConn(psycopg2.extensions.connection):
    """Mọi cursor mặc định trả dict (RealDictRow) — tiện rowjson."""
    def cursor(self, *args, **kwargs):
        kwargs.setdefault("cursor_factory", psycopg2.extras.RealDictCursor)
        return super().cursor(*args, **kwargs)


def db():
    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise HTTPException(503, "Thiếu DATABASE_URL")
    conn = psycopg2.connect(url, connect_timeout=10,
                            options="-c statement_timeout=20000",
                            connection_factory=_DictConn)
    return conn


def _clean(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def rowjson(r):
    return {k: _clean(v) for k, v in dict(r).items()}


def _filtered(q="", source="", category="", exp="", tag="", skill="", level="",
              salary_min=0.0, it_only=1, since_hours=336, company_size="",
              relevance_min=0, company="", status="open", city="",
              work_mode="", role=""):
    """Build WHERE chung cho jobs/meta/stats/trend — mirror dashboard local."""
    where, params = ["1=1"], []
    if status not in ("open", "closed", "unknown", "all"):
        raise HTTPException(422, "status phải là open/closed/unknown/all")
    if status != "all":
        where.append("jobs.effective_status=%s")
        params.append(status)
    if it_only:
        where.append("jobs.is_it=1")
    if city:
        if city == "__unknown__":
            where.append("cardinality(jobs.provinces)=0")
        else:
            where.append("%s = ANY(jobs.provinces)")
            params.append(city)
    if work_mode:
        where.append("jobs.work_mode=%s"); params.append(work_mode)
    role_slugs = [s for s in (role or "").split(",") if s in ROLE_SLUGS]
    if role:
        if not role_slugs:
            raise HTTPException(422, "role phải là danh sách: " + ",".join(ROLE_SLUGS))
        where.append("jobs.roles && %s::text[]")
        params.append(role_slugs)
    if relevance_min:
        where.append("COALESCE(jobs.relevance,0) >= %s"); params.append(relevance_min)
    if source:
        where.append("jobs.source=%s"); params.append(source)
    if company:
        where.append("jobs.company=%s"); params.append(company)
    if category:
        where.append("jobs.category=%s"); params.append(category)
    if exp:
        for value, _name, years in EXP_BUCKETS:
            if value == exp:
                where.append("jobs.exp_min <= %s"); params.append(years)
                break
    if level:
        where.append("jobs.level=%s"); params.append(level)
    if salary_min:
        where.append("jobs.salary_max IS NOT NULL AND jobs.salary_max >= %s")
        params.append(salary_min)
    if skill:
        where.append("jobs.skills @> %s::jsonb"); params.append(json.dumps([skill]))
    if tag:
        where.append("jobs.tags @> %s::jsonb"); params.append(json.dumps([tag]))
    for term in [t for t in (q or "").split() if t.strip()][:8]:
        where.append("jobs.search ILIKE %s"); params.append(f"%{term}%")
    if since_hours:
        where.append("jobs.posted_at >= now() - make_interval(hours => %s)"
                     " AND jobs.posted_at <= now()")
        params.append(since_hours)
        if status == "open":
            where.append("jobs.date_source='structured'")
    if company_size:
        where.append("(EXISTS (SELECT 1 FROM company_directory d WHERE d.source=jobs.source"
                     " AND d.detail_url=jobs.company_url AND d.bucket=%s)"
                     " OR EXISTS (SELECT 1 FROM company_directory d WHERE d.source=jobs.source"
                     " AND d.name=jobs.company AND d.bucket=%s))")
        params.extend([company_size, company_size])
    return " AND ".join(where), params


JOB_SELECT = """SELECT jobs.source, jobs.source_id, jobs.title, jobs.company, jobs.url,
       jobs.city, jobs.salary, jobs.experience, jobs.exp_min, jobs.category,
       jobs.tags, jobs.skills, jobs.is_it, jobs.level, jobs.salary_min, jobs.salary_max,
       jobs.posted_text, jobs.posted_at, jobs.relevance, jobs.matched,
       jobs.first_seen_at, jobs.last_seen_at, jobs.is_new, jobs.status,
       jobs.status_reason, jobs.valid_through, jobs.date_source,
       jobs.detail_checked_at, jobs.work_mode, jobs.employment_type, jobs.company_url,
       jobs.effective_status,
       COALESCE(m.viewed,0) AS viewed, COALESCE(m.hidden,0) AS hidden,
       COALESCE(m.applied,0) AS applied, COALESCE(m.starred,0) AS starred
FROM jobs LEFT JOIN job_marks m ON m.source=jobs.source AND m.source_id=jobs.source_id"""


def _attach_company(cur, rows):
    if not rows:
        return rows
    urls, names = {}, {}
    for r in rows:
        if r.get("company_url"):
            urls.setdefault(r["source"], set()).add(r["company_url"])
        if r.get("company"):
            names.setdefault(r["source"], set()).add(r["company"])
    by = {}
    for col, keys in (("detail_url", urls), ("name", names)):
        for src, vals in keys.items():
            cur.execute(f"SELECT source, {col} AS k, size_raw, bucket, num_employees"
                        f" FROM company_directory WHERE source=%s AND {col} = ANY(%s)"
                        f" ORDER BY enriched_at DESC NULLS LAST", (src, list(vals)))
            for d in cur.fetchall():
                by.setdefault((d["source"], d["k"]), d)
    for r in rows:
        d = by.get((r["source"], r.get("company_url"))) or by.get((r["source"], r.get("company")))
        r["company_size_raw"] = d["size_raw"] if d else None
        r["company_bucket"] = d["bucket"] if d else None
        r["company_num_employees"] = d["num_employees"] if d else None
    return rows


@app.get("/api/jobs")
def api_jobs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
             source="", q="", category="", exp="", tag="", skill="", level="",
             salary_min=0.0, it_only=1, show_hidden=0, company_size="",
             since_hours=336, sort="auto", relevance_min=0, mark="all",
             company="", status="open", city="", work_mode="", role=""):
    where, params = _filtered(q=q, source=source, category=category, exp=exp,
                              tag=tag, skill=skill, level=level, salary_min=salary_min,
                              it_only=it_only, since_hours=since_hours,
                              company_size=company_size, relevance_min=relevance_min,
                              company=company, status=status, city=city,
                              work_mode=work_mode, role=role)
    if mark in MARK_CONDS:
        where += f" AND {MARK_CONDS[mark]}"
    elif not show_hidden:
        where += " AND COALESCE(m.hidden,0)=0"
    order = {"posted": "jobs.posted_at DESC NULLS LAST",
             "new": "jobs.last_seen_at DESC",
             "salary": "jobs.salary_max DESC NULLS LAST"}.get(
        sort, "COALESCE(jobs.relevance,0) DESC, jobs.posted_at DESC NULLS LAST")
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM jobs LEFT JOIN job_marks m"
                        " ON m.source=jobs.source AND m.source_id=jobs.source_id"
                        f" WHERE {where}", params)
            total = cur.fetchone()["count"]
            cur.execute(f"{JOB_SELECT} WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s",
                        params + [limit, offset])
            rows = [rowjson(r) for r in cur.fetchall()]
            _attach_company(cur, rows)
        return JSONResponse({"total": total, "jobs": rows})
    finally:
        conn.close()


@app.get("/api/meta")
def api_meta(source="", q="", category="", exp="", tag="", skill="", level="",
             salary_min=0.0, it_only=1, since_hours=336, relevance_min=0,
             company="", status="open", city="", work_mode="", company_size="", role=""):
    where, params = _filtered(q=q, source=source, category=category, exp=exp, tag=tag,
                              skill=skill, level=level, salary_min=salary_min,
                              it_only=it_only, since_hours=since_hours,
                              company_size=company_size, relevance_min=relevance_min,
                              company=company, status=status, city=city,
                              work_mode=work_mode, role=role)
    where_no_role, params_no_role = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only, since_hours=since_hours,
        company_size=company_size, relevance_min=relevance_min, company=company,
        status=status, city=city, work_mode=work_mode, role="")
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT source FROM jobs ORDER BY 1")
            out = {"sources": [r["source"] for r in cur.fetchall()]}
            cur.execute(f"SELECT category name, count(*) n FROM jobs WHERE {where}"
                        " AND category != '' GROUP BY 1 ORDER BY n DESC LIMIT 30", params)
            out["categories"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT CASE WHEN exp_min<=0 THEN '0' WHEN exp_min>=5 THEN '5+'"
                        " ELSE exp_min::int::text END v, count(*) n FROM jobs"
                        f" WHERE {where} AND exp_min IS NOT NULL GROUP BY 1", params)
            exp_rows = {r["v"]: r["n"] for r in cur.fetchall()}
            out["experience"] = [{"value": v, "name": name,
                                  "n": exp_rows.get("5+" if v == "5" else v, 0)}
                                 for v, name, _y in EXP_BUCKETS]
            cur.execute(f"SELECT level, count(*) n FROM jobs WHERE {where}"
                        " AND level IS NOT NULL AND level != '' GROUP BY 1", params)
            lv = {r["level"]: r["n"] for r in cur.fetchall()}
            out["levels"] = [{"value": x, "n": lv.get(x, 0)} for x in LEVELS]
            cur.execute(f"SELECT skills, tags FROM jobs WHERE {where} LIMIT 5000", params)
            skills, tags = {}, {}
            for r in cur.fetchall():
                for s in (r["skills"] or []):
                    if s and len(s) > 2:
                        skills[s] = skills.get(s, 0) + 1
                for t in (r["tags"] or []):
                    if t and len(t) > 2:
                        tags[t] = tags.get(t, 0) + 1
            out["top_skills"] = [{"name": k, "n": v} for k, v in
                                 sorted(skills.items(), key=lambda kv: -kv[1])[:40]]
            out["top_tags"] = [{"name": k, "n": v} for k, v in
                               sorted(tags.items(), key=lambda kv: -kv[1])[:40]]
            out["role_counts"] = {}
            for slug in ROLE_SLUGS:
                cur.execute(f"SELECT count(*) n FROM jobs WHERE {where_no_role}"
                            " AND roles && %s::text[]", params_no_role + [[slug]])
                out["role_counts"][slug] = cur.fetchone()["n"]
            out["company_sizes"] = []
            for b in COMPANY_BUCKETS:
                cur.execute(f"SELECT count(*) n FROM jobs WHERE {where_no_role}"
                            " AND (EXISTS (SELECT 1 FROM company_directory d"
                            " WHERE d.source=jobs.source AND d.detail_url=jobs.company_url"
                            " AND d.bucket=%s) OR EXISTS (SELECT 1 FROM company_directory d"
                            " WHERE d.source=jobs.source AND d.name=jobs.company"
                            " AND d.bucket=%s))", params_no_role + [b, b])
                out["company_sizes"].append({"bucket": b, "n": cur.fetchone()["n"]})
            out["it_count"] = 0
            out["non_it_count"] = 0
            cur.execute("SELECT count(*) FILTER (WHERE is_it=1) a,"
                        " count(*) FILTER (WHERE is_it=0) b FROM jobs")
            itrow = cur.fetchone()
            out["it_count"], out["non_it_count"] = itrow["a"], itrow["b"]
        return JSONResponse(out)
    finally:
        conn.close()


@app.get("/api/stats")
def api_stats(source="", q="", category="", exp="", tag="", skill="", level="",
              salary_min=0.0, it_only=1, since_hours=336, relevance_min=0,
              company="", status="open", city="", work_mode="", company_size="", role=""):
    where, params = _filtered(q=q, source=source, category=category, exp=exp, tag=tag,
                              skill=skill, level=level, salary_min=salary_min,
                              it_only=it_only, since_hours=since_hours,
                              company_size=company_size, relevance_min=relevance_min,
                              company=company, status=status, city=city,
                              work_mode=work_mode, role=role)
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) total,"
                        " count(*) FILTER (WHERE effective_status='open') active,"
                        " count(*) FILTER (WHERE posted_at >= now() - interval '24 hours') last24,"
                        " count(DISTINCT company) FILTER (WHERE company != '') companies"
                        f" FROM jobs WHERE {where}", params)
            row = cur.fetchone()
            out = {**dict(row), "generated_at": datetime.now().astimezone().isoformat(timespec="seconds")}
            cur.execute("SELECT CASE WHEN exp_min<=0 THEN '0' WHEN exp_min>=5 THEN '5+'"
                        " ELSE exp_min::int::text END experience, count(*) n FROM jobs"
                        f" WHERE {where} AND exp_min IS NOT NULL GROUP BY 1"
                        " ORDER BY MIN(exp_min)", params)
            out["top_exp"] = out["topcv_top_exp"] = [dict(r) for r in cur.fetchall()]
            cur.execute(f"SELECT category, count(*) n FROM jobs WHERE {where}"
                        " AND category != '' GROUP BY 1 ORDER BY n DESC LIMIT 12", params)
            cats = [dict(r) for r in cur.fetchall()]
            out["top_categories"] = out["itviec_top_categories"] = cats
            out["queue"] = {}
            for k, cond in MARK_CONDS.items():
                cur.execute("SELECT count(*) n FROM jobs LEFT JOIN job_marks m"
                            " ON m.source=jobs.source AND m.source_id=jobs.source_id"
                            f" WHERE {where} AND {cond}", params)
                out["queue"][k] = cur.fetchone()["n"]
        return JSONResponse(out)
    finally:
        conn.close()


@app.get("/api/trend")
def api_trend(days: int = Query(14, ge=1, le=60), q: str = "", source: str = "",
              category: str = "", exp: str = "", tag: str = "", skill: str = "",
              level: str = "", salary_min: float = 0, it_only: int = 1,
              relevance_min: int = 0, company: str = "", status: str = "open",
              city: str = "", work_mode: str = "", company_size: str = "", role: str = ""):
    """Trend việc mới/ngày — tôn trọng filter hiện tại (trừ since_hours)."""
    where, params = _filtered(q=q, source=source, category=category, exp=exp, tag=tag,
                              skill=skill, level=level, salary_min=salary_min,
                              it_only=it_only, since_hours=0, company_size=company_size,
                              relevance_min=relevance_min, company=company, status=status,
                              city=city, work_mode=work_mode, role=role)
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT source FROM jobs ORDER BY 1")
            sources = [r["source"] for r in cur.fetchall()]
            cur.execute(f"SELECT (posted_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date d,"
                        f" source, count(*) n FROM jobs WHERE {where}"
                        " AND posted_at >= now() - make_interval(days => %s)"
                        " GROUP BY 1, 2 ORDER BY 1", params + [days])
            agg = {}
            for r in cur.fetchall():
                agg.setdefault(str(r["d"]), {})[r["source"]] = r["n"]
        return JSONResponse({"sources": sources,
                             "days": [{"date": k, **{s: v.get(s, 0) for s in sources}}
                                      for k, v in sorted(agg.items())]})
    finally:
        conn.close()


@app.get("/api/job/{source}/{source_id}")
def api_job_detail(source: str, source_id: str):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM jobs WHERE source=%s AND source_id=%s",
                        (source, source_id))
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        return JSONResponse(rowjson(row))
    finally:
        conn.close()


class MarkBody(BaseModel):
    source: str
    source_id: str
    viewed: int | None = None
    hidden: int | None = None
    applied: int | None = None
    starred: int | None = None


@app.post("/api/mark")
def api_mark(body: MarkBody):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO job_marks(source, source_id, viewed, hidden, applied, starred, marked_at)
                           VALUES (%s,%s,%s,%s,%s,%s,now())
                           ON CONFLICT (source, source_id) DO UPDATE SET
                             viewed=COALESCE(%s, job_marks.viewed),
                             hidden=COALESCE(%s, job_marks.hidden),
                             applied=COALESCE(%s, job_marks.applied),
                             starred=COALESCE(%s, job_marks.starred),
                             marked_at=now()
                           RETURNING viewed, hidden, applied, starred""",
                        (body.source, body.source_id,
                         body.viewed or 0, body.hidden or 0, body.applied or 0,
                         body.starred or 0,
                         body.viewed, body.hidden, body.applied, body.starred))
            out = dict(cur.fetchone())
        conn.commit()
        return {"ok": True, **out}
    finally:
        conn.close()


@app.get("/api/locations")
def api_locations():
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT p FROM jobs, unnest(provinces) p")
            provs = {r["p"] for r in cur.fetchall()}
            cur.execute("SELECT DISTINCT p FROM company_directory, unnest(provinces) p")
            provs |= {r["p"] for r in cur.fetchall()}
        ordered = sorted(provs, key=lambda n: (PROVINCE_PRIORITY.get(n, 3), n))
        return {"provinces": [{"value": n, "label": "TP. Hồ Chí Minh" if n == "Hồ Chí Minh" else n}
                              for n in ordered]}
    finally:
        conn.close()


@app.get("/api/health")
def api_health():
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) total_jobs,"
                        " count(*) FILTER (WHERE effective_status='open') verified_open,"
                        " count(*) FILTER (WHERE detail_checked_at IS NOT NULL) detail_checked,"
                        " count(*) FILTER (WHERE effective_status='open'"
                        "   AND date_source='structured'"
                        "   AND posted_at >= now() - interval '14 days'"
                        "   AND posted_at <= now()) recent_open,"
                        " (SELECT count(*) FROM company_directory) company_profiles FROM jobs")
            counts = dict(cur.fetchone())
            sources = []
            for src in ("itviec", "topcv", "topdev", "companies"):
                cur.execute("SELECT source, status, finished_at, note FROM crawl_runs"
                            " WHERE source=%s AND finished_at IS NOT NULL"
                            " ORDER BY id DESC LIMIT 1", (src,))
                r = cur.fetchone()
                item = dict(r) if r else {"source": src, "status": "never_run"}
                item["healthy"] = bool(r and r["status"] in ("ok", "partial")
                                       and r["finished_at"]
                                       and datetime.now(r["finished_at"].tzinfo) - r["finished_at"]
                                       < timedelta(hours=3 if src == "companies" else 1))
                sources.append(item)
        return {"status": "ok" if all(s["healthy"] for s in sources) else "degraded",
                "sources": sources, "counts": counts,
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    finally:
        conn.close()


# ---- Công ty ----------------------------------------------------------------

_CO_EMPTY = "('','unknown','n/a','na','null','none','-','—')"


def _company_where(q="", source="", bucket="", hiring=0, it_only=0, city="",
                   missing_fields="", missing_mode="all"):
    where, params = ["1=1"], []
    if source:
        where.append("d.source=%s"); params.append(source)
    if bucket:
        where.append("d.bucket=%s"); params.append(bucket)
    if q:
        where.append("(d.name ILIKE %s OR d.industry ILIKE %s OR d.description ILIKE %s)")
        params.extend([f"%{q}%"] * 3)
    if it_only:
        where.append("d.it_status IN ('technology','it_department')")
    if city:
        if city == "__unknown__":
            where.append("COALESCE(jc.n,0)+COALESCE(jn.n,0) = 0")
        else:
            where.append("(%s = ANY(d.provinces) OR COALESCE(jc.n,0)+COALESCE(jn.n,0) > 0)")
            params.append(city)
    if hiring:
        where.append("COALESCE(jc.n,0)+COALESCE(jn.n,0) > 0")
    selected = [f for f in (missing_fields or "").split(",") if f]
    if selected:
        cols = {"size": "size_raw", "industry": "industry", "website": "website",
                "address": "address", "description": "description"}
        conds = [f"(COALESCE(LOWER(TRIM(d.{cols[f]})), '') IN {_CO_EMPTY})"
                 for f in selected if f in cols]
        joiner = " AND " if missing_mode == "all" else " OR "
        if conds:
            where.append("(" + joiner.join(conds) + ")")
    return " AND ".join(where), params


_JOBS_CTES = """WITH jc AS (SELECT source, company_url k, count(*) n FROM jobs
                WHERE effective_status='open' AND company_url IS NOT NULL {city} GROUP BY 1,2),
     jn AS (SELECT source, company k, count(*) n, array_agg(DISTINCT category) cats,
                   array_agg(DISTINCT r) roless
            FROM jobs, unnest(roles) r
            WHERE effective_status='open' AND company IS NOT NULL {city} GROUP BY 1,2)"""


@app.get("/api/companies")
def api_companies(q="", source="", bucket="", hiring=0, it_only=0, city="",
                  missing_fields="", missing_mode="all",
                  limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    where, params = _company_where(q, source, bucket, hiring, it_only, city,
                                   missing_fields, missing_mode)
    city_sql = ("AND %s = ANY(provinces)" if city and city != "__unknown__" else "")
    city_params = [city] if city_sql else []
    ctes = _JOBS_CTES.replace("{city}", city_sql)
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(ctes + f" SELECT count(*) FROM company_directory d"
                        f" LEFT JOIN jc ON jc.source=d.source AND jc.k=d.detail_url"
                        f" LEFT JOIN jn ON jn.source=d.source AND jn.k=d.name"
                        f" WHERE {where}", city_params + city_params + params)
            total = cur.fetchone()["count"]
            cur.execute(ctes + f"""SELECT d.*, COALESCE(jc.n,0)+COALESCE(jn.n,0) job_count,
                           jn.cats, jn.roless
                    FROM company_directory d
                    LEFT JOIN jc ON jc.source=d.source AND jc.k=d.detail_url
                    LEFT JOIN jn ON jn.source=d.source AND jn.k=d.name
                    WHERE {where}
                    ORDER BY job_count DESC, (d.it_status!='unknown') DESC, d.name
                    LIMIT %s OFFSET %s""",
                        city_params + city_params + params + [limit, offset])
            companies = []
            for r in cur.fetchall():
                companies.append(_company_row(r))
        return JSONResponse({"total": total, "companies": companies,
                             "count_semantics": "source profiles; may overlap across sources"})
    finally:
        conn.close()


def _company_row(r):
    out = rowjson(r)
    out["company"] = out.get("name")
    out["company_slug"] = out.get("slug")
    out["fetched_at"] = out.get("enriched_at")
    cats = out.pop("cats", None) or []
    counts = {}
    for c in cats:
        if c:
            counts[c] = counts.get(c, 0) + 1
    out["hiring_roles"] = [{"name": k, "n": v} for k, v in
                           sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    out["hiring_role_tags"] = sorted({x for x in (out.pop("roless", None) or [])
                                      if x in ROLE_SLUGS})
    out["is_hiring"] = int((out.get("job_count") or 0) > 0)
    return out


@app.get("/api/company-stats")
def api_company_stats(q="", source="", bucket="", hiring=0, it_only=0, city="",
                      missing_fields="", missing_mode="all"):
    where, params = _company_where(q, source, bucket, hiring, it_only, city,
                                   missing_fields, missing_mode)
    city_sql = ("AND %s = ANY(provinces)" if city and city != "__unknown__" else "")
    city_params = [city] if city_sql else []
    ctes = _JOBS_CTES.replace("{city}", city_sql)
    conn = db()
    try:
        with conn.cursor() as cur:
            base = (f" FROM company_directory d"
                    f" LEFT JOIN jc ON jc.source=d.source AND jc.k=d.detail_url"
                    f" LEFT JOIN jn ON jn.source=d.source AND jn.k=d.name"
                    f" WHERE {where}")
            cur.execute(ctes + f"SELECT count(*) total,"
                        " count(*) FILTER (WHERE bucket IS NOT NULL) enriched,"
                        " count(*) FILTER (WHERE COALESCE(website,'') NOT IN " + _CO_EMPTY + ") websites,"
                        " count(*) FILTER (WHERE COALESCE(address,'') NOT IN " + _CO_EMPTY + ") addresses,"
                        " count(*) FILTER (WHERE it_status!='unknown') it_profiles" + base,
                        city_params + city_params + params)
            result = dict(cur.fetchone())
            cur.execute(ctes + "SELECT count(*) h" + base
                        + " AND COALESCE(jc.n,0)+COALESCE(jn.n,0) > 0",
                        city_params + city_params + params)
            result["hiring"] = cur.fetchone()["h"]
            cur.execute(ctes + f"SELECT bucket, count(*) n" + base
                        + " AND bucket IS NOT NULL GROUP BY 1",
                        city_params + city_params + params)
            result["buckets"] = [dict(r) for r in cur.fetchall()]
            cur.execute(ctes + f"SELECT d.source, count(*) n,"
                        " count(*) FILTER (WHERE enriched_at IS NOT NULL) checked" + base
                        + " GROUP BY 1", city_params + city_params + params)
            result["by_source"] = [dict(r) for r in cur.fetchall()]
            result["missing_counts"] = {}
            for f, col in (("size", "size_raw"), ("industry", "industry"),
                           ("website", "website"), ("address", "address"),
                           ("description", "description")):
                cur.execute(ctes + f"SELECT count(*) n" + base +
                            f" AND COALESCE(LOWER(TRIM(d.{col})), '') IN {_CO_EMPTY}",
                            city_params + city_params + params)
                result["missing_counts"][f] = cur.fetchone()["n"]
        return JSONResponse(result)
    finally:
        conn.close()


@app.get("/api/companies/export")
def export_companies(q="", source="", bucket="", hiring=0, it_only=0, city="",
                     missing_fields="", missing_mode="all"):
    where, params = _company_where(q, source, bucket, hiring, it_only, city,
                                   missing_fields, missing_mode)
    conn = db()
    fields = ["source", "slug", "name", "name_exact", "detail_url", "website",
              "address", "industry", "size_raw", "description", "company_type",
              "country", "working_days", "overtime", "tech_stack", "benefits",
              "public_links", "it_status", "it_evidence", "enriched_at",
              "enrichment_error"]

    def generate():
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {','.join('d.'+f for f in fields)}"
                            f" FROM company_directory d WHERE {where} LIMIT 50000", params)
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(fields)
                yield "\ufeff" + buf.getvalue()
                for row in cur.fetchall():
                    buf.seek(0)
                    buf.truncate(0)
                    w.writerow([("'"+v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else
                                 json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                                for v in dict(row).values()])
                    yield buf.getvalue()
        finally:
            conn.close()

    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="companies.csv"'})
