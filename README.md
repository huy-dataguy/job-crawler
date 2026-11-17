# Săn Việc / Job Hunt

Job-intelligence pipeline cá nhân cho thị trường việc làm IT Việt Nam. Hệ thống thu thập ITviec, TopCV và TopDev, chuẩn hóa dữ liệu, đánh giá độ phù hợp với CV, xác minh job còn mở và hiển thị trên dashboard riêng tư.

## Dự án làm gì?

- Crawl job từ 3 nguồn, dedupe theo `(source, source_id)` và lưu lịch sử phát hiện.
- Chuẩn hóa title, skills, level, kinh nghiệm, lương, địa điểm và role.
- Chấm điểm phù hợp CV (0–100) theo skills, title, role và kinh nghiệm.
- Kiểm tra lại trang detail để xác định deadline, trạng thái mở/đóng và tránh job đã hết hạn.
- Thu thập/enrich danh bạ công ty; liên kết công ty với các job đang tuyển.
- Đồng bộ dữ liệu từ SQLite local lên Supabase; React dashboard chạy qua FastAPI/Vercel.

## Kỹ thuật chính

- Source-specific adapters cho HTML và JSON API; fallback JSON-LD.
- TLS impersonation (`curl_cffi`), warm-up session, rate limit theo host, jitter, retry/backoff và `Retry-After`.
- Nhận diện Cloudflare challenge và schema drift để dừng pipeline thay vì ghi dữ liệu rác.
- Raw evidence nén gzip, định danh SHA-256, manifest và replay parser không cần gọi lại mạng.
- SQLite WAL + FTS5 cho data plane local; idempotent upsert và detail verification theo ngân sách.
- Windmill orchestration, per-source locks, health watchdog và Telegram alert.
- Supabase/Postgres serving với dữ liệu precompute, GIN indexes, Google Auth và RLS.

## Kiến trúc

```text
ITviec / TopCV / TopDev
        ↓
Crawler → raw evidence → normalize / score / verify
        ↓
SQLite (WAL + FTS5) ──sync──> Supabase Postgres
        ↓                         ↓
  Windmill + health          FastAPI + React / Vercel
```

## Chạy local

Yêu cầu: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 18+ và Docker (nếu dùng Windmill).

```bash
git clone https://github.com/huy-dataguy/job-crawler.git
cd job-crawler

uv sync --extra dev
npm --prefix frontend ci

uv run job-crawler migrate
uv run job-crawler all
uv run pytest -q
```

Crawler chạy được với cấu hình mặc định. Nếu dùng Telegram, Supabase hoặc deploy cloud, tạo `.env` theo [docs/operations.md](docs/operations.md).

Chạy dashboard local:

```bash
uv run uvicorn dashboard.main:app --host 127.0.0.1 --port 8130
```

Mở `http://127.0.0.1:8130`. Để chạy scheduler local:

```bash
scripts/local/windmill.sh up
```

## Lệnh thường dùng

```bash
uv run job-crawler itviec       # crawl một nguồn
uv run job-crawler companies    # harvest + enrich công ty
uv run job-crawler recheck      # xác minh lại job detail
uv run job-crawler replay       # parse lại raw evidence, không gọi mạng
uv run job-crawler health       # kiểm tra freshness / pipeline health
uv run job-crawler verify       # boot gate trên persisted data
uv run job-crawler raw-gc       # dọn raw evidence quá hạn
```

Thông tin cấu hình, lịch chạy, sync Supabase và xử lý sự cố: [docs/operations.md](docs/operations.md). Thiết lập private deployment: [docs/security.md](docs/security.md).

## Kiểm tra chất lượng

```bash
uv run pytest -q
npm --prefix frontend run build
```

CI chạy backend tests và frontend production build trên mỗi push/PR.

## License

[MIT](LICENSE) © Nguyen Quoc Huy
