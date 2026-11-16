import type { ReactNode } from "react";
import { authConfigError, useAuth } from "./auth";
import Logo from "./Logo";
import { useT } from "./i18n";

export default function AuthGate({ children }: { children: ReactNode }) {
  const { state, signIn, retrySignIn } = useAuth();
  const t = useT();

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
        <Logo size={64} className="animate-[pulse_1.6s_ease-in-out_infinite]" />
        <p className="mt-4 font-mono text-xs text-faint">{t("Loading…")}</p>
      </Shell>
    );
  }

  if (state.status === "denied") {
    return (
      <Shell>
        <Card>
          <LogoMark />
          <p className="font-mono text-[11px] tracking-[0.18em] text-coral font-medium">{t("NO ACCESS")}</p>
          <h1 className="mt-3 text-[26px] font-extrabold tracking-tight leading-tight">
            {t("This account")} <em className="accent-italic">{t("is not invited")}</em>.
          </h1>
          <p className="mt-3 text-slate text-[14px] leading-relaxed">
            <span className="font-mono text-[13px]">{state.email}</span> {t("is not on the access list — this page is owner-only.")}
          </p>
          <button onClick={retrySignIn}
            className="mt-6 w-full rounded-full bg-white border border-line-deep px-6 py-3 font-bold text-[14px] shadow-hard press-hard">
            {t("Try another account")}
          </button>
        </Card>
      </Shell>
    );
  }

  if (state.status === "signedout") {
    return (
      <Shell>
        <Card>
          <LogoMark />
          <p className="font-mono text-[11px] tracking-[0.18em] text-mute font-medium flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-peri inline-block" aria-hidden />
            {t("PRIVATE · INVITED ACCOUNTS ONLY")}
          </p>
          <h1 className="mt-3 text-[28px] font-extrabold tracking-tight leading-[1.1]">
            {t("Sign in to open the job")} <em className="accent-italic">{t("queue")}</em>.
          </h1>
          <p className="mt-3 text-slate text-[14px] leading-relaxed">
            {t("This job-hunting dashboard is yours — sign in with your work Google account to continue.")}
          </p>
          <button onClick={signIn}
            className="mt-6 w-full rounded-full bg-white border border-line-deep px-6 py-3 font-bold text-[14px] text-ink shadow-hard press-hard flex items-center justify-center gap-3">
            <GoogleG /> {t("Sign in with Google")}
          </button>
          <p className="mt-4 font-mono text-[11px] text-faint text-center">
            {t("session issued by Supabase Auth · only 1 Google account allowed")}
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

function LogoMark() {
  return (
    <div className="flex items-center gap-3 mb-5">
      <Logo size={44} />
      <span className="font-extrabold tracking-tight text-[19px]">Job Hunt</span>
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
