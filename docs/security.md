# Bảo mật — trang private chỉ 1 tài khoản Google

Trang production `job-crawler-theta.vercel.app` là của riêng Huy: **chỉ
`dataguy.chill@gmail.com`** đăng nhập được, mọi người khác (kể cả khi biết
URL) không đọc được dữ liệu.

## Ba lớp bảo vệ (defense in depth)

| Lớp | Ở đâu | Chống lại |
| --- | --- | --- |
| 1. AuthGate — màn đăng nhập | `frontend/src/AuthGate.tsx` | Người vô tình/ghé qua — UX mượt, không spam 401 |
| 2. API khóa toàn bộ `/api/*` | `api/index.py` → `require_user` | Ai cũng gọi được API khi có URL — lớp **enforce thật sự**: mọi request cần `Authorization: Bearer <token>` do Supabase Auth cấp cho đúng `ALLOWED_EMAIL`, sai thì **401** |
| 3. RLS Postgres | policy trong `scripts/sync_supabase.py` → `apply_rls` | Biết cả URL **và** publishable key (nằm trong bundle JS): qua PostgREST, role `anon` bị REVOKE sạch, role `authenticated` chỉ SELECT khi JWT email đúng chủ |

Luồng đăng nhập: Google OAuth → Supabase Auth đổi code lấy session (PKCE) →
SPA giữ session (localStorage, tự refresh ~1h) → mọi fetch gắn Bearer token
(`frontend/src/api.ts` → `apiFetch`) → API verify token với Supabase (cache
dương tính 5 phút/token) + so email với `ALLOWED_EMAIL`.

Token sai / email lạ / hết hạn ⇒ API 401 ⇒ SPA tự `signOut()` về màn đăng nhập.
Tài khoản Google lạ đăng nhập thành công cũng bị: AuthGate hiện màn "không có
quyền" + signOut, và RLS chặn đọc dữ liệu trực tiếp.

## Đã cấu hình sẵn (tự động, không cần làm lại)

- Code: `api/index.py` (khóa API), `AuthGate.tsx` + `auth.ts` (login),
  `api.ts` (Bearer header + xử lý 401), nút logout ở nav.
- **RLS đã áp lên Supabase production** và được sync đảm bảo lại mỗi 15 phút
  (idempotent). Đã kiểm chứng: PostgREST với publishable key trả
  `permission denied for table jobs`.
- Env trong `.env`: `ALLOWED_EMAIL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`,
  `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_ALLOWED_EMAIL`.
- `scripts/local/deploy_vercel.sh` tự đẩy các env đó lên Vercel rồi deploy.

## Còn 1 lần làm trong console (~10 phút) — bắt buộc trước khi login được

### 1. Google Cloud Console → tạo OAuth client

1. <https://console.cloud.google.com> → chọn project (hoặc tạo mới, vd `job-crawler`).
2. **APIs & Services → OAuth consent screen**: User type **External**, tên app
   `Săn Việc`, email hỗ trợ = email của bạn. Ở bước Audience thêm
   `dataguy.chill@gmail.com` làm **test user** (app cá nhân để chế độ Testing
   là đủ, không cần publish).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**,
   loại **Web application**, Authorized redirect URIs:
   ```
   https://fcirnfihfkudcxuswydb.supabase.co/auth/v1/callback
   ```
4. Copy **Client ID** và **Client Secret**.

### 2. Supabase Dashboard → bật Google provider

1. <https://supabase.com/dashboard> → project `fcirnfihfkudcxuswydb` →
   **Authentication → Sign In / Providers → Google**: bật, dán Client ID/Secret.
2. **Authentication → URL Configuration**:
   - Site URL: `https://job-crawler-theta.vercel.app`
   - Redirect URLs: thêm `https://job-crawler-theta.vercel.app/**` và
     `http://localhost:5173/**` (dev).

### 3. Deploy

```bash
scripts/local/deploy_vercel.sh
```

## Kiểm chứng sau khi deploy

```bash
# 1. API khóa: kỳ vọng 401 (không token)
curl -s -o /dev/null -w '%{http_code}\n' https://job-crawler-theta.vercel.app/api/health
# 2. Token bừa: kỳ vọng 401
curl -s -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer xxx' \
  https://job-crawler-theta.vercel.app/api/health
# 3. PostgREST qua publishable key: kỳ vọng permission denied
curl -s "https://fcirnfihfkudcxuswydb.supabase.co/rest/v1/jobs?select=source&limit=1" \
  -H "apikey: $SUPABASE_PUBLISHABLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_PUBLISHABLE_KEY"
# 4. Mở trang: thấy màn "Đăng nhập bằng Google" → login đúng email → vào dashboard.
#    Thử email Google khác: bị chặn màn "không có quyền".
```

## Vận hành

- **Đổi tài khoản được phép**: sửa `ALLOWED_EMAIL` + `VITE_ALLOWED_EMAIL` trong
  `.env`; với Vercel phải `vercel env rm <tên> production preview` rồi chạy lại
  deploy script (env add không ghi đè giá trị cũ). RLS tự cập nhật trong lần
  sync ≤15 phút sau (hoặc chạy tay
  `.venv/bin/python scripts/sync_supabase.py`).
- **Thu hồi phiên ngay**: Supabase Dashboard → Authentication → Users →
  sign out tài khoản. Token API bị cache tối đa 5 phút/lần verify.
- **Dev local không muốn login**:
  ```bash
  AUTH_DISABLED=1 .venv/bin/python -m uvicorn api.index:app --port 8130
  ```
  (`AUTH_DISABLED` bị bỏ qua trên Vercel — biến `VERCEL=1` luôn có ở đó.)
- Dashboard local (`dashboard/main.py`, port 8130) vốn chỉ bind localhost,
  không đưa ra internet — giữ nguyên không cần auth.

## Mô hình tin cậy

- Publishable key trong bundle JS là **dự định công khai** — an toàn nhờ RLS.
- Secret thật (`SUPABASE_DB_URL`, `SUPABASE_SECRET_KEY`, Client Secret của
  Google) chỉ nằm trong `.env` (đã gitignore) và env của Vercel — không bao giờ
  xuống bundle.
- Nếu nghi lộ token: sign out user ở Supabase + xoá session; nếu nghi lộ DB
  password: đổi password Supabase rồi cập nhật `SUPABASE_DB_URL` ở Vercel.
