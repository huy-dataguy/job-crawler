import { useState } from "react";
import type { Filters, Meta, MarkState } from "./api";
import type { Stats } from "./api";

const SINCE_OPTIONS = [
  { v: 0, label: "Mọi lúc" },
  { v: 24, label: "24h" },
  { v: 72, label: "3 ngày" },
  { v: 168, label: "7 ngày" },
];

const REL_OPTIONS = [
  { v: 0, label: "Tất cả" },
  { v: 40, label: "Khớp ≥40" },
  { v: 70, label: "Rất khớp ≥70" },
];

const MARK_TABS: { v: MarkState; label: string; countKey?: keyof Stats["queue"] }[] = [
  { v: "unseen", label: "Cần xem", countKey: "unseen" },
  { v: "viewed", label: "Đã xem", countKey: "viewed" },
  { v: "applied", label: "Đã apply", countKey: "applied" },
  { v: "hidden", label: "Không OK", countKey: "hidden" },
];

export default function FilterBar({ filters, setF, meta, stats }: {
  filters: Filters;
  setF: (f: Filters) => void;
  meta: Meta | undefined;
  stats: Stats | undefined;
}) {
  const [advOpen, setAdvOpen] = useState(false);
  const q = stats?.queue;

  return (
    <div className="space-y-2.5">
      {/* Tabs trạng thái review — inbox */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {MARK_TABS.map((t) => {
          const active = filters.mark === t.v;
          const n = q?.[t.countKey!] ?? null;
          return (
            <button key={t.v} onClick={() => setF({ ...filters, mark: t.v, show_hidden: t.v === "hidden" ? 1 : 0 })}
              className={`px-3.5 py-1.5 rounded-full text-sm font-semibold border transition
                ${active ? "bg-gradient-to-r from-ember to-[#ff8a3c] text-white border-transparent shadow" : "bg-panel text-dim border-edge hover:border-faint hover:text-mist"}`}>
              {t.label}
              {n != null && <span className={`font-mono text-xs ml-1.5 ${active ? "text-white/85" : "text-faint"}`}>{n}</span>}
            </button>
          );
        })}
      </div>

      {/* Chip lọc nhanh */}
      <div className="flex items-center gap-2 flex-wrap">
        <Group label="Khớp profile">
          {REL_OPTIONS.map((o) => (
            <Chip key={o.v} active={filters.relevance_min === o.v}
              onClick={() => setF({ ...filters, relevance_min: o.v })}>{o.label}</Chip>
          ))}
        </Group>
        <Group label="Đăng">
          {SINCE_OPTIONS.map((o) => (
            <Chip key={o.v} active={filters.since_hours === o.v}
              onClick={() => setF({ ...filters, since_hours: o.v })}>{o.label}</Chip>
          ))}
        </Group>
        <Group label="Nguồn">
          {[{ v: "", label: "Tất cả" }, { v: "itviec", label: "ITviec" }, { v: "topcv", label: "TopCV" }, { v: "topdev", label: "TopDev" }].map((o) => (
            <Chip key={o.v || "all"} active={filters.source === o.v}
              onClick={() => setF({ ...filters, source: o.v })}>{o.label}</Chip>
          ))}
        </Group>
        <Group label="Lương">
          {[0, 20, 30, 40].map((v) => (
            <Chip key={v} active={filters.salary_min === v}
              onClick={() => setF({ ...filters, salary_min: v })}>{v === 0 ? "Tất cả" : `≥${v}tr`}</Chip>
          ))}
        </Group>
        <button onClick={() => setAdvOpen(!advOpen)}
          className={`px-3 py-1 rounded-full text-xs font-medium border transition ${advOpen ? "bg-violet/15 text-violet border-violet/40" : "bg-panel text-dim border-edge hover:border-faint"}`}>
          Nâng cao {advOpen ? "▴" : "▾"}
        </button>
      </div>

      {/* Bộ lọc nâng cao — chỉ mở khi cần */}
      {advOpen && (
        <div className="bg-panel border border-edge rounded-[14px] p-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {meta && (
            <AdvGroup title="Kỹ năng IT">
              <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
                {meta.top_skills.slice(0, 24).map((t) => (
                  <Chip key={t.name} active={filters.skill === t.name}
                    onClick={() => setF({ ...filters, skill: filters.skill === t.name ? "" : t.name })}>
                    {t.name} <span className="font-mono text-[10px] opacity-60">{t.n}</span>
                  </Chip>
                ))}
              </div>
            </AdvGroup>
          )}
          {meta && (
            <AdvGroup title="Cấp bậc">
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
            <AdvGroup title="Ngành">
              <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
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
            <AdvGroup title="Năm kinh nghiệm">
              <div className="flex flex-wrap gap-1.5">
                {meta.experience.map((e) => (
                  <Chip key={e.value} active={filters.exp === e.value}
                    onClick={() => setF({ ...filters, exp: filters.exp === e.value ? "" : e.value })}>
                    {e.name} <span className="font-mono text-[10px] opacity-60">{e.n}</span>
                  </Chip>
                ))}
              </div>
            </AdvGroup>
          )}
          <AdvGroup title="Quy mô công ty">
            <div className="flex flex-wrap gap-1.5">
              {["", "<50", "50-100", "101-150", "151-300", "301-1000", "1000+"].map((v) => (
                <Chip key={v || "all"} active={filters.company_size === v}
                  onClick={() => setF({ ...filters, company_size: v })}>{v || "Tất cả"}</Chip>
              ))}
            </div>
          </AdvGroup>
          {meta && (
            <AdvGroup title="Tag gốc (TopCV)">
              <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
                {meta.top_tags.slice(0, 24).map((t) => (
                  <Chip key={t.name} active={filters.tag === t.name}
                    onClick={() => setF({ ...filters, tag: filters.tag === t.name ? "" : t.name })}>
                    {t.name} <span className="font-mono text-[10px] opacity-60">{t.n}</span>
                  </Chip>
                ))}
              </div>
            </AdvGroup>
          )}
        </div>
      )}

      <ActivePills filters={filters} setF={setF} />
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="font-mono text-[10px] uppercase tracking-wide text-faint">{label}</span>
      <div className="flex rounded-full bg-night border border-edge p-0.5">{children}</div>
    </div>
  );
}

function AdvGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="font-mono text-xs text-faint mb-2">{title}</h3>
      {children}
    </div>
  );
}

function Chip({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`px-2.5 py-1 rounded-full text-xs font-medium transition
        ${active ? "bg-ember text-white" : "text-dim hover:text-mist"}`}>
      {children}
    </button>
  );
}

function ActivePills({ filters, setF }: { filters: Filters; setF: (f: Filters) => void }) {
  const pills: { label: string; clear: () => void }[] = [];
  if (filters.q) pills.push({ label: `“${filters.q}”`, clear: () => setF({ ...filters, q: "" }) });
  if (filters.relevance_min) pills.push({ label: `khớp ≥${filters.relevance_min}`, clear: () => setF({ ...filters, relevance_min: 0 }) });
  if (filters.source) pills.push({ label: `nguồn ${filters.source}`, clear: () => setF({ ...filters, source: "" }) });
  if (filters.since_hours) pills.push({ label: `đăng ${SINCE_OPTIONS.find((o) => o.v === filters.since_hours)?.label}`, clear: () => setF({ ...filters, since_hours: 0 }) });
  if (filters.skill) pills.push({ label: `kỹ năng ${filters.skill}`, clear: () => setF({ ...filters, skill: "" }) });
  if (filters.category) pills.push({ label: `ngành ${filters.category}`, clear: () => setF({ ...filters, category: "" }) });
  if (filters.exp) pills.push({ label: `${filters.exp} năm KN`, clear: () => setF({ ...filters, exp: "" }) });
  if (filters.level) pills.push({ label: `cấp ${filters.level}`, clear: () => setF({ ...filters, level: "" }) });
  if (filters.salary_min) pills.push({ label: `lương ≥ ${filters.salary_min}tr`, clear: () => setF({ ...filters, salary_min: 0 }) });
  if (filters.tag) pills.push({ label: `tag ${filters.tag}`, clear: () => setF({ ...filters, tag: "" }) });
  if (filters.company_size) pills.push({ label: `quy mô ${filters.company_size}`, clear: () => setF({ ...filters, company_size: "" }) });
  if (pills.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 flex-wrap" aria-live="polite">
      <span className="font-mono text-xs text-faint">đang lọc:</span>
      {pills.map((p) => (
        <button key={p.label} onClick={p.clear} title="Gỡ lọc này"
          className="px-2.5 py-1 rounded-full text-[13px] bg-violet/15 text-violet border border-violet/30 font-medium hover:bg-violet/25 transition">
          {p.label} <span aria-hidden>×</span>
        </button>
      ))}
    </div>
  );
}
