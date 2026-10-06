# Job Crawler

Crawler việc làm IT tại HCM từ **ITviec**, **TopCV** và **TopDev**. Hệ thống lưu dữ liệu chuẩn hoá vào SQLite, có dashboard để lọc job, và gửi Telegram khi phát hiện job mới.

```text
ITviec / TopCV / TopDev
            │
            ▼
  crawler → SQLite (data/job_crawler.db) → Dashboard (:8130)
            │
            └──────────────────────────→ Telegram

Windmill (:8131) chạy crawler mỗi 15 phút (00, 15, 30, 45 — Asia/Ho_Chi_Minh)
```

## Tính năng

- Deduplicate theo `source + source_id`; crawl lại chỉ cập nhật `last_seen_at`.
- **Liên quan cá nhân hoá**: mỗi job được chấm điểm 0–100 khớp profile CV
  (Data Engineer là hướng chính, FullStack là hướng phụ — xem
  `src/job_crawler/relevance.py`). Dashboard mặc định xếp "liên quan nhất";
  badge `% khớp` hiện trên mỗi job (hover xem term khớp).
- **Thư mục công ty đầy đủ** (bảng `company_directory`): TopCV qua sitemap
  (~49k công ty), ITviec qua directory phân trang, TopDev qua trang đầu +
  tích lũy từ tin đăng (sitemap topdev đang lỗi 500 phía server). Mỗi job
  crawl gắn kèm công ty với tên chính xác + cờ đang tuyển; quy mô công ty
  được enrich dần theo ngân sách mỗi ngày (ưu tiên công ty đang tuyển).
- **DB gọn nhẹ, không raw**: chỉ lưu job IT đã làm sạch (non-IT bị bỏ trước khi
  lưu); job đăng quá `JC_KEEP_DAYS` ngày hoặc biến mất khỏi nguồn sau
  `JC_STALE_DAYS` ngày sẽ bị xoá (kèm FTS/marks) rồi `VACUUM` — thư mục công ty
  được giữ lại (dòng nhỏ, không prune).
- Telegram chỉ push job mới có điểm liên quan ≥ `JC_NOTIFY_MIN_RELEVANCE`
  (kèm dòng `🎯 Khớp profile: N%`). Gửi lỗi thì job chưa commit và sẽ retry ở lượt sau.
- Dashboard React/FastAPI: search, filter, đánh dấu đã xem/ẩn và thống kê.
- Windmill có `no_flow_overlap`: lượt quét chậm không tạo lượt chạy chồng.
- ITviec và TopDev được xử lý trước; TopCV fetch qua curl_cffi impersonate TLS (chrome124/136/safari184) để vượt Cloudflare — không cần browser.

## Yêu cầu

