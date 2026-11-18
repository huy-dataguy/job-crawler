# Vận hành chi tiết

Chi tiết kỹ thuật cho người vận hành — README chỉ giữ phần dùng hằng ngày.

## Lịch chạy (Windmill, timezone Asia/Ho_Chi_Minh)

**Windmill là scheduler DUY NHẤT.** systemd chỉ chạy dashboard. Các unit
`job-crawler-{crawl,deep,companies,sync}.timer` trong `scripts/local/` chỉ còn
để tham khảo và **phải luôn disabled**: chạy song song sẽ ghi cùng SQLite →
`database is locked`, đồng thời sinh alert Telegram từ tiến trình mà Windmill
không quản lý (Windmill vẫn xanh). `scripts/local/check.sh` sẽ báo lỗi nếu phát
hiện timer nào bị bật lại.

Mỗi sàn là **một pipeline riêng** (`crawl_itviec`, `crawl_topcv`, `crawl_topdev`)
để xem log / retry / tắt độc lập trên Windmill. Lệch phút để không tranh lock.

| Schedule | Cron | Script | Việc |
| --- | --- | --- | --- |
| crawl_topdev | `0 0 9,12,14,16 * * *` | crawl_topdev | API newest, 2 trang — bắt job mới sớm nhất |
| crawl_itviec | `0 2 9,12,14,16 * * *` | crawl_itviec | 2 trang listing + Telegram |
| crawl_topcv | `0 4 9,12,14,16 * * *` | crawl_topcv | 2 trang listing + Telegram |
| deep_itviec | `0 0 5 * * *` | deep_itviec | 50 trang + kiểm tra job còn mở |
| deep_topcv | `0 10 5 * * *` | deep_topcv | 20 trang + kiểm tra job còn mở |
| deep_topdev | `0 20 5 * * *` | deep_topdev | đọc tới trang rỗng (full coverage) |
| companies_am | `0 25 6 * * *` | companies | Harvest + enrich danh bạ (sáng) |
| companies_pm | `0 25 18 * * *` | companies | Harvest + enrich danh bạ (tối) |
| sync_hour | `0 20 * * * *` | sync_supabase | Đẩy SQLite → Supabase mỗi giờ |
| verify_open | `0 35 * * * *` | verify_open | Recheck open-state mỗi giờ (xem dưới) |
| health_hour | `0 45 * * * *` | health | Watchdog: lỗi/treo/không chạy → Telegram |

Có `no_flow_overlap` chống chồng chéo. Windmill không chạy bù nhịp lỡ; mốc đầu
tiên sau khi mở máy là data tươi lại. Các schedule cũ (`crawl_all`,
`deep_daily`, `companies_hour`, `sync_15min`, `health_10min`) bị tắt khi chạy
lại `provision.py`.

Worker chạy **4 replica** (`deploy.replicas`) vì mỗi container chỉ xử lý 1 job
bash: deep/companies dài không chặn được các lượt quick 4 lần/ngày. Máy yếu có
thể giảm còn 2; đừng bật `NATIVE_MODE`/`NUM_WORKERS>1` vì Windmill từ chối job
bash ở native mode.

