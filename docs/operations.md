# Vận hành chi tiết

Chi tiết kỹ thuật cho người vận hành — README chỉ giữ phần dùng hằng ngày.

## Lịch chạy (Windmill, timezone Asia/Ho_Chi_Minh)

| Schedule | Cron | Script | Việc |
| --- | --- | --- | --- |
| crawl_15min | `0 */15 * * * *` | crawl_all | Quét 2 trang/nguồn (job mới nằm đầu listing) |
| sync_15min | `0 10-59/15 * * * *` | sync_supabase | Đẩy SQLite → Supabase (production) |
| companies_hour | `0 20 * * * *` | companies | Làm giàu danh bạ |
| deep_daily | `0 37 4 * * *` | deep | Quét đủ sâu 50/20/40 trang + kiểm tra còn mở |

Có `no_flow_overlap` chống chồng chéo. Windmill không chạy bù nhịp lỡ; mốc 15
phút đầu sau khi mở máy là data tươi lại.

## Toàn bộ biến cấu hình

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| JC_DATA_DIR / JC_DB_PATH | ./data | Vị trí SQLite, raw, lock |
| JC_MAX_PAGES_ITVIEC/TOPCV/TOPDEV | 2/2/2 | Trang mỗi lượt quick |
| JC_DEEP_PAGES_ITVIEC/TOPCV/TOPDEV | 50/20/40 | Lượt sâu hằng ngày |
| JC_RAW_RETENTION_HOURS | 48 | TTL raw (0 = tắt dọn) |
| JC_JOB_DETAIL_BUDGET | 60 | Chi tiết tối đa mỗi nguồn/lượt |
| JC_COMPANY_ENRICH_BUDGET | 90 | Hồ sơ làm giàu mỗi lượt |
| JC_TOPCV_SITEMAP_PAGES | 10 | Sub-sitemap mỗi lượt |
| JC_TOPDEV_COMPANY_PAGES | 10 | Trang danh bạ TopDev mỗi lượt |
| JC_OPEN_CHECK_HOURS | 24 | Hết bằng chứng "còn mở" |
| JC_DELAY | 2.0 | Giãn request, giây |
| SUPABASE_DB_URL | — | Pooler Postgres cho sync + API production |
| VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY | — | Auth client (public key) |
| VITE_ALLOWED_EMAIL / ALLOWED_EMAIL | — | Email Google duy nhất được vào web |
| JC_TELEGRAM_ENABLED | 0 | Bật thông báo Telegram (cần token trong .env) |

## Cơ chế nội bộ đáng chú ý

- **writer.lock**: mọi CLI chia sẻ advisory lock; bận → exit 75, thử lại sau.
- **Raw lifecycle**: sha256 content-addressed + gzip; `raw.sweep()` chạy sau
  mỗi lượt crawl (sau khi đã commit vào SQLite), manifest prune có flock.
- **Sync precompute**: provinces[] (locations.py), roles[] (roles.py),
  effective_status (open_condition) tính lúc sync để API Postgres chỉ lọc GIN.
- **Detail error policy**: lỗi từng tin = partial, retry 2h; company detail
  lỗi chờ 6h; thành công làm mới sau 14 ngày.
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
| Windmill runs FAIL "another writer" | 2 scheduler cùng chạy | Tắt systemd timers; chỉ 1 scheduler |
| TopDev "no jobs" nhiều nhịp | Site đổi markup | Xem `journalctl`/logs, sửa parser `topdev.py` |
| Web production đứng data | Máy nhà tắt / sync lỗi | `scripts/local/check.sh`; bật Windmill |
| Login web bị từ chối | Sai email ALLOWED_EMAIL | Kiểm tra `.env` + Vercel env |
| Đĩa cạn | Raw TTL bị tắt | `JC_RAW_RETENTION_HOURS=48` + `job-crawler raw-gc` |
