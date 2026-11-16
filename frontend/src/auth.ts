import { useEffect, useRef, useState } from "react";
import { createClient } from "@supabase/supabase-js";
import type { Session } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;
export const ALLOWED_EMAIL = String(import.meta.env.VITE_ALLOWED_EMAIL || "").toLowerCase();

// null khi bản build thiếu cấu hình — AuthGate hiện lỗi hướng dẫn, không treo.
export const supabase = url && key ? createClient(url, key) : null;
export const authConfigError =
  !url || !key
    ? "Build is missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY — see docs/security.md."
    : null;

export type AuthState =
  | { status: "loading" }
  | { status: "signedout" }
  | { status: "denied"; email: string }
  | { status: "ok"; email: string };

/** Access token cho Authorization header; null khi chưa đăng nhập. */
export async function authToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  // Tài khoản lạ bị từ chối thì signOut ngay — nhưng vẫn giữ màn "không có
  // quyền" qua sự kiện session=null bắn ra sau đó (đỡ nhảy về login gây hiểu
  // nhầm là đăng nhập sai mật khẩu).
  const deniedEmail = useRef<string | null>(null);

  useEffect(() => {
    if (!supabase) return;
    const classify = (session: Session | null) => {
      if (deniedEmail.current) {
        setState({ status: "denied", email: deniedEmail.current });
        return;
      }
      if (!session) {
        setState({ status: "signedout" });
        return;
      }
      const email = (session.user.email || "").toLowerCase();
      if (email && email === ALLOWED_EMAIL) {
        setState({ status: "ok", email });
      } else {
        deniedEmail.current = email || "không rõ tài khoản";
        setState({ status: "denied", email: deniedEmail.current });
        supabase.auth.signOut(); // session của người lạ không nằm lại trên máy
      }
    };
    supabase.auth.getSession().then(({ data }) => classify(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) =>
      classify(session),
    );
    return () => sub.subscription.unsubscribe();
  }, []);

  const signIn = async () => {
    if (!supabase) return;
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin },
    });
  };

  const retrySignIn = () => {
    deniedEmail.current = null;
    if (supabase) supabase.auth.signOut();
    setState({ status: "signedout" });
  };

  const signOut = () => {
    deniedEmail.current = null;
    if (supabase) supabase.auth.signOut();
  };

  return { state, signIn, retrySignIn, signOut };
}