| Thành phần | Mục đích |
| --- | --- |
| Git | Clone repository |
| Python 3.11+ và [uv](https://docs.astral.sh/uv/) | Crawler, dashboard backend, tests |
| Node.js 20+ và npm | Build dashboard React |
| Docker Engine + Docker Compose v2 | Windmill, Postgres, crawler worker |
| `wmill` CLI | Deploy scripts và schedule vào Windmill |

Không cần Chrome/Chromium ở host hay worker: TopCV dùng curl_cffi (TLS impersonate), không spawn browser.

## Quickstart: chạy đầy đủ sau khi clone

### 1. Clone và cài dependencies

```bash
git clone <URL_REPOSITORY_CUA_BAN> job-crawler
cd job-crawler

# Python package + test dependencies
uv sync --extra dev

# Tạo frontend bundle để FastAPI có thể serve dashboard
cd frontend
npm ci
npm run build
cd ..
```

Thư mục `data/` được tạo tự động ở lần crawl đầu tiên và không được commit.

### 2. Crawl dữ liệu cục bộ

Chạy từng nguồn trước để kiểm tra network:

```bash
uv run job-crawler itviec
uv run job-crawler topdev
```

Chạy toàn bộ nguồn (kể cả TopCV — chỉ cần network, không cần Chrome):

```bash
uv run job-crawler
# hoặc: uv run job-crawler topcv
```

Dữ liệu ở `data/job_crawler.db`. Không cần xoá database giữa các lần chạy; crawler đã deduplicate.

### 3. Chạy dashboard

Mở terminal khác tại repository root:

```bash
uv run uvicorn dashboard.main:app --host 0.0.0.0 --port 8130
```

Mở <http://localhost:8130>. Muốn sửa frontend với hot reload thì chạy thêm:

```bash
cd frontend
npm run dev
```

Vite chạy tại <http://localhost:5173> và proxy API về dashboard `:8130`.

### 4. Khởi động Windmill

```bash
cd windmill
cp .env.example .env
# Đổi ít nhất POSTGRES_PASSWORD và ADMIN_PASSWORD trong .env trước khi dùng lâu dài.
docker compose up -d
docker compose ps
cd ..
```

Mở <http://localhost:8131>, đăng nhập bằng `ADMIN_EMAIL` / `ADMIN_PASSWORD` trong `windmill/.env`, rồi tạo workspace có **workspace ID** là `jobcrawler`.

### 5. Deploy scripts và schedule

Sau khi cài `wmill` CLI, chạy từ thư mục `windmill/`:

```bash
cd windmill
wmill login --base-url http://localhost:8131
wmill workspace add jobcrawler jobcrawler http://localhost:8131
wmill workspace switch jobcrawler

wmill script push u/jobcrawler/crawl_itviec.py
wmill script push u/jobcrawler/crawl_topcv.py
wmill script push u/jobcrawler/crawl_topdev.py
wmill script push u/jobcrawler/crawl_all.py
wmill script push u/jobcrawler/telegram_test.py

wmill schedule push \
  u/jobcrawler/schedule_crawl_jobcrawl.yaml \
  u/jobcrawler/schedule_crawl_jobcrawl
cd ..
```

Schedule chạy script `u/jobcrawler/crawl_all` ở phút `00, 15, 30, 45` mỗi giờ theo `Asia/Ho_Chi_Minh`.

> Nếu CLI chưa thấy workspace sau login, dùng `wmill workspace list-remote` rồi thêm/chuyển sang profile tương ứng. Repository dùng các lệnh push tường minh ở trên, không yêu cầu `wmill sync push`.

## Cấu hình Telegram

### Tạo bot và lấy chat ID

1. Tạo bot qua [@BotFather](https://t.me/BotFather), lưu token ở nơi an toàn.
2. Mở bot và bấm **Start** / gửi `/start`.
3. Gửi một tin nhắn bất kỳ cho bot, sau đó lấy chat ID:

   ```bash
   export TELEGRAM_BOT_TOKEN='token_tu_BotFather'
   curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"
   ```

   Lấy giá trị `message.chat.id` trong JSON trả về.

### Lưu Telegram secrets trong Windmill

Không commit token vào Git, `.env.example` hoặc `docker-compose.yml`. Scripts lấy encrypted Windmill Variables này qua job token sống ngắn:

```bash
export TELEGRAM_CHAT_ID='chat_id_cua_ban'

cd windmill
wmill variable add "$TELEGRAM_BOT_TOKEN" u/jobcrawler/telegram_bot_token
wmill variable add "$TELEGRAM_CHAT_ID" u/jobcrawler/telegram_chat_id
wmill script run u/jobcrawler/telegram_test
cd ..
```

Khi test thành công, bot nhận tin `Job Crawler đã kết nối Telegram`. Job mới có format:

```text
🚨 JOB MỚI · TOPDEV

Senior Backend Developer
🏢 ABC Company
📍 Hồ Chí Minh
💰 30–50 triệu
🧭 3 năm kinh nghiệm
🛠 Python, FastAPI, PostgreSQL
🕒 Đăng 2 giờ trước

Xem và ứng tuyển →
```

Lương, skills và thời gian đăng chỉ hiện nếu nguồn cung cấp. Link ứng tuyển ở cuối tin; link preview được tắt.

### Chạy alert khi crawl local (tuỳ chọn)

```bash
export TELEGRAM_BOT_TOKEN='...'
export TELEGRAM_CHAT_ID='...'
uv run job-crawler telegram-test
uv run job-crawler itviec

# Tắt alert cho đúng một lần chạy local
JC_TELEGRAM_ENABLED=0 uv run job-crawler itviec
```

## Chạy local tự động (systemd timer — nhẹ nhất, không cần Windmill/Docker)

```bash
bash scripts/local/install.sh
```

Script làm 3 việc: tạo `.env` (nếu chưa có) để điền secret Telegram, cài
systemd user units (crawl 15 phút/lượt + dashboard nền `127.0.0.1:8130`),
enable cả hai. Kiểm tra:

```bash
systemctl --user list-timers job-crawler-crawl.timer
curl -s localhost:8130/api/stats | head -c 200
journalctl --user -u job-crawler-crawl.service -n 20 --no-pager
```

Muốn dashboard/timer chạy ngay cả khi chưa đăng nhập GUI, bật linger:
`loginctl enable-linger` (cần quyền admin). Dừng/huỷ:

```bash
systemctl --user disable --now job-crawler-crawl.timer job-crawler-dashboard.service
```

## Kiểm tra sau khi cài

Chạy ở repository root:

```bash
uv run pytest -q
uv run job-crawler itviec
curl -f http://localhost:8130/api/stats

cd windmill
docker compose ps
docker compose logs --tail=100 windmill_worker_jobcrawl
```

Trong Windmill UI, xác nhận schedule `u/jobcrawler/schedule_crawl_jobcrawl` đang enabled. Trang Runs hiển thị `found`, `new`, `updated`, `notified` của từng nguồn; SQLite lưu manifest trong bảng `crawl_runs`.

## Vận hành thường ngày

| Việc | Lệnh |
| --- | --- |
| Crawl toàn bộ local | `uv run job-crawler` |
| Crawl một nguồn | `uv run job-crawler itviec\|topcv\|topdev` |
| Harvest thư mục công ty + enrich | `uv run job-crawler companies` |
| Chỉ enrich quy mô công ty | `uv run job-crawler enrich` |
| Test Telegram local | `uv run job-crawler telegram-test` |
| Dashboard | <http://localhost:8130> |
| Windmill | <http://localhost:8131> |
| Xem worker log | `cd windmill && docker compose logs -f windmill_worker_jobcrawl` |
| Dừng Windmill | `cd windmill && docker compose down` |

`docker compose down` vẫn giữ volumes. Không dùng `docker compose down -v` nếu không chủ đích xoá toàn bộ trạng thái Windmill/Postgres.

## Biến môi trường hữu ích

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `JC_DATA_DIR` | `./data` | Thư mục SQLite |
| `JC_DB_PATH` | `$JC_DATA_DIR/job_crawler.db` | Đường dẫn SQLite cụ thể |
| `JC_MAX_PAGES_ITVIEC` | `3` | Trang ITviec tối đa/lượt |
| `JC_MAX_PAGES_TOPCV` | `3` | Trang TopCV tối đa/lượt |
| `JC_MAX_PAGES_TOPDEV` | `4` | Trang TopDev tối đa/lượt |
| `JC_KEEP_DAYS` | `30` | Giữ job đăng trong vòng N ngày (quá thì xoá) |
| `JC_STALE_DAYS` | `7` | Xoá job không thấy lại trên nguồn sau N ngày |
| `JC_NOTIFY_MIN_RELEVANCE` | `40` | Ngưỡng điểm CV để push Telegram (0 = push mọi job mới) |
| `JC_ITVIEC_COMPANY_PAGES` | `120` | Số trang directory công ty ITviec tối đa |
| `JC_TOPCV_SITEMAP_PAGES` | `300` | Số sub-sitemap công ty TopCV tối đa |
| `JC_COMPANY_ENRICH_BUDGET` | `150` | Số trang detail công ty enrich mỗi lượt chạy |
| `JC_DELAY` | `2.0` | Giãn request, đơn vị giây |
| `TELEGRAM_BOT_TOKEN` | — | Token bot (chỉ local hoặc Windmill Secret) |
| `TELEGRAM_CHAT_ID` | — | Chat nhận alert (chỉ local hoặc Windmill Secret) |
| `JC_TELEGRAM_ENABLED` | tự bật khi đủ secrets | Đặt `0` để tắt local alert |

## Cấu trúc

```text
src/job_crawler/  Crawlers, normalize, SQLite store, Telegram notifier
dashboard/        FastAPI API/dashboard backend
frontend/         React + Vite dashboard
windmill/         Docker Compose, Windmill scripts và schedule
tests/            Tests pipeline/notifier
data/             SQLite runtime data (tự tạo, git-ignored)
```

## Lưu ý vận hành

- Không tăng số trang hoặc giảm `JC_DELAY` tuỳ tiện; nguồn có thể rate-limit hoặc đổi giao diện.
- Nếu Cloudflare siết thêm khiến TopCV bị chặn TLS, run Windmill sẽ đỏ ngay với lỗi rõ ràng (không treo); crawler vẫn thử lại ở schedule sau.
- Nếu bot token từng bị lộ, revoke/regenerate ở BotFather, sau đó cập nhật `u/jobcrawler/telegram_bot_token` trong Windmill.
