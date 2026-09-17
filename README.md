# job-crawler

Crawler tự động lấy việc làm IT tại HCMC từ **ITviec** và **TopCV**, chạy định kỳ qua **Windmill**, data sạch nhỏ nhẹ (SQLite), dashboard xem + filter để apply job.

## Kiến trúc ngắn

```
itviec  (HTTP thuần, server-rendered) ─┐
                                       ├─→ job_crawler (parse → canonical) → SQLite data/job_crawler.db
topcv   (headless Chrome — Cloudflare) ─┘            ↑ schedule Windmill 9/11/14/16/21h
                                                     └→ dashboard (FastAPI :8130)
```

- **itviec**: fetch HTTP trực tiếp (trang server-render, không cần browser).
- **topcv**: chặn Cloudflare với HTTP thuần → headless Chrome one-shot (`--dump-dom`), core: `UA` phải là Chrome thật (không phải HeadlessChrome) mới pass.
- **Dữ liệu sạch**: chỉ lưu bản ghi đã normalize: `source, source_id (dedup), title, company, url, city, salary, experience, category, tags, posted_at (ước tính từ "N hours/tuần trước"), first/last_seen, seen_count, is_active, is_new`. Không lưu raw HTML.
- **Idempotent**: crawl lại → upsert `last_seen`, không pha dữ liệu.
- **Manifest**: bảng `crawl_runs` ghi mỗi lần chạy (status, found, new, updated, error note).

## Chạy crawler bằng tay

```bash
uv sync && uv run python -m job_crawler          # all
uv run python -m job_crawler itviec              # 1 nguồn
uv run python -m job_crawler topcv               # (cần google-chrome trên host)
```

## Dashboard

```bash
uv run uvicorn dashboard.main:app --port 8130
# http://localhost:8130  — stats + filter (nguồn/category/tag/từ khoá)
# API: /api/jobs?limit=100&source=topcv&q=java · /api/stats
```

## Windmill (điều phối — tạo mới cho dự án này)

```bash
cd windmill
cp .env.example .env
docker compose up -d             # UI tại http://localhost:8131
```

Worker dùng image `heronq02/windmill-worker:latest` (có sẵn Chromium cho TopCV), mount repo `/workspace` (ro) + `/data` (rw).

Sau đó trong UI hoặc CLI:

```bash
cd windmill
wmill login                                        # lần đầu
wmill sync push                                    # đẩy u/jobcrawler/* (scripts + schedule)
```

- Scripts: `windmill/u/jobcrawler/crawl_itviec.py`, `crawl_topcv.py`, `crawl_all.py` (schedule entry).
- Schedule (đã tạo sẵn yaml): `0 9,11,14,16,21 * * *` — Asia/Ho_Chi_Minh.
- Nếu `wmill sync` không nhận schedule yaml (format có thể đổi theo version), tạo schedule thủ công trong UI: script `u/jobcrawler/crawl_all`, cron ấy, no_overlap.

## Cấu trúc

```
src/job_crawler/    crawler package (itviec.py, topcv.py, store.py, pipeline.py, config.py)
dashboard/          FastAPI + Jinja2 dashboard
windmill/           docker-compose + wmill scripts + schedule
data/job_crawler.db SQLite — dữ liệu sạch duy nhất của hệ thống
recon/              fixture recon (không commit)
docs/               design notes
```

## Cảnh báo vận hành

- TopCV có thể thay đổi biến thể trang (đã thấy 1 variant mất field) — crawler tự retry/validation, lỗi sẽ hiện trong `crawl_runs` + UI Windmill.
- Không nâng số trang/req vội: distressed site, giữ delay 2s/n-pages.
