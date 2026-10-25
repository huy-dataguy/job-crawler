# Job Crawler — Việt Nam & Remote

Tìm việc IT liên tục trên toàn Việt Nam từ ITviec, TopCV và TopDev; xây dựng
thư mục công ty độc lập với vòng đời tin tuyển dụng. Dashboard: <http://127.0.0.1:8130>.

## Hành vi mặc định

- Quét job mỗi **15 phút**; quét rộng hơn mỗi ngày lúc **04:37**.
- Inbox ưu tiên **14 ngày gần nhất**, ngày đăng gốc từ trang chi tiết, và tin
  **còn mở được kiểm tra trong 24 giờ**. Tin được đẩy lại không tự trở thành tin mới.
- Xác nhận mở dựa trên JobPosting phù hợp + nút ứng tuyển hiện tại + hạn còn hiệu lực
  nếu nguồn cung cấp. HTTP 404/410 hoặc hết hạn đóng tin. Timeout/challenge không xác nhận mở.
- Xem JD, yêu cầu, phúc lợi, hạn nộp, vị trí và hình thức làm việc ngay trên dashboard.
- Dropdown **Tỉnh / thành** ở đầu trang áp dụng cho cả Inbox, Thống kê và Công ty;
  giữ lựa chọn khi chuyển tab. Nhận diện tên có dấu/không dấu và các tên như
  Ha Noi, Hanoi, TP.HCM, Ho Chi Minh. Công ty khớp theo địa chỉ hoặc địa điểm
  tin tuyển dụng còn mở; KPI, biểu đồ và CSV áp dụng cùng bộ lọc. Có lựa chọn
  “Toàn quốc” và “Chưa rõ tỉnh / thành”.
- Chọn “Chưa xác nhận”, “Đã đóng”, “Tất cả” hoặc “Mọi lúc” để xem rộng hơn.
  Tin không có ngày đăng không vào bộ lọc 14 ngày; chúng vẫn được lưu để kiểm tra.
- Giữ lịch sử job, thư mục công ty và các dấu đã xem/ẩn/apply. Không tự xóa do
  không xuất hiện trên vài trang đầu. Một tin vẫn được giữ nếu nguồn khác lỗi.

## Thư mục công ty

- ITviec: sitemap công khai được khai báo trong robots.txt, hiện có hơn 12.000 hồ sơ.
- TopCV: sitemap con có checkpoint; quét luân phiên từng nhóm, làm mới chu kỳ 7 ngày.
- TopDev: directory phân trang có checkpoint và công ty tích lũy từ job, có báo rõ phạm vi thu thập.
- Làm giàu hồ sơ **mỗi giờ** (phút 08, lệch tối đa 60 giây): tên thật, website/tuyển dụng,
  địa chỉ, ngành, quy mô, mô tả, mô hình, quốc gia, lịch làm việc, OT, kỹ năng, phúc lợi,
  liên kết công khai nếu nguồn có cung cấp. Chưa có dữ liệu thì để trống.
- Phân loại “công nghệ”, “có tín hiệu IT”, “chưa phân loại” bằng quy tắc có bằng chứng.
  Tín hiệu từ directory hoặc từ khóa chưa phải xác nhận cơ cấu phòng ban.
  Doanh nghiệp ngân hàng/bán lẻ/sản xuất có tuyển IT vẫn thuộc phạm vi ưu tiên.
- Có tìm kiếm/lọc, tỷ lệ đầy đủ và xuất CSV theo bộ lọc. Con số là **hồ sơ theo nguồn**;
  một doanh nghiệp có thể có nhiều hồ sơ. Không cam kết bao phủ mọi công ty Việt Nam.
- Trong tab Công ty, chọn **Thông tin còn thiếu** để lọc hồ sơ thiếu quy mô, lĩnh vực,
  website, địa chỉ hoặc mô tả. Có thể kết hợp “thiếu tất cả” hoặc “thiếu ít nhất một”
  mục; thống kê và CSV dùng cùng điều kiện. NULL, chuỗi trống và giá trị như N/A/unknown
  đều được xem là chưa có thông tin.

## Kiến trúc

```text
Public listing / company sitemap
    -> source HTTP adapter -> immutable HTML + append-only manifest
    -> listing parser -> canonical jobs / directory (SQLite WAL)
    -> detail verification / profile enrichment queue (bounded, retryable)
    -> FastAPI -> React dashboard / CSV
```

Mốc thời gian riêng: posted_at (ngày nguồn), first_seen_at, last_seen_at,
detail_checked_at, valid_through, enriched_at. Không dùng first_seen thay ngày đăng.
Raw ở `data/raw/<source>/<date>/<kind>/<sha256>.html`; manifest ở
`data/raw/manifest.jsonl`; cột `raw_artifact` liên kết hồ sơ đã xử lý tới bằng chứng.
Crawl runs và checkpoint được lưu trong SQLite. Không cần Docker/Windmill để chạy local.

Thiết kế và contract: [requirements](docs/requirements/redesign.md),
[architecture](docs/architecture/design.md), [contracts](docs/data/contracts.md).

## Cài và chạy

Python 3.11+, uv, Node.js/npm; systemd user cho chạy nền trên Linux.

```bash
uv sync --extra dev
npm --prefix frontend ci
npm --prefix frontend run build

# Migrate cộng thêm, tự backup SQLite hiện có vào data/backups/.
# Chạy trước khi khởi động crawler/dashboard mới.
uv run job-crawler migrate

# Crawl thật, không gửi thông báo ra ngoài.
uv run job-crawler all
uv run job-crawler companies

# Cài unit với đường dẫn checkout hiện tại và bật chạy nền.
bash scripts/local/install.sh
```

