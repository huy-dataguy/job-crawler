# Săn Việc — Personal Job Intelligence Pipeline

> **EN one-liner:** A production-grade, end-to-end data pipeline that crawls 3
> Vietnamese IT job boards every 15 minutes, scores each job against my CV,
> enriches a 65k+ company directory, and serves a private web app — fully
> automated, self-hosted orchestration, zero monthly cost.

Crawler việc IT Việt Nam (**ITviec · TopCV · TopDev**) → chấm điểm khớp CV →
danh bạ 65k+ công ty → web riêng xem ở đâu cũng được. Một người thiết kế, xây
và vận hành toàn bộ.

## Dự án trong 30 giây

| Khía cạnh | Thực tế |
| --- | --- |
| Vấn đề | Tin tuyển dụng rải rác 3 nguồn, lẫn nhiều nghề; việc "đúng nghề, đủ kinh nghiệm" khó tìm tay |
| Giải pháp | Pipeline tự động 15 phút/lượt: crawl → chuẩn hoá → chấm khớp CV (0–100) → web inbox riêng |
| Quy mô dữ liệu | **65.374** hồ sơ công ty · **~1.900** job active (cửa sổ 14 ngày) · **96 lượt crawl/ngày** |
| Độ tươi | Job mới lên web production trong **<30 phút** kể từ khi nguồn đăng |
| Chi phí vận hành | **0đ/tháng** — Vercel + Supabase free tier, crawler chạy trên máy cá nhân |
| Kiểm thử | **60 pytest** (contract, parser, migration, serving) + boot gate verify |
| Hiệu năng đã tối ưu | `/api/jobs` 74s → 0.3s; `/api/companies` 21.7s → 0.2s; filter quy mô 13.9s → 0.07s |
| Vận hành | 1 lệnh check 7 tầng (Windmill → crawl → SQLite → sync → Supabase → Vercel) |

## Kiến trúc

```
MÁY NHÀ (nuôi dữ liệu)                          CLOUD (production)
┌────────────────────────────────┐   sync 15'   ┌──────────────────────────┐
│ Windmill (docker compose riêng)│═════════════►│ Supabase Postgres        │
│  crawl :00/:15/...  quick 2tr  │  precompute  │  (RLS: anon REVOKE,      │
│  deep  04:37        50/20/40tr │  provinces[] │   authenticated SELECT)  │
│  companies :20      enrich     │  roles[]     │        ▲                 │
│  sync    :10/:25/...           │  status      │ Vercel: SPA + FastAPI    │
│ SQLite (WAL + FTS5) ◄─ crawl   │              │  serverless (psycopg2)   │
│ raw: sha256+gzip, TTL 48h      │              └────────┬─────────────────┘
└────────────────────────────────┘                       ▼
                                    https://job-crawler-theta.vercel.app
```

Hai luồng độc lập: dữ liệu sống theo pipeline máy nhà; code web deploy từ
repo (push/kéo Git). 4 hướng ứng tuyển khớp cả category + title (DE · Backend
· Fullstack · DS), mặc định KN ≤2 năm.

## Kỹ thuật đáng chú ý (điểm khó đã giải quyết)

- **Chống-bot không browser**: HTTP với TLS fingerprint Chrome thật
  (curl_cffi) — nhanh, nhẹ, không Playwright.
- **Parser RSC flight stream**: TopDev đổi toàn bộ stack (sáp nhập Saramin,
  bỏ HTML server-render) → viết parser bóc JSON object từ React Server
  Component stream bằng brace-balancing; chuẩn hoá lương VND/USD lẫn lộn.
- **Port SQLite → Postgres không đổi contract**: thay vì dịch các hàm Python
  (match tỉnh thành có dấu, role matching, open-condition) sang SQL, sync
  **precompute** thành cột mảng + GIN index — API serverless chỉ lọc bằng
  index, giữ semantics 100%.
- **Tối ưu truy vấn 200–250×**: loại subquery tương quan quét 65k dòng × mỗi
  row (74s → 0.3s); CTE join ngược thay per-row scan; migration index đúng
  khoá (source, name/detail_url).
- **Bảo mật 3 lớp cho trang riêng tư**: AuthGate → mọi `/api/*` bắt Bearer
  token đúng email (401) → RLS Postgres chặn cả PostgREST.
- **Raw evidence lifecycle**: content-addressed (sha256) + gzip + TTL 48h tự
  dọn sau khi vào DB — từ +7.4GB/ngày xuống chặn trần ~2GB.
- **Orchestration có giao diện**: Windmill instance riêng (compose project
  tách bạch, provision idempotent qua REST), 4 schedule tự chạy, UI xem
  success/failure từng lượt.
