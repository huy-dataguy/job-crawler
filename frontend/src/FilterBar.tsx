import { useState } from "react";
import type { Filters, Meta, MarkState } from "./api";
import type { Stats } from "./api";
import { BUCKET_COLOR } from "./company";
import { useT } from "./i18n";

const SINCE_OPTIONS = [
  { v: 0, label: "Any time" },
  { v: 24, label: "24h" },
  { v: 72, label: "3 days" },
  { v: 168, label: "7 days" },
  { v: 336, label: "14 days" },
];

const REL_OPTIONS = [
  { v: 0, label: "All" },
  { v: 40, label: "Match ≥40" },
  { v: 70, label: "Strong match ≥70" },
];

const MARK_TABS: { v: MarkState; label: string; countKey?: keyof NonNullable<Stats["queue"]> }[] = [
  { v: "all", label: "All" },
  { v: "unseen", label: "To review", countKey: "unseen" },
  { v: "starred", label: "★ Starred", countKey: "starred" },
  { v: "viewed", label: "Viewed", countKey: "viewed" },
  { v: "applied", label: "Applied", countKey: "applied" },
  { v: "hidden", label: "Not OK", countKey: "hidden" },
];

export default function FilterBar({ filters, setF, meta, stats }: {
  filters: Filters;
  setF: (f: Filters) => void;
  meta: Meta | undefined;
  stats: Stats | undefined;
}) {
  const t = useT();
  const [advOpen, setAdvOpen] = useState(false);
  const q = stats?.queue;

  // localized labels (kept as base English keys)
  const MARK_LABELS: Record<string, string> = {
    all: t("All"),
    unseen: t("To review"),
    starred: t("★ Starred"),
    viewed: t("Viewed"),
    applied: t("Applied"),
    hidden: t("Not OK"),
  };

  return (
    <div className="mt-4 space-y-2.5">
      <div className="flex items-center gap-1.5 flex-wrap">
        {MARK_TABS.map((tab) => {
          const active = filters.mark === tab.v;
          const n = q?.[tab.countKey!] ?? null;
          return (
            <button key={tab.v} onClick={() => setF({ ...filters, mark: tab.v, show_hidden: tab.v === "hidden" ? 1 : 0 })}
              className={`px-4 py-1.5 rounded-full text-sm font-semibold border transition
                ${active ? "bg-navy text-white border-navy shadow-hard-sm" : "bg-white text-slate border-line hover:border-line-deep hover:text-ink"}`}>
              {MARK_LABELS[tab.v]}
              {n != null && <span className={`font-mono text-xs ml-1.5 ${active ? "text-white/70" : "text-faint"}`}>{n}</span>}
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
        <Group label={t("Required experience")}>
          {[{ v: "", label: t("All") }, { v: "0", label: "Fresher" }, { v: "1", label: t("≤1 year") },
            { v: "2", label: t("≤2 years") }, { v: "3", label: t("≤3 years") }, { v: "5", label: t("≤5 years") }].map((o) => (
            <Chip key={o.v || "all"} active={filters.exp === o.v}
              onClick={() => setF({ ...filters, exp: o.v })}>{o.label}</Chip>
          ))}
        </Group>
        <Group label={t("Posted")}>
          {SINCE_OPTIONS.map((o) => (
            <Chip key={o.v} active={filters.since_hours === o.v}
              onClick={() => setF({ ...filters, since_hours: o.v })}>{t(o.label)}</Chip>
          ))}
        </Group>
        <Group label={t("Discovered")}>
          <Chip active={!filters.first_seen_today && !filters.first_seen_hours}
            onClick={() => setF({ ...filters, first_seen_today: 0, first_seen_hours: 0 })}>{t("All")}</Chip>
          <Chip active={!!filters.first_seen_today}
            onClick={() => setF({ ...filters, first_seen_today: 1, first_seen_hours: 0 })}>{t("Today")}</Chip>
          {[72, 168].map((v) => (
            <Chip key={v} active={filters.first_seen_hours === v}
              onClick={() => setF({ ...filters, first_seen_today: 0, first_seen_hours: v })}>
              {v === 72 ? t("3 days") : t("7 days")}
            </Chip>
          ))}
        </Group>
        <Group label={t("CV match")}>
          {REL_OPTIONS.map((o) => (
            <Chip key={o.v} active={filters.relevance_min === o.v}
              onClick={() => setF({ ...filters, relevance_min: o.v })}>{t(o.label)}</Chip>
          ))}
        </Group>
        <Group label={t("Salary")}>
          {[0, 20, 30, 40].map((v) => (
            <Chip key={v} active={filters.salary_min === v}
              onClick={() => setF({ ...filters, salary_min: v })}>{v === 0 ? t("All") : `≥${v}tr`}</Chip>
          ))}
        </Group>
      </div>

      <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
        <Group label={t("Company size")}>
          <Chip active={!filters.company_size}
            onClick={() => setF({ ...filters, company_size: "" })}>{t("All")}</Chip>
          {(meta?.company_sizes || []).map((s) => (
            <Chip key={s.bucket} active={filters.company_size === s.bucket}
              onClick={() => setF({ ...filters, company_size: filters.company_size === s.bucket ? "" : s.bucket })}>
              <span className="inline-flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: BUCKET_COLOR[s.bucket] }} aria-hidden />
                {s.bucket}
                <span className="font-mono text-[10px] opacity-60">{s.n}</span>
              </span>
            </Chip>
          ))}
        </Group>
        <Group label={t("Source")}>
          {[{ v: "", label: t("All") }, { v: "itviec", label: "ITviec" }, { v: "topcv", label: "TopCV" }, { v: "topdev", label: "TopDev" }].map((o) => (
            <Chip key={o.v || "all"} active={filters.source === o.v}
              onClick={() => setF({ ...filters, source: o.v })}>{o.label}</Chip>
          ))}
        </Group>
        <Group label={t("Status")}>
          {([{v:"open",label:t("Open")},{v:"unknown",label:t("Unverified")},{v:"closed",label:t("Closed")},{v:"all",label:t("All")}] as const).map(o =>
            <Chip key={o.v} active={filters.status === o.v} onClick={() => setF({...filters,status:o.v})}>{o.label}</Chip>)}
        </Group>
        <Group label={t("Work mode")}>
          <select aria-label={t("Work mode")} value={filters.work_mode} onChange={e=>setF({...filters,work_mode:e.target.value})}
            className="bg-white border border-line rounded-full px-3 py-1 text-xs text-slate focus:outline-none focus:border-peri">
            <option value="">{t("All modes")}</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">{t("Onsite")}</option>
          </select>
        </Group>
        <button onClick={() => setAdvOpen(!advOpen)}
          className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition ${advOpen ? "bg-peri-soft text-peri-deep border-peri/40" : "bg-white text-slate border-line hover:border-line-deep"}`}>
          {t("Advanced")} {advOpen ? "▴" : "▾"}
        </button>
      </div>

      {advOpen && (
        <div className="soft-card rounded-2xl p-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {meta && (
            <AdvGroup title={t("IT skills")}>
              <div className="flex flex-wrap gap-1.5 max-h-44 overflow-y-auto strip-scroll">
                {meta.top_skills.slice(0, 24).map((t2) => (
                  <Chip key={t2.name} active={filters.skill === t2.name}
                    onClick={() => setF({ ...filters, skill: filters.skill === t2.name ? "" : t2.name })}>
                    {t2.name} <span className="font-mono text-[10px] opacity-60">{t2.n}</span>
                  </Chip>
                ))}
              </div>
            </AdvGroup>
          )}
          {meta && (
            <AdvGroup title={t("Level")}>
              <div className="flex flex-wrap gap-1.5">
                {(meta.levels || []).filter((l) => l.n > 0).map((l) => (
                  <Chip key={l.value} active={filters.level === l.value}
                    onClick={() => setF({ ...filters, level: filters.level === l.value ? "" : l.value })}>
                    {l.value} <span className="font-mono text-[10px] opacity-60">{l.n}</span>
                  </Chip>
                ))}
              </div>
            </AdvGroup>
          )}
          {meta && (
            <AdvGroup title={t("Category")}>
              <div className="flex flex-wrap gap-1.5 max-h-44 overflow-y-auto strip-scroll">
                {meta.categories.slice(0, 16).map((c) => (
                  <Chip key={c.name} active={filters.category === c.name}
                    onClick={() => setF({ ...filters, category: filters.category === c.name ? "" : c.name })}>
                    {c.name} <span className="font-mono text-[10px] opacity-60">{c.n}</span>
                  </Chip>
                ))}
              </div>
            </AdvGroup>
          )}
          {meta && (
            <AdvGroup title={t("Original tag (TopCV)")}>
              <div className="flex flex-wrap gap-1.5 max-h-44 overflow-y-auto strip-scroll">
                {meta.top_tags.slice(0, 24).map((t2) => (
                  <Chip key={t2.name} active={filters.tag === t2.name}
                    onClick={() => setF({ ...filters, tag: filters.tag === t2.name ? "" : t2.name })}>
                    {t2.name} <span className="font-mono text-[10px] opacity-60">{t2.n}</span>
                  </Chip>
                ))}
              </div>
            </AdvGroup>
          )}
        </div>
      )}

      <ActivePills filters={filters} setF={setF} t={t} />
    </div>
  );
}

function Group({ label, children, highlight }: { label: string; children: React.ReactNode; highlight?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className={`font-mono text-[10px] uppercase tracking-wider ${highlight ? "text-peri font-semibold" : "text-faint"}`}>{label}</span>
      <div className="flex flex-wrap gap-0.5 rounded-full bg-white border border-line p-0.5 shadow-sm">{children}</div>
    </div>
  );
}

function AdvGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="font-mono text-[11px] text-faint mb-2 uppercase tracking-wider">{title}</h3>
      {children}
    </div>
  );
}

function Chip({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`px-2.5 py-1 rounded-full text-xs font-medium transition
        ${active ? "bg-peri text-white shadow-sm" : "text-slate hover:bg-paper hover:text-ink"}`}>
      {children}
    </button>
  );
}

function ActivePills({ filters, setF, t }: { filters: Filters; setF: (f: Filters) => void; t: (k: string) => string }) {
  const pills: { label: string; clear: () => void }[] = [];
  if (filters.q) pills.push({ label: `“${filters.q}”`, clear: () => setF({ ...filters, q: "" }) });
  if (filters.relevance_min) pills.push({ label: `${t("match")} ≥${filters.relevance_min}`, clear: () => setF({ ...filters, relevance_min: 0 }) });
  if (filters.source) pills.push({ label: `${t("source")} ${filters.source}`, clear: () => setF({ ...filters, source: "" }) });
  if (filters.company) pills.push({ label: `${t("company")} ${filters.company.slice(0, 30)}`, clear: () => setF({ ...filters, company: "" }) });
  if (filters.since_hours) pills.push({ label: `${t("posted")} ${SINCE_OPTIONS.find((o) => o.v === filters.since_hours)?.label}`, clear: () => setF({ ...filters, since_hours: 0 }) });
  if (filters.skill) pills.push({ label: `${t("skill")} ${filters.skill}`, clear: () => setF({ ...filters, skill: "" }) });
  if (filters.category) pills.push({ label: `${t("category")} ${filters.category}`, clear: () => setF({ ...filters, category: "" }) });
  if (filters.exp) pills.push({ label: `${t("exp ≤")} ${filters.exp} ${t("years")}`, clear: () => setF({ ...filters, exp: "" }) });
  if (filters.level) pills.push({ label: `${t("level")} ${filters.level}`, clear: () => setF({ ...filters, level: "" }) });
  if (filters.salary_min) pills.push({ label: `${t("salary ≥")} ${filters.salary_min}tr`, clear: () => setF({ ...filters, salary_min: 0 }) });
  if (filters.tag) pills.push({ label: `${t("tag")} ${filters.tag}`, clear: () => setF({ ...filters, tag: "" }) });
  if (filters.company_size) pills.push({ label: `${t("size")} ${filters.company_size}`, clear: () => setF({ ...filters, company_size: "" }) });
  if (pills.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 flex-wrap" aria-live="polite">
      <span className="font-mono text-[11px] text-faint">{t("filtering:")}</span>
      {pills.map((p) => (
        <button key={p.label} onClick={p.clear} title={t("Remove this filter")}
          className="px-2.5 py-1 rounded-full text-[12px] bg-peri-soft text-peri-deep border border-peri/30 font-medium hover:bg-peri/15 transition">
          {p.label} <span aria-hidden>×</span>
        </button>
      ))}
    </div>
  );
}
