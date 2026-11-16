"""API production cho Vercel serverless — Postgres (Supabase) thay SQLite.

Cùng contract với dashboard/main.py local để frontend dùng nguyên: mọi endpoint
/api/*, tham số và ngữ nghĩa lọc giữ nguyên. Khác biệt kiến trúc:
- Các hàm Python SQLite (province_matches/role_matches/open_condition) đã được
  sync script precompute thành cột: provinces text[], roles text[],
  effective_status/effective_open → ở đây chỉ lọc bằng index.
- Tìm từ khóa bỏ dấu trên cột search (đủ cho quy mô ~vài nghìn job).
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
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
import psycopg2.pool
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


app = FastAPI(title="Job Hunt API", version="1.0.0",
              dependencies=[Depends(require_user)])

ROLE_SLUGS = ["de", "backend", "fullstack", "ds"]
EXP_BUCKETS = [("0", "Fresher / Không YC", 0), ("1", "≤ 1 năm", 1),
               ("2", "≤ 2 năm", 2), ("3", "≤ 3 năm", 3), ("5", "≤ 5 năm", 5)]
LEVELS = ["intern", "fresher", "junior", "middle", "senior", "lead", "manager"]
COMPANY_BUCKETS = ["<50", "50-100", "101-150", "151-300", "301-1000", "1000+"]
PROVINCE_PRIORITY = {"Hồ Chí Minh": 0, "Hà Nội": 1, "Đà Nẵng": 2}

# Tìm kiếm không dấu: FTS SQLite bỏ dấu tự động, còn Postgres thì không. Chuẩn
# hóa cả cột lẫn từ khóa để "cong ty co phan" khớp "CÔNG TY CỔ PHẦN".
_FOLD_FROM = (
    "àáảãạăằắẳẵặâầấẩẫậ"
    "èéẻẽẹêềếểễệ"
    "ìíỉĩị"
    "òóỏõọôồốổỗộơờớởỡợ"
    "ùúủũụưừứửữự"
    "ỳýỷỹỵ"
    "đ"
)
_FOLD_TO = "a" * 17 + "e" * 11 + "i" * 5 + "o" * 17 + "u" * 11 + "y" * 5 + "d"


def _fold_sql(column: str) -> str:
    return f"translate(lower(COALESCE({column}, '')), '{_FOLD_FROM}', '{_FOLD_TO}')"


def _fold_text(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


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


_POOL_LOCK = threading.Lock()
_POOLS: dict[str, psycopg2.pool.ThreadedConnectionPool] = {}
_LAST_USED: dict[int, float] = {}
_IDLE_CHECK = 120.0


def _pool_for(url: str) -> psycopg2.pool.ThreadedConnectionPool:
    pool = _POOLS.get(url)
    if pool is None:
        with _POOL_LOCK:
            pool = _POOLS.get(url)
            if pool is None:
                pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 8, url, connect_timeout=10,
                    options="-c statement_timeout=20000",
                    connection_factory=_DictConn)
                _POOLS[url] = pool
    return pool


class _PooledConn:
    def __init__(self, pool, raw):
        self._pool = pool
        self._raw = raw

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def close(self):
        raw = self._raw
        if raw is None:
            return
        self._raw = None
        if not raw.autocommit:
            try:
                raw.rollback()
            except Exception:
                try:
                    raw.close()
                except Exception:
                    pass
                return
        _LAST_USED[id(raw)] = time.monotonic()
        try:
            self._pool.putconn(raw)
        except Exception:
            _LAST_USED.pop(id(raw), None)
            try:
                raw.close()
            except Exception:
                pass


def _valid_conn(raw) -> bool:
    last = _LAST_USED.get(id(raw))
    if last is None or time.monotonic() - last < _IDLE_CHECK:
        return True
    try:
        with raw.cursor() as cur:
            cur.execute("SELECT 1")
        _LAST_USED[id(raw)] = time.monotonic()
        return True
    except Exception:
        return False


def db():
    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise HTTPException(503, "Thiếu DATABASE_URL")
    pool = _pool_for(url)
    raw = pool.getconn()
    raw.autocommit = True
    if not _valid_conn(raw):
        _LAST_USED.pop(id(raw), None)
        try:
            raw.close()
        except Exception:
            pass
        try:
            pool.putconn(raw, close=True)
        except Exception:
            pass
        raw = pool.getconn()
        raw.autocommit = True
    return _PooledConn(pool, raw)


def _clean(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def rowjson(r):
    return {k: _clean(v) for k, v in dict(r).items()}


def _filtered(q="", source="", category="", exp="", tag="", skill="", level="",
              salary_min=0.0, it_only=1, since_hours=336, company_size="",
              relevance_min=0, company="", company_url="", status="open", city="",
              work_mode="", role="", first_seen_hours=0, first_seen_today=0):
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
        if company_url:
            # Cùng một công ty có thể khớp qua tên hoặc URL hồ sơ nguồn.
            where.append("(jobs.company=%s OR jobs.company_url=%s)")
            params.extend([company, company_url])
        else:
            where.append("jobs.company=%s"); params.append(company)
    elif company_url:
        where.append("jobs.company_url=%s"); params.append(company_url)
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
    if first_seen_hours:
        # Thời điểm crawler PHÁT HIỆN job (first_seen_at) — khác posted_at là
        # ngày đăng trên nguồn; lọc "việc mới trong hôm nay" theo crawler.
        where.append("jobs.first_seen_at >= now() - make_interval(hours => %s)"
                     " AND jobs.first_seen_at <= now()")
        params.append(first_seen_hours)
    if first_seen_today:
        # "Hôm nay" = từ 00:00 giờ Việt Nam — khác cửa sổ trượt 24h.
        where.append("jobs.first_seen_at >= "
                     "(date_trunc('day', now() AT TIME ZONE 'Asia/Ho_Chi_Minh')"
                     " AT TIME ZONE 'Asia/Ho_Chi_Minh')"
                     " AND jobs.first_seen_at <= now()")
    for term in [t for t in (q or "").split() if t.strip()][:8]:
        folded = _fold_text(term)
        if folded:
            where.append(_fold_sql("jobs.search") + " LIKE %s")
            params.append(f"%{folded}%")
    if since_hours:
        where.append("jobs.posted_at >= now() - make_interval(hours => %s)"
                     " AND jobs.posted_at <= now()")
        params.append(since_hours)
        if status == "open":
            where.append("jobs.date_source='structured'")
    if company_size:
        where.append("EXISTS (SELECT 1 FROM company_directory d WHERE d.source=jobs.source"
                     " AND (d.detail_url=jobs.company_url OR d.name=jobs.company)"
                     " AND d.bucket=%s)")
        params.append(company_size)
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
    """Gắn hồ sơ quy mô cho trang hiện tại — 1 truy vấn/source thay vì 2."""
    if not rows:
        return rows
    urls, names = {}, {}
    for r in rows:
        if r.get("company_url"):
            urls.setdefault(r["source"], set()).add(r["company_url"])
        if r.get("company"):
            names.setdefault(r["source"], set()).add(r["company"])
    by_url, by_name = {}, {}
    for src in set(urls) | set(names):
        cur.execute(
            "SELECT source, name, detail_url, size_raw, bucket, num_employees"
            " FROM company_directory WHERE source=%s"
            " AND (detail_url = ANY(%s) OR name = ANY(%s))"
            " ORDER BY enriched_at DESC NULLS LAST",
            (src, list(urls.get(src, [])), list(names.get(src, []))))
        for d in cur.fetchall():
            if d["detail_url"]:
                by_url.setdefault((d["source"], d["detail_url"]), d)
            if d["name"]:
                by_name.setdefault((d["source"], d["name"]), d)
    for r in rows:
        d = (by_url.get((r["source"], r.get("company_url")))
             or by_name.get((r["source"], r.get("company"))))
        r["company_size_raw"] = d["size_raw"] if d else None
        r["company_bucket"] = d["bucket"] if d else None
        r["company_num_employees"] = d["num_employees"] if d else None
    return rows


@app.get("/api/jobs")
def api_jobs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
             source="", q="", category="", exp="", tag="", skill="", level="",
             salary_min: float = 0.0, it_only: int = 1, show_hidden: int = 0,
             company_size="", since_hours: int = 336, sort="auto",
             relevance_min: int = 0, mark="all",
             company="", company_url="", status="open", city="", work_mode="", role="",
             first_seen_hours: int = 0, first_seen_today: int = 0):
    where, params = _filtered(q=q, source=source, category=category, exp=exp,
                              tag=tag, skill=skill, level=level, salary_min=salary_min,
                              it_only=it_only, since_hours=since_hours,
                              company_size=company_size, relevance_min=relevance_min,
                              company=company, company_url=company_url,
                              status=status, city=city,
                              work_mode=work_mode, role=role,
                              first_seen_hours=first_seen_hours, first_seen_today=first_seen_today)
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
             salary_min: float = 0.0, it_only: int = 1, since_hours: int = 336,
             relevance_min: int = 0, company="", company_url="", status="open",
             city="", work_mode="", company_size="", role="",
             first_seen_hours: int = 0, first_seen_today: int = 0):
    where, params = _filtered(q=q, source=source, category=category, exp=exp, tag=tag,
                              skill=skill, level=level, salary_min=salary_min,
                              it_only=it_only, since_hours=since_hours,
                              company_size=company_size, relevance_min=relevance_min,
                              company=company, company_url=company_url, status=status,
                              city=city, work_mode=work_mode, role=role,
                              first_seen_hours=first_seen_hours, first_seen_today=first_seen_today)
    where_no_role, params_no_role = _filtered(
        q=q, source=source, category=category, exp=exp, tag=tag, skill=skill,
        level=level, salary_min=salary_min, it_only=it_only, since_hours=since_hours,
        company_size=company_size, relevance_min=relevance_min, company=company,
        company_url=company_url, status=status, city=city, work_mode=work_mode, role="",
        first_seen_hours=first_seen_hours, first_seen_today=first_seen_today)
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT source FROM jobs ORDER BY 1")
            out = {"sources": [r["source"] for r in cur.fetchall()]}
            cur.execute(f"""WITH j AS (SELECT category, exp_min, level FROM jobs
                           WHERE {where})
                SELECT 'category' kind, category k, count(*) n FROM j
                  WHERE category != '' GROUP BY 2
                UNION ALL
                SELECT 'experience', CASE WHEN exp_min<=0 THEN '0'
                       WHEN exp_min>=5 THEN '5+' ELSE exp_min::int::text END,
                       count(*) FROM j WHERE exp_min IS NOT NULL GROUP BY 2
                UNION ALL
                SELECT 'level', level, count(*) FROM j
                  WHERE level IS NOT NULL AND level != '' GROUP BY 2""", params)
            meta_rows = cur.fetchall()
            out["categories"] = [{"name": r["k"], "n": r["n"]}
                                 for r in sorted((r for r in meta_rows if r["kind"] == "category"),
                                                 key=lambda r: -r["n"])[:30]]
            exp_rows = {r["k"]: r["n"] for r in meta_rows if r["kind"] == "experience"}
            out["experience"] = [{"value": v, "name": name,
                                  "n": exp_rows.get("5+" if v == "5" else v, 0)}
                                 for v, name, _y in EXP_BUCKETS]
            lv = {r["k"]: r["n"] for r in meta_rows if r["kind"] == "level"}
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
            role_cols = ", ".join(
                f"count(*) FILTER (WHERE roles && %s::text[]) AS r{i}"
                for i in range(len(ROLE_SLUGS)))
            cur.execute(f"SELECT {role_cols} FROM jobs WHERE {where_no_role}",
                        [[slug] for slug in ROLE_SLUGS] + params_no_role)
            rc = cur.fetchone()
            out["role_counts"] = {slug: rc[f"r{i}"]
                                  for i, slug in enumerate(ROLE_SLUGS)}
            size_cols = ", ".join(
                f"count(*) FILTER (WHERE bucket=%s) AS b{i}"
                for i in range(len(COMPANY_BUCKETS)))
            cur.execute(f"""SELECT {size_cols}
                FROM (SELECT (SELECT d.bucket FROM company_directory d
                              WHERE d.source=jobs.source
                                AND (d.detail_url=jobs.company_url OR d.name=jobs.company)
                              LIMIT 1) bucket
                      FROM jobs WHERE {where_no_role}) x""",
                        list(COMPANY_BUCKETS) + params_no_role)
            size_row = cur.fetchone()
            out["company_sizes"] = [{"bucket": b, "n": size_row[f"b{i}"]}
                                    for i, b in enumerate(COMPANY_BUCKETS)]
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
              salary_min: float = 0.0, it_only: int = 1, since_hours: int = 336,
              relevance_min: int = 0, company="", company_url="", status="open",
              city="", work_mode="", company_size="", role="",
              first_seen_hours: int = 0, first_seen_today: int = 0):
    where, params = _filtered(q=q, source=source, category=category, exp=exp, tag=tag,
                              skill=skill, level=level, salary_min=salary_min,
                              it_only=it_only, since_hours=since_hours,
                              company_size=company_size, relevance_min=relevance_min,
                              company=company, company_url=company_url, status=status,
                              city=city, work_mode=work_mode, role=role,
                              first_seen_hours=first_seen_hours, first_seen_today=first_seen_today)
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
            queue_cols = ", ".join(
                f"count(*) FILTER (WHERE {cond}) AS {k}"
                for k, cond in MARK_CONDS.items())
            cur.execute("SELECT " + queue_cols + " FROM jobs"
                        " LEFT JOIN job_marks m"
                        " ON m.source=jobs.source AND m.source_id=jobs.source_id"
                        f" WHERE {where}", params)
            out["queue"] = dict(cur.fetchone())
        return JSONResponse(out)
    finally:
        conn.close()


@app.get("/api/trend")
def api_trend(days: int = Query(14, ge=1, le=60), q: str = "", source: str = "",
              category: str = "", exp: str = "", tag: str = "", skill: str = "",
              level: str = "", salary_min: float = 0, it_only: int = 1,
              relevance_min: int = 0, company: str = "", company_url: str = "",
              status: str = "open", city: str = "", work_mode: str = "",
              company_size: str = "", role: str = "",
              first_seen_hours: int = 0, first_seen_today: int = 0):
    """Trend việc mới/ngày — tôn trọng filter hiện tại (trừ since_hours)."""
    where, params = _filtered(q=q, source=source, category=category, exp=exp, tag=tag,
                              skill=skill, level=level, salary_min=salary_min,
                              it_only=it_only, since_hours=0, company_size=company_size,
                              relevance_min=relevance_min, company=company,
                              company_url=company_url, status=status,
                              city=city, work_mode=work_mode, role=role,
                              first_seen_hours=first_seen_hours, first_seen_today=first_seen_today)
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
            run_sources = ("itviec", "topcv", "topdev", "companies")
            cur.execute("SELECT DISTINCT ON (source) source, status, finished_at, note"
                        " FROM crawl_runs WHERE source = ANY(%s)"
                        " AND finished_at IS NOT NULL"
                        " ORDER BY source, id DESC", (list(run_sources),))
            runs = {r["source"]: r for r in cur.fetchall()}
            sources = []
            for src in run_sources:
                r = runs.get(src)
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
        folded = _fold_text(q)
        where.append(f"({_fold_sql('d.name')} LIKE %s OR {_fold_sql('d.slug')} LIKE %s"
                     f" OR {_fold_sql('d.industry')} LIKE %s)")
        params.extend([f"%{folded}%"] * 3)
    if it_only:
        where.append("d.it_status IN ('technology','it_department')")
    if city:
        if city == "__unknown__":
            where.append("COALESCE(jc.n, jn.n, 0) = 0")
        else:
            where.append("(%s = ANY(d.provinces) OR COALESCE(jc.n, jn.n, 0) > 0)")
            params.append(city)
    if hiring:
        where.append("COALESCE(jc.n, jn.n, 0) > 0")
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
                WHERE effective_status='open' AND is_it=1
                  AND company_url IS NOT NULL {city} GROUP BY 1,2),
     jn AS (SELECT jobs.source, jobs.company k, count(DISTINCT jobs.source_id) n,
                   array_agg(DISTINCT r) FILTER (WHERE r IS NOT NULL) roless
            FROM jobs LEFT JOIN LATERAL unnest(roles) r ON true
            WHERE effective_status='open' AND is_it=1
              AND company IS NOT NULL {city} GROUP BY 1,2),
     jcat AS (SELECT source, company k, jsonb_object_agg(category, n) cats
              FROM (SELECT source, company, category, count(*) n FROM jobs
                    WHERE effective_status='open' AND is_it=1
                      AND company IS NOT NULL {city}
                      AND category IS NOT NULL AND category != ''
                    GROUP BY 1,2,3) x GROUP BY 1,2)"""