## Toàn bộ biến cấu hình

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| JC_DATA_DIR / JC_DB_PATH | ./data | Vị trí SQLite, raw, lock |
| JC_MAX_PAGES_ITVIEC/TOPCV/TOPDEV | 2/2/5 | Trang mỗi lượt quick (TopDev đa ngành → 9% job là IT) |
| JC_DEEP_PAGES_ITVIEC/TOPCV/TOPDEV | 50/20/0 | Lượt sâu hằng ngày (`0` = tới last_page) |
| JC_RAW_RETENTION_HOURS | 48 | TTL raw (0 = tắt dọn) |
| JC_RAW_SWEEP_MINUTES | 15 | Giãn cách tối thiểu giữa 2 lần quét raw |
| JC_JOB_DETAIL_BUDGET | 60 | Chi tiết tối đa mỗi nguồn/lượt deep |
| JC_QUICK_DETAIL_BUDGET | 15 | (script/provision) map sang `JC_JOB_DETAIL_BUDGET` cho lượt quick |
| JC_DETAIL_RECHECK_HOURS | 18 | Chỉ recheck chi tiết sau X giờ (phải < `JC_OPEN_CHECK_HOURS=24`) |
| JC_RECHECK_BUDGET_ITVIEC/TOPCV/TOPDEV | 45/110/25 | Budget mỗi lượt `verify_open` (mỗi giờ) |
| JC_COMPANY_ENRICH_BUDGET | 200 | Hồ sơ công ty làm giàu mỗi lượt (trước 90) |
| JC_COMMIT_BATCH | 50 | Số job/lần commit khi không cần Telegram từng job |
| JC_COMPANY_ENRICH_BUDGET | 90 | Hồ sơ làm giàu mỗi lượt |
| JC_PIPELINE_STALE_MINUTES | 1080 | Không có lượt OK trong X phút → cảnh báo (18h, hợp lịch 4 lượt/ngày) |
| JC_COMPANIES_STALE_MINUTES | 1080 | Ngưỡng riêng cho pipeline companies |
| JC_RUNNING_STALE_MINUTES | 60 | Lượt chưa kết thúc quá X phút → coi như treo |
| JC_TOPCV_SITEMAP_PAGES | 10 | Sub-sitemap mỗi lượt |
| JC_TOPDEV_COMPANY_PAGES | 10 | Trang danh bạ TopDev mỗi lượt |
| JC_OPEN_CHECK_HOURS | 24 | Hết bằng chứng "còn mở" |
| JC_DELAY | 2.0 | Giãn request mặc định, giây |
| JC_DELAY_ITVIEC/TOPCV/TOPDEV | 1.6/2.5/0.4 | Giãn request theo host (kèm jitter `JC_DELAY_JITTER`) |
| JC_IMPERSONATE | chrome136 | TLS profile chung |
| JC_MIN_FILL_RATE | 0.85 | Ngưỡng drift: dưới mức này → dừng + báo lỗi |
| JC_TOPDEV_PAGE_SIZE | 100 | Job/trang API TopDev (max 100) |
| JC_TOPDEV_ORDERING | newest | Sort listing TopDev |
| SUPABASE_DB_URL | — | Pooler Postgres cho sync + API production |
| VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY | — | Auth client (public key) |
| VITE_ALLOWED_EMAIL / ALLOWED_EMAIL | — | Email Google duy nhất được vào web |
| JC_TELEGRAM_ENABLED | 0 | Bật thông báo Telegram (cần token trong .env) |

## Cơ chế nội bộ đáng chú ý

- **Lock**: CLI lấy advisory lock theo phạm vi (per-source/companies/writer);
  bận → in `skipped` và exit 0, nhịp sau tự chạy.
- **Raw lifecycle**: sha256 content-addressed + gzip; `raw.sweep()` chạy sau
  mỗi lượt crawl (sau khi đã commit vào SQLite), manifest prune có flock.
- **Sync precompute**: provinces[] (locations.py), roles[] (roles.py),
  effective_status (open_condition) tính lúc sync để API Postgres chỉ lọc GIN.
- **Detail error policy**: lỗi từng tin = partial, retry 2h; company detail
  lỗi chờ 6h; thành công làm mới sau 14 ngày.
- **Telegram alerts**: job mới gửi ngay khi phát hiện (trước commit để retry
  được); pipeline lỗi/dừng gửi kèm nguồn + bước + run; watchdog `health` chạy
  10 phút/lần bắt trường hợp process bị kill (quá `JC_RUNNING_STALE_MINUTES`)
  hoặc nguồn im lặng quá `JC_PIPELINE_STALE_MINUTES`.
- **Per-source lock**: `source-<name>.lock` cho từng sàn, `companies.lock` cho
  danh bạ, `writer.lock` cho `all`/`recheck` — 3 pipeline chạy song song được.
- **Marks production ≠ local**: sao/apply trên web ghi vào Supabase và ở lại
  đó; local giữ marks riêng (chỉ `--full` mới đẩy marks).

## Dung lượng (đo 26/10/2026)

| Kho | Hiện tại | Tăng/ngày | Trần |
| --- | --- | --- | --- |
| SQLite local | ~70 MB | ~2–3 MB | vài GB/năm |
| Raw (gzip, TTL 48h) | ~2 GB | ~1 GB | ~2 GB |
| Supabase | ~84 MB | ~phẳng | 500 MB free tier |
| Backup migrate | ~207 MB | theo lần migrate | xoá tay được |

## Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
| --- | --- | --- |
| Windmill runs FAIL "another writer" / "database is locked" | 2 scheduler cùng chạy (Windmill + systemd timers) | `systemctl --user disable --now job-crawler-{crawl,deep,companies,sync}.timer`; chỉ Windmill |
| Telegram báo lỗi nhưng lịch sử Windmill toàn xanh | Lỗi đến từ systemd timer chạy ngoài Windmill | Tắt timer như trên; đối chiếu `journalctl --user -u job-crawler-crawl -n 50` |
| TopDev "no jobs" nhiều nhịp | Site đổi markup | Xem `journalctl`/logs, sửa parser `topdev.py` |
| Web production đứng data | Máy nhà tắt / sync lỗi | `scripts/local/check.sh`; bật Windmill |
| Login web bị từ chối | Sai email ALLOWED_EMAIL | Kiểm tra `.env` + Vercel env |
| Đĩa cạn | Raw TTL bị tắt | `JC_RAW_RETENTION_HOURS=48` + `job-crawler raw-gc` |