- **Trải nghiệm keyboard-first**: inbox j/k/Enter/a/s/v/x; bộ lọc + JD mở +
  vị trí cuộn sống trong URL (deep-link, back/forward chuẩn).

## Stack

| Tầng | Công nghệ |
| --- | --- |
| Frontend | React 19 · TypeScript · Vite · Tailwind v4 · TanStack Query · React Router 7 · Recharts |
| Backend | FastAPI (local + Vercel serverless) · Pydantic |
| Data | SQLite (WAL, FTS5) · PostgreSQL 17 / Supabase (RLS, GIN) · psycopg2 |
| Crawler | Python · curl_cffi (TLS impersonate) · BeautifulSoup · custom RSC parser |
| Orchestration | Windmill (docker compose) · systemd (fallback) |
| Infra/CI | Vercel · GitHub · uv · pytest (60) · tsc strict |

## Chạy local (5 phút)

```bash
uv sync --extra dev && npm --prefix frontend ci && npm --prefix frontend run build
uv run job-crawler migrate        # schema (backup tự động nếu DB cũ)
uv run job-crawler all            # crawl thử 1 lượt
scripts/local/windmill.sh up      # tự động: Windmill + 4 lịch + UI :8132
```

Dashboard local `localhost:8130` · Windmill UI `localhost:8132`
(`admin@windmill.dev` / `changeme`). Mở lại máy là tự chạy tiếp — không cần
gõ gì.

## Lệnh hay dùng

```bash
scripts/local/check.sh             # sức khoẻ cả chuỗi 7 tầng
scripts/local/windmill.sh runs     # 10 lượt chạy gần nhất
uv run job-crawler all | companies | deep | raw-gc | verify
uv run pytest -q                   # 60 test
```

## Production

Web: **[job-crawler-theta.vercel.app](https://job-crawler-theta.vercel.app)**
— riêng tư, đăng nhập Google 1 tài khoản. Deploy: `scripts/local/deploy_vercel.sh`
hoặc nối GitHub trên Vercel để auto-deploy mỗi push. Env cần: `DATABASE_URL`
(Vercel) + `SUPABASE_DB_URL`, `VITE_*`, `ALLOWED_EMAIL` (`.env`, không commit).

## Tính năng người dùng

Inbox 4 hướng ứng tuyển + KN ≤2 năm, điểm khớp CV 0–100 kèm term trùng, lọc
quy mô công ty/tỉnh thành (có–không dấu)/lương/nguồn/cấp bậc/remote, ★ sao
việc hay, JD + phúc lợi trong trang, card công ty "đang tuyển gì" → nhảy
Inbox đã lọc, thống kê theo bộ lọc, xuất CSV.

## Tài liệu

- [docs/operations.md](docs/operations.md) — lịch chạy, toàn bộ env, cơ chế
  nội bộ, dung lượng, xử lý sự cố
- [docs/security.md](docs/security.md) — bảo mật 3 lớp production
- [docs/architecture/design.md](docs/architecture/design.md) ·
  [docs/data/contracts.md](docs/data/contracts.md) — thiết kế & data contract

---

<details>
<summary><strong>PROJECT FACTS — structured summary for AI readers</strong></summary>

```yaml
project: san-viec (job-crawler)
purpose: personal job-intelligence pipeline for Vietnamese IT market
author_role: solo engineer (design + build + operate)
data_pipeline:
  sources: [itviec, topcv, topdev]
  cadence: quick crawl 15min (2 pages/source); deep daily (50/20/40 pages)
  jobs_active: ~1900 (14-day window, open-verified)
  company_directory: 65374 profiles, enriched hourly
  storage: SQLite WAL+FTS5 (~70MB) | raw gzip sha256 TTL-48h (~2GB cap) | Supabase Postgres 84MB/500MB
engineering_highlights:
  - curl_cffi TLS impersonation (no headless browser)
  - custom RSC-flight-stream parser (TopDev/Saramin migration)
  - SQLite->Postgres port via sync-time precompute (provinces[], roles[], effective_status) + GIN indexes
  - query optimization 74s->0.3s (eliminated correlated subqueries over 65k-row directory)
  - 3-layer auth: AuthGate -> Bearer-enforced /api/* -> Postgres RLS
  - raw evidence lifecycle: +7.4GB/day -> ~2GB steady state
  - Windmill orchestration (dedicated compose project, idempotent REST provisioning)
stack: [React19, TypeScript, Vite, Tailwind4, TanStack Query, React Router 7,
        FastAPI, SQLite, PostgreSQL/Supabase, psycopg2, curl_cffi, BeautifulSoup,
        Windmill, Vercel, uv, pytest]
tests: 60 pytest (parsers, contracts, migrations, serving, security gates)
urls: {prod: https://job-crawler-theta.vercel.app, repo: https://github.com/huy-dataguy/job-crawler}
```

</details>
