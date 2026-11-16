import { MY_ROLES } from "./api";
import { useT } from "./i18n";

export default function RoleSwitcher({ counts, value, onChange }: {
  counts?: Record<string, number>;
  value: string;
  onChange: (role: string) => void;
}) {
  const t = useT();
  const selected = new Set(value.split(",").map(s => s.trim()).filter(Boolean));
  const toggle = (slug: string) => {
    const next = new Set(selected);
    if (next.has(slug)) next.delete(slug); else next.add(slug);
    onChange(MY_ROLES.filter(r => next.has(r.slug)).map(r => r.slug).join(","));
  };

  return (
    <section aria-label={t("Target roles")}>
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="font-mono text-[11px] tracking-[0.18em] text-mute font-medium">{t("TARGET ROLES")}</h2>
        {!selected.size && (
          <button onClick={() => onChange(MY_ROLES.map(r => r.slug).join(","))}
            className="text-[13px] font-semibold text-peri hover:text-peri-deep">
            {t("Select all 4 roles ✓")}
          </button>
        )}
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        {MY_ROLES.map((r) => {
          const active = selected.has(r.slug);
          const n = counts?.[r.slug];
          return (
            <button key={r.slug} onClick={() => toggle(r.slug)} aria-pressed={active}
              className={`group text-left rounded-2xl px-4 py-3.5 border transition-all
                ${active
                  ? "bg-navy text-white border-navy shadow-hard press-hard"
                  : "soft-card hover:border-line-deep hover:-translate-y-px"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className={`font-bold text-[15px] ${active ? "text-white" : "text-ink"}`}>{r.name}</span>
                {r.main
                  ? <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-bold ${active ? "bg-sun text-ink" : "bg-amber-soft text-amber"}`}>{t("MAIN")}</span>
                  : null}
              </div>
              <p className={`mt-0.5 text-xs ${active ? "text-white/60" : "text-mute"}`}>{r.desc}</p>
              <p className={`mt-2 font-mono text-[12px] ${active ? "text-white/80" : "text-faint"}`}>
                {n != null ? <><span className={active ? "text-sun" : "text-peri"}>{n}</span> {t("jobs waiting")}</> : t("— jobs")}
              </p>
            </button>
          );
        })}
      </div>
      {!selected.size && (
        <p className="mt-2 text-[13px] text-slate">
          {t("Viewing")} <strong>{t("all IT fields")}</strong> — {t("not limited to the 4 target roles.")}
        </p>
      )}
    </section>
  );
}
