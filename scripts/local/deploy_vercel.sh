#!/usr/bin/env bash
# Deploy production lên Vercel: API (api/index.py → serverless) + SPA (frontend/dist).
# Nạp biến môi trường từ .env (Supabase + auth) rồi `vercel --prod`.
# Lần đầu chạy sẽ hỏi liên kết project — chấp nhận default.
# Lưu ý: đổi GIÁ TRỊ biến thì phải `vercel env rm <tên> production preview` trước,
# script chỉ add khi biến chưa tồn tại.
set -euo pipefail
cd "$(dirname "$0")/../.."

set -a; source .env; set +a
: "${SUPABASE_DB_URL:?Thêm SUPABASE_DB_URL vào .env}"
: "${SUPABASE_URL:?Thêm SUPABASE_URL vào .env}"
: "${SUPABASE_PUBLISHABLE_KEY:?Thêm SUPABASE_PUBLISHABLE_KEY vào .env}"
: "${ALLOWED_EMAIL:?Thêm ALLOWED_EMAIL vào .env}"
: "${VITE_SUPABASE_URL:?Thêm VITE_SUPABASE_URL vào .env}"
: "${VITE_SUPABASE_ANON_KEY:?Thêm VITE_SUPABASE_ANON_KEY vào .env}"
: "${VITE_ALLOWED_EMAIL:?Thêm VITE_ALLOWED_EMAIL vào .env}"

if ! vercel whoami >/dev/null 2>&1; then
  echo "Chưa đăng nhập Vercel — chạy: vercel login  (rồi gọi lại script này)" >&2
  exit 1
fi

# env cho deployment (chạy 1 lần là đủ; lặp lại không hại — biến đã có sẽ báo
# lỗi và được bỏ qua; ĐỔI GIÁ TRỊ thì vercel env rm <tên> trước).
# CLI 54 không nhận nhiều target cùng lệnh nữa → add từng target một.
# VITE_* cần ở môi trường build để Vite nhúng vào bundle; DATABASE_URL cho
# function runtime; SUPABASE_URL/PUBLISHABLE_KEY/ALLOWED_EMAIL để verify token.
for kv in \
  "DATABASE_URL=$SUPABASE_DB_URL" \
  "SUPABASE_URL=$SUPABASE_URL" \
  "SUPABASE_PUBLISHABLE_KEY=$SUPABASE_PUBLISHABLE_KEY" \
  "ALLOWED_EMAIL=$ALLOWED_EMAIL" \
  "VITE_SUPABASE_URL=$VITE_SUPABASE_URL" \
  "VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY" \
  "VITE_ALLOWED_EMAIL=$VITE_ALLOWED_EMAIL"; do
  for target in production preview; do
    vercel env add "${kv%%=*}" "$target" <<< "${kv#*=}" 2>&1 | grep -v "Removed trailing newline" || true
  done
done

if [ ! -d .vercel ]; then
  vercel link
fi
vercel --prod
echo "Xong. Kiểm tra (kỳ vọng 401): curl -s -o /dev/null -w '%{http_code}\n' <URL>/api/health"
