import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

export type Lang = "en" | "vi";

const STORAGE_KEY = "jc_lang";

// English is the source/default language: t(key) returns key when no vi override.
const VI: Record<string, string> = {};

export function registerVi(entries: Record<string, string>) {
  Object.assign(VI, entries);
}

let _lang: Lang = "en";
export function currentLang(): Lang { return _lang; }

export const I18nContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: "en", setLang: () => {} });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const saved = localStorage.getItem(STORAGE_KEY) as Lang | null;
    return saved === "vi" || saved === "en" ? saved : "en";
  });
  useEffect(() => { _lang = lang; localStorage.setItem(STORAGE_KEY, lang); document.documentElement.lang = lang; }, [lang]);
  const setLang = (l: Lang) => { _lang = l; setLangState(l); };
  return <I18nContext.Provider value={{ lang, setLang }}>{children}</I18nContext.Provider>;
}

export function useLang() { return useContext(I18nContext); }
export function useT() {
  const { lang } = useLang();
  return (key: string) => (lang === "vi" ? (VI[key] ?? key) : key);
}