Cài lại sau khi di chuyển thư mục dự án. Các unit được kiểm tra bằng
`systemd-analyze --user verify` trước khi kích hoạt. Dashboard bind loopback.
Host hiện có Linger=yes; service tiếp tục chạy khi đăng xuất và tự khởi động lại
khi máy bật. Máy phải hoạt động và có mạng để quét được.

## Lệnh vận hành

| Lệnh | Chức năng |
| --- | --- |
| `uv run job-crawler all` | Quét đủ nguồn; lỗi một nguồn vẫn chạy các nguồn còn lại |
| `uv run job-crawler itviec` | Chỉ một nguồn; tương tự topcv/topdev |
| `uv run job-crawler companies` | Discovery danh bạ và làm giàu theo ngân sách |
| `uv run job-crawler enrich` | Chỉ làm giàu hồ sơ |
| `uv run job-crawler recheck` | Chỉ kiểm tra chi tiết job đã lưu |
| `uv run job-crawler replay` | Parse lại raw đã lưu, không gọi mạng và không gia hạn bằng chứng còn mở |
| `uv run job-crawler verify` | Boot gate dữ liệu thật: contract, counts, freshness, raw, query plan |
| `curl -fsS localhost:8130/api/health` | Tình trạng nguồn và số liệu thực tế |
| `curl -fsS localhost:8130/api/runs` | Lượt chạy gần đây và lỗi |
| `systemctl --user list-timers 'job-crawler-*'` | Lịch chạy tiếp theo |
| `journalctl --user -u job-crawler-crawl.service -n 30 --no-pager` | Log crawler |

Các CLI dùng chung writer.lock. Busy trả exit 75; systemd thử lại sau 120 giây,
tránh công ty bị bỏ quét mãi khi trùng lịch job. Lỗi nguồn thật chờ kỳ lịch sau.
`all` trả exit 1 nếu một nguồn discovery lỗi sau khi đã thử các nguồn còn lại;
chi tiết bị lỗi từng tin được ghi là partial và có thể thử lại sau 2 giờ.
Company detail lỗi chờ 6 giờ, thành công làm mới sau 14 ngày.

Tạm dừng:

```bash
systemctl --user disable --now job-crawler-crawl.timer job-crawler-companies.timer job-crawler-deep.timer
systemctl --user stop job-crawler-crawl.service job-crawler-companies.service job-crawler-deep.service
systemctl --user disable --now job-crawler-dashboard.service
```

## Cấu hình

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| JC_DATA_DIR | ./data | SQLite, raw, manifest và lock |
| JC_DB_PATH | data/job_crawler.db | Đường dẫn canonical DB |
| JC_MAX_PAGES_ITVIEC | 10 | Ngân sách trang/lượt |
| JC_MAX_PAGES_TOPCV | 5 | Ngân sách trang/lượt |
| JC_MAX_PAGES_TOPDEV | 10 | Ngân sách trang/lượt |
| JC_JOB_DETAIL_BUDGET | 60 | Kiểm tra chi tiết tối đa mỗi nguồn/lượt |
| JC_COMPANY_ENRICH_BUDGET | 90 | Hồ sơ tối đa mỗi lượt làm giàu |
| JC_TOPCV_SITEMAP_PAGES | 10 | Sub-sitemap chưa làm trong mỗi lượt |
| JC_TOPDEV_COMPANY_PAGES | 10 | Trang danh bạ TopDev tiếp theo mỗi lượt |
| JC_OPEN_CHECK_HOURS | 24 | Hết bằng chứng còn mở nếu quá thời gian này |
| JC_DELAY | 2.0 | Giãn request theo nguồn, giây |
| JC_DEEP_PAGES_ITVIEC/TOPCV/TOPDEV | 50/20/40 | Lượt quét rộng hằng ngày |
| JC_DEEP_DETAIL_BUDGET | 100 | Chi tiết mỗi nguồn trong lượt rộng |

Script local nạp `.env` nhưng tắt Telegram trong đợt triển khai này. CLI cũng mặc
định không gửi tin, kể cả có secret. Chỉ bật lại bằng cấu hình tường minh khi muốn
sử dụng tính năng Telegram cũ; không commit token vào Git. Các file Windmill cũ
được giữ để tham khảo, **chưa triển khai lại** và không phải lịch local đang dùng.

## Bảo mật (production)

Bản Vercel là trang **riêng tư**: chỉ 1 tài khoản Google được phép đăng nhập
(`ALLOWED_EMAIL` trong `.env`). Ba lớp: màn login (AuthGate) → mọi `/api/*`
yêu cầu Bearer token hợp lệ (401 nếu sai) → RLS Postgres chặn cả đường
PostgREST. Runbook đầy đủ (tạo Google OAuth client, bật provider Supabase,
kiểm chứng, thu hồi phiên): `docs/security.md`.

## Kiểm chứng

```bash
uv run pytest -q
(cd frontend && npx tsc --noEmit && npm run build)
uv run job-crawler verify
curl -fsS 'http://127.0.0.1:8130/api/jobs?limit=3'
curl -fsS 'http://127.0.0.1:8130/api/companies?it_only=1&limit=3'
```

Kết quả runtime và ảnh giao diện ở `data/verification/` (không đưa dữ liệu vào Git).
Backup trước migrate ở `data/backups/`. Raw và lịch sử tăng theo thời gian; giám sát
thư mục data và chỉ áp dụng chính sách giữ dữ liệu sau khi đã chọn phạm vi retention.