@app.get("/api/companies")
def api_companies(q="", source="", bucket="", hiring: int = 0,
                  it_only: int = 0, city="",
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
            cur.execute(ctes + f"""SELECT d.*, COALESCE(jc.n, jn.n, 0) job_count,
                           jcat.cats, jn.roless, count(*) OVER() AS total_count
                    FROM company_directory d
                    LEFT JOIN jc ON jc.source=d.source AND jc.k=d.detail_url
                    LEFT JOIN jn ON jn.source=d.source AND jn.k=d.name
                    LEFT JOIN jcat ON jcat.source=d.source AND jcat.k=d.name
                    WHERE {where}
                    ORDER BY job_count DESC, (d.it_status!='unknown') DESC, d.name
                    LIMIT %s OFFSET %s""",
                        city_params * 3 + params + [limit, offset])
            rows = cur.fetchall()
            total = rows[0]["total_count"] if rows else 0
            if not rows and offset:
                cur.execute(ctes + f" SELECT count(*) FROM company_directory d"
                            f" LEFT JOIN jc ON jc.source=d.source AND jc.k=d.detail_url"
                            f" LEFT JOIN jn ON jn.source=d.source AND jn.k=d.name"
                            f" WHERE {where}", city_params * 3 + params)
                total = cur.fetchone()["count"]
            companies = [_company_row(r) for r in rows]
        return JSONResponse({"total": total, "companies": companies,
                             "count_semantics": "source profiles; may overlap across sources"})
    finally:
        conn.close()


def _company_row(r):
    out = rowjson(r)
    out.pop("total_count", None)
    out["company"] = out.get("name")
    out["company_slug"] = out.get("slug")
    out["fetched_at"] = out.get("enriched_at")
    cats = out.pop("cats", None) or {}
    counts = {c: n for c, n in cats.items() if c} if isinstance(cats, dict) else {}
    out["hiring_roles"] = [{"name": k, "n": v} for k, v in
                           sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    out["hiring_role_tags"] = sorted({x for x in (out.pop("roless", None) or [])
                                      if x in ROLE_SLUGS})
    out["is_hiring"] = int((out.get("job_count") or 0) > 0)
    return out


@app.get("/api/company-stats")
def api_company_stats(q="", source="", bucket="", hiring: int = 0,
                      it_only: int = 0, city="",
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
            missing = {f: col for f, col in (("size", "size_raw"),
                                              ("industry", "industry"),
                                              ("website", "website"),
                                              ("address", "address"),
                                              ("description", "description"))}
            missing_cols = ", ".join(
                f"count(*) FILTER (WHERE COALESCE(LOWER(TRIM(d.{col})), '')"
                f" IN {_CO_EMPTY}) AS missing_{f}"
                for f, col in missing.items())
            cur.execute(ctes + f"SELECT count(*) total,"
                        " count(*) FILTER (WHERE bucket IS NOT NULL) enriched,"
                        " count(*) FILTER (WHERE COALESCE(website,'') NOT IN " + _CO_EMPTY + ") websites,"
                        " count(*) FILTER (WHERE COALESCE(address,'') NOT IN " + _CO_EMPTY + ") addresses,"
                        " count(*) FILTER (WHERE it_status!='unknown') it_profiles,"
                        " count(*) FILTER (WHERE COALESCE(jc.n, jn.n, 0) > 0) hiring,"
                        + missing_cols + base,
                        city_params * 3 + params)
            result = dict(cur.fetchone())
            result["missing_counts"] = {f: result.pop(f"missing_{f}") for f in missing}
            cur.execute(ctes + f"SELECT bucket, count(*) n" + base
                        + " AND bucket IS NOT NULL GROUP BY 1",
                        city_params * 3 + params)
            result["buckets"] = [dict(r) for r in cur.fetchall()]
            cur.execute(ctes + f"SELECT d.source, count(*) n,"
                        " count(*) FILTER (WHERE enriched_at IS NOT NULL) checked" + base
                        + " GROUP BY 1", city_params * 3 + params)
            result["by_source"] = [dict(r) for r in cur.fetchall()]
        return JSONResponse(result)
    finally:
        conn.close()


@app.get("/api/companies/export")
def export_companies(q="", source="", bucket="", hiring: int = 0,
                     it_only: int = 0, city="",
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
