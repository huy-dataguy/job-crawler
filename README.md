# Săn Việc

Crawler việc IT Việt Nam (**ITviec · TopCV · TopDev**) xếp theo độ khớp CV,
danh bạ 65k+ công ty, web riêng xem ở đâu cũng được.

| Cổng | Địa chỉ | Dùng khi |
| --- | --- | --- |
| 🌐 **Web** | [job-crawler-theta.vercel.app](https://job-crawler-theta.vercel.app) | Xem việc mọi nơi (login Google, riêng tư) |
| 🏠 Dashboard local | `localhost:8130` | Xem nhanh trên máy |
| ⚙️ Windmill | `localhost:8132` | Coi/cạy pipeline (admin@windmill.dev / changeme) |

## Cách hoạt động (1 hình)

```
MÁY NHÀ                                CLOUD
Windmill ── crawl 15 phút ──► SQLite ── sync 15 phút ──► Supabase ◄── Vercel web
           (deep 4h37, companies :20)  (~2GB raw gzip      (RLS)      (FastAPI
                                            TTL 48h)                  serverless)
```

Máy nhà nuôi data; web chỉ đọc cloud. Push code → web cập nhật, dữ liệu không đổi.

## Chạy local (5 phút)

```bash
uv sync --extra dev && npm --prefix frontend ci && npm --prefix frontend run build
uv run job-crawler migrate        # schema (backup tự động nếu DB cũ)
uv run job-crawler all            # crawl thử 1 lượt
scripts/local/windmill.sh up      # bật tự động: Windmill + 4 lịch + UI
```

Xong. Mở lại máy là tự chạy tiếp (docker `unless-stopped`) — không cần gõ gì.

## Lệnh hay dùng

```bash
scripts/local/check.sh                    # sức khoẻ cả chuỗi (7 mục ✓)
scripts/local/windmill.sh runs            # 10 lượt chạy gần nhất
uv run job-crawler all | itviec | topcv | topdev | companies | deep
uv run job-crawler raw-gc                 # dọn raw tay
uv run pytest -q                          # 60 test
```

## Deploy production

```bash
scripts/local/deploy_vercel.sh    # hoặc nối GitHub trên Vercel để auto mỗi push
```

Cần env: `DATABASE_URL` (Vercel) + `SUPABASE_DB_URL`, `VITE_*`, `ALLOWED_EMAIL`
(`.env` — không commit). Setup Google OAuth lần đầu: **[docs/security.md](docs/security.md)**.

## Tính năng

Inbox 4 hướng ứng tuyển (DE/Backend/Fullstack/DS) + KN ≤2 năm, điểm khớp CV
0–100, lọc quy mô công ty/tỉnh thành/lương/nguồn, ★ sao + phím tắt (j/k/a/s/v/x),
router `/thong-ke` `/cong-ty` + filter trong URL, JD đầy đủ trong trang, card
công ty "đang tuyển gì", xuất CSV.

## Tài liệu

- **[docs/operations.md](docs/operations.md)** — lịch chạy, toàn bộ env, cơ chế
  nội bộ (writer.lock, raw lifecycle, sync precompute), dung lượng, xử lý sự cố
- [docs/security.md](docs/security.md) — bảo mật 3 lớp production
- [docs/architecture/design.md](docs/architecture/design.md) ·
  [docs/data/contracts.md](docs/data/contracts.md) — thiết kế & contract

## Stack

React 19 + Vite + Tailwind v4 · FastAPI · SQLite/Supabase Postgres ·
curl_cffi + BeautifulSoup (không browser) · Windmill · Vercel · uv + pytest.
