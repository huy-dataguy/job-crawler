# Săn Việc — Job Crawler Việt Nam & Remote

Tự động tìm việc IT từ **ITviec, TopCV, TopDev**, xếp hạng theo độ khớp CV,
làm giàu danh bạ 65k+ công ty và phục vụ qua web riêng — có bản local chạy
trên máy cá nhân và bản production trên Vercel + Supabase.

- **Production**: <https://job-crawler-theta.vercel.app> — riêng tư, đăng nhập
  Google 1 tài khoản (xem [Bảo mật](#bảo-mật-production))
- **Local dashboard**: <http://127.0.0.1:8130>
- **Orchestration UI (Windmill)**: <http://localhost:8132>

## Tính năng chính

- **Inbox apply-first**: hàng đợi mặc định = 4 hướng ứng tuyển (Data Engineer ·
  Backend · Fullstack · Data Science, khớp cả category lẫn title) · KN ≤2 năm ·
  còn mở đã kiểm tra · 14 ngày gần nhất, tự xếp theo độ khớp CV (0–100, chấm từ
  thuật toán relevance có trọng số theo hướng nghề).
- **Lọc phủ toàn diện**: quy mô công ty (chip màu, số việc realtime), tỉnh/thành
  (nhận biết dấu + tên gốc Ha Noi/TP.HCM…), KN, lương, nguồn, cấp bậc, remote/
  hybrid, kỹ năng; mọi KPI/biểu đồ/CSV dùng cùng bộ lọc.
- **Đánh dấu cá nhân**: ★ sao yêu thích (phím `s`, tab "Đã sao"), đã xem, đã
  apply, ẩn — phím tắt j/k/Enter/a/v/x theo kiểu keyboard inbox.
- **Router thật**: `/` Inbox · `/thong-ke` · `/cong-ty`; bộ lọc + JD đang mở +
  công ty đang mở sống trong URL (refresh/back-forward/deep-link) + khôi phục
  vị trí cuộn.
- **Thư mục công ty**: card grid "săn qua công ty" — quy mô nhân sự, vị trí đang
  tuyển (gom từ job còn mở), nhảy thẳng Inbox đã lọc.
- **Chi tiết job**: JD/yêu cầu/phúc lợi/hạn nộp ngay trong trang; ngày đăng gốc
  từ trang chi tiết; tin còn mở được kiểm tra 24h một lần.

## Kiến trúc

```text
┌── Máy cá nhân (nguồn dữ liệu) ────────────────────────────────────┐
│ Windmill (docker compose riêng, tự dậy theo máy)                  │
│  ├─ crawl_all      :00/:15/:30/:45  → curl_cffi + BeautifulSoup   │
│  │   (TopDev bóc RSC flight stream — site mới của Saramin)        │
│  ├─ sync_supabase  :10/:25/:40/:55  → Supabase Postgres           │
│  │   (precompute provinces[]/roles[]/effective_status + GIN idx)  │
│  ├─ companies      :20 mỗi giờ      → làm giàu danh bạ            │
│  └─ deep           04:37 hằng ngày  → quét đủ 50/20/40 trang      │
│ SQLite (WAL + FTS5) ← canonical jobs + directory + marks          │
│ Raw evidence: sha256 + gzip, TTL 48h (~2GB steady state)          │
│ Dashboard FastAPI :8130 (tùy chọn — production thay thế được)     │
└───────────────────────────────────────────────────────────────────┘
                          ↓ sync 15 phút/lượt
┌── Cloud (production) ─────────────────────────────────────────────┐
│ Supabase Postgres (RLS: anon REVOKE, authenticated chọn lọc)      │
│ Vercel: SPA tĩnh + api/index.py (FastAPI serverless, psycopg2)    │
│ → https://job-crawler-theta.vercel.app (Google auth 3 lớp)        │
└───────────────────────────────────────────────────────────────────┘
```

Hai luồng **độc lập**: dữ liệu sống theo pipeline máy nhà; code web deploy từ
repo. Push code không đụng dữ liệu, crawler không đụng web.

Tài liệu thiết kế: [requirements](docs/requirements/redesign.md) ·
[architecture](docs/architecture/design.md) · [contracts](docs/data/contracts.md) ·
[security](docs/security.md).

## Chạy local (dành cho người mới lấy repo về)

Yêu cầu: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 18+,
Docker (cho Windmill), Linux (systemd user).

```bash
git clone https://github.com/huy-dataguy/job-crawler.git && cd job-crawler

# 1. Cài dependencies
uv sync --extra dev
npm --prefix frontend ci && npm --prefix frontend run build

# 2. Migrate schema (tự backup vào data/backups/ nếu có DB cũ)
uv run job-crawler migrate

# 3. Chạy thử một lượt crawl (không gửi thông báo ra ngoài)
uv run job-crawler all

# 4. Dashboard local
uv run uvicorn dashboard.main:app --port 8130   # hoặc bash scripts/local/install.sh
```

### Bật tự động bằng Windmill (khuyến nghị)

```bash
scripts/local/windmill.sh up     # docker compose up + provision workspace/scripts/schedules
```

UI: <http://localhost:8132> (`admin@windmill.dev` / `changeme` — đổi qua
`windmill/.env`). Workspace **Job Crawler** có 5 script bấm-Run-được và 4
schedule tự chạy; tab Runs xem success/failure từng lượt.

Container `restart: unless-stopped` — **mở lại máy là tự dậy**, không cần gõ
gì. Windmill không chạy bù nhịp lỡ, nhưng mốc 15 phút đầu tiên sau khi mở máy
là data đã tươi lại.

### Nếu không muốn Docker: systemd (cấu hình cũ, vẫn dùng được)

```bash
bash scripts/local/install.sh          # cài dashboard + crawl/deep/companies/sync timers
```

Mặc định hiện tại khuyến nghị **chọn một** scheduler (Windmill **hoặc**
systemd timers) để tránh 2 lượt crawl giẫm writer.lock. Đang dùng Windmill
thì các timer đã `disable`.

## Production (Vercel + Supabase)

| Thành phần | Ở đâu | Ghi chú |
| --- | --- | --- |
| SPA + API serverless | Vercel project `job-crawler` | `api/index.py` mirror contract bản local |
| Database | Supabase Postgres | precompute tại sync → API chỉ lọc bằng index |
| Deploy | `scripts/local/deploy_vercel.sh` hoặc Vercel Git | nối GitHub ở Settings → Git để auto-deploy mỗi push |
| Env bắt buộc | `DATABASE_URL` (Vercel) + `VITE_*`, `SUPABASE_*` (`.env`) | secrets không bao giờ commit |

Đổi code web → `vercel --prod` (hoặc push nếu đã nối Git). Dữ liệu **không**
theo deploy — do pipeline máy nhà sync.

## Lệnh vận hành

| Lệnh | Chức năng |
| --- | --- |
| `uv run job-crawler all` / `itviec` `topcv` `topdev` | Quét nguồn; lỗi một nguồn vẫn chạy nguồn khác |
| `uv run job-crawler companies` / `enrich` | Danh bạ / chỉ làm giàu hồ sơ |
| `uv run job-crawler recheck` / `replay` | Kiểm tra chi tiết / parse lại raw không gọi mạng |
| `uv run job-crawler raw-gc` | Dọn raw quá TTL tay (không cần writer.lock) |
| `uv run job-crawler verify` | Boot gate: contract, counts, freshness, query plan |
| `scripts/local/check.sh` | **Kiểm sức khoẻ cả chuỗi** — Windmill → dashboard → từng nguồn crawl → sync → cloud (7 mục ✓/✗) |
| `scripts/local/windmill.sh up/stop/runs` | Bật/tắt Windmill + xem 10 run gần nhất bằng CLI |
| `curl -fsS localhost:8130/api/health` | Trạng thái nguồn + số liệu thật |

CLI dùng chung `writer.lock`; bận trả exit 75 và thử lại sau. Detail lỗi từng
tin được ghi partial, thử lại sau 2h; company detail lỗi chờ 6h.

## Dung lượng (đo thực tế)

| Kho | Hiện tại | Tăng/ngày | Trần |
| --- | --- | --- | --- |
| SQLite local | ~70 MB | ~2–3 MB | vài GB/năm |
| Raw evidence (đã gzip) | ~2 GB | ~1 GB (48h TTL tự dọn) | **~2 GB chặn trần** |
| Supabase | ~84 MB | ~phẳng | 500 MB free tier |

## Cấu hình

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| JC_DATA_DIR / JC_DB_PATH | ./data | Vị trí SQLite, raw, lock |
| JC_MAX_PAGES_ITVIEC/TOPCV/TOPDEV | 2/2/2 | Trang mỗi lượt quick (15 phút) |
| JC_DEEP_PAGES_ITVIEC/TOPCV/TOPDEV | 50/20/40 | Lượt sâu hằng ngày (run_deep.sh) |
| JC_RAW_RETENTION_HOURS | 48 | TTL raw (0 = tắt dọn); sweep chạy sau mỗi lượt crawl |
| JC_JOB_DETAIL_BUDGET | 60 | Chi tiết tối đa mỗi nguồn/lượt |
| JC_COMPANY_ENRICH_BUDGET | 90 | Hồ sơ làm giàu mỗi lượt |
| JC_OPEN_CHECK_HOURS | 24 | Hết bằng chứng "còn mở" |
| JC_DELAY | 2.0 | Giãn request theo nguồn, giây |
| SUPABASE_DB_URL | — | Postgres pooler cho sync + API production |
| VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY / VITE_ALLOWED_EMAIL | — | Auth client (public key, an toàn nhờ RLS) |
| ALLOWED_EMAIL | — | Email Google duy nhất được vào production |

Telegram tắt mặc định; bật lại bằng `JC_TELEGRAM_ENABLED=1` + token trong
`.env` (không commit).

## Bảo mật (production)

Trang production **riêng tư**: màn login (AuthGate) → mọi `/api/*` yêu cầu
Bearer token hợp lệ của đúng `ALLOWED_EMAIL` (401 nếu sai) → RLS Postgres chặn
cả đường PostgREST. Runbook tạo Google OAuth client + kiểm chứng + thu hồi
phiên: **[docs/security.md](docs/security.md)**.

## Kiểm chứng

```bash
uv run pytest -q                          # 60 test
(cd frontend && npx tsc --noEmit && npm run build)
uv run job-crawler verify
scripts/local/check.sh                    # cả chuỗi tới cloud
curl -fsS 'http://127.0.0.1:8130/api/jobs?limit=3'
```

Backup trước migrate ở `data/backups/`. Kết quả runtime ở `data/verification/`
(không đưa vào Git).

## Stack

React 19 · TypeScript · Vite · Tailwind v4 · TanStack Query · React Router 7 ·
Recharts — FastAPI · SQLite/Postgres (Supabase) · psycopg2 — curl_cffi ·
BeautifulSoup — Windmill (orchestration, docker compose riêng) — Vercel — uv ·
pytest (60) · GitHub Actions-ready.
