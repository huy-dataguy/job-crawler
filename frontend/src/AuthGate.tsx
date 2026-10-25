import type { ReactNode } from "react";
import { authConfigError, useAuth } from "./auth";

// Cổng đăng nhập: trang là của riêng chủ sở hữu — API từ chối mọi request
// không có token hợp lệ của ALLOWED_EMAIL, nên gate này chỉ để UX mượt (không
// spam 401); lớp enforce thật nằm ở api/index.py và RLS Postgres.
export default function AuthGate({ children }: { children: ReactNode }) {
  const { state, signIn, retrySignIn } = useAuth();

  if (authConfigError) {
    return (
      <Shell>
        <p className="font-mono text-[12px] text-coral leading-relaxed">{authConfigError}</p>
      </Shell>
    );
  }

  if (state.status === "loading") {
    return (
      <Shell>
        <div className="w-11 h-11 rounded-[14px] bg-gradient-to-br from-peri to-coral text-white font-extrabold flex items-center justify-center text-xl animate-pulse">J</div>
        <p className="mt-4 font-mono text-xs text-faint">đang mở khóa…</p>
      </Shell>
    );
  }

  if (state.status === "denied") {
    return (
      <Shell>
        <Card>
          <Logo />
          <p className="font-mono text-[11px] tracking-[0.18em] text-coral font-medium">KHÔNG CÓ QUYỀN TRUY CẬP</p>
          <h1 className="mt-3 text-[26px] font-extrabold tracking-tight leading-tight">
            Tài khoản này <em className="accent-italic">không được mời</em>.
          </h1>
          <p className="mt-3 text-slate text-[14px] leading-relaxed">
            <span className="font-mono text-[13px]">{state.email}</span> không nằm trong
            danh sách truy cập — trang này chỉ dành cho chủ sở hữu.
          </p>
          <button onClick={retrySignIn}
            className="mt-6 w-full rounded-full bg-white border border-line-deep px-6 py-3 font-bold text-[14px] shadow-hard press-hard">
            Thử tài khoản khác
          </button>
        </Card>
      </Shell>
    );
  }

  if (state.status === "signedout") {
    return (
      <Shell>
        <Card>
          <Logo />
          <p className="font-mono text-[11px] tracking-[0.18em] text-mute font-medium flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-peri inline-block" aria-hidden />
            RIÊNG TƯ · CHỈ TÀI KHOẢN ĐƯỢC MỜI
          </p>
          <h1 className="mt-3 text-[28px] font-extrabold tracking-tight leading-[1.1]">
            Đăng nhập để mở <em className="accent-italic">hàng đợi</em> việc làm.
          </h1>
          <p className="mt-3 text-slate text-[14px] leading-relaxed">
            Dashboard săn việc này là của riêng bạn — đăng nhập bằng Google tài khoản
            công việc để tiếp tục.
          </p>
          <button onClick={signIn}
            className="mt-6 w-full rounded-full bg-white border border-line-deep px-6 py-3 font-bold text-[14px] text-ink shadow-hard press-hard flex items-center justify-center gap-3">
            <GoogleG /> Đăng nhập bằng Google
          </button>
          <p className="mt-4 font-mono text-[11px] text-faint text-center">
            phiên do Supabase Auth cấp · chỉ 1 tài khoản Google được phép
          </p>
        </Card>
      </Shell>
    );
  }

  return <>{children}</>;
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen paper-bg text-ink flex items-center justify-center px-4">
      <div className="flex flex-col items-center">{children}</div>
    </div>
  );
}

function Card({ children }: { children: ReactNode }) {
  return (
    <div className="soft-card rounded-3xl px-7 py-9 sm:px-10 w-full max-w-[400px] mt-8 flex flex-col items-center text-center">
      {children}
    </div>
  );
}

function Logo() {
  return (
    <div className="flex items-center gap-2.5 mb-5">
      <span className="w-9 h-9 rounded-[11px] bg-gradient-to-br from-peri to-coral text-white font-extrabold flex items-center justify-center text-lg">J</span>
      <span className="font-extrabold tracking-tight text-[17px]">Săn Việc</span>
    </div>
  );
}

function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path fill="#FFC107" d="M43.611 20.083H42V20H24v8h11.303c-1.649 4.657-6.08 8-11.303 8-6.627 0-12-5.373-12-12s5.373-12 12-12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.65-.389-3.917z" />
      <path fill="#FF3D00" d="M6.306 14.691l6.571 4.819C14.655 15.108 18.961 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 16.318 4 9.656 8.337 6.306 14.691z" />
      <path fill="#4CAF50" d="M24 44c5.166 0 9.86-1.977 13.409-5.192l-6.19-5.238C29.211 35.091 26.715 36 24 36c-5.202 0-9.619-3.317-11.283-7.946l-6.522 5.025C9.505 39.556 16.227 44 24 44z" />
      <path fill="#1976D2" d="M43.611 20.083H42V20H24v8h11.303c-.792 2.237-2.231 4.166-4.087 5.571l.003-.002 6.19 5.238C36.971 39.205 44 34 44 24c0-1.341-.138-2.65-.389-3.917z" />
    </svg>
  );
}
