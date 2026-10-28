import { useState } from "react";
import type { Filters, Meta, MarkState } from "./api";
import type { Stats } from "./api";
import { BUCKET_COLOR } from "./company";

const SINCE_OPTIONS = [
  { v: 0, label: "Mọi lúc" },
  { v: 24, label: "24h" },
  { v: 72, label: "3 ngày" },
  { v: 168, label: "7 ngày" },
  { v: 336, label: "14 ngày" },
];

const REL_OPTIONS = [
  { v: 0, label: "Tất cả" },
  { v: 40, label: "Khớp ≥40" },
  { v: 70, label: "Rất khớp ≥70" },
];

const MARK_TABS: { v: MarkState; label: string; countKey?: keyof NonNullable<Stats["queue"]> }[] = [
  { v: "all", label: "Tất cả" },
  { v: "unseen", label: "Cần xem", countKey: "unseen" },
  { v: "starred", label: "★ Đã sao", countKey: "starred" },
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
    <div className="mt-4 space-y-2.5">
      {/* Tabs trạng thái review — inbox: active là pill navy kiểu techvibe */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {MARK_TABS.map((t) => {
          const active = filters.mark === t.v;
          const n = q?.[t.countKey!] ?? null;
          return (
            <button key={t.v} onClick={() => setF({ ...filters, mark: t.v, show_hidden: t.v === "hidden" ? 1 : 0 })}
              className={`px-4 py-1.5 rounded-full text-sm font-semibold border transition
                ${active ? "bg-navy text-white border-navy shadow-hard-sm" : "bg-white text-slate border-line hover:border-line-deep hover:text-ink"}`}>
              {t.label}
              {n != null && <span className={`font-mono text-xs ml-1.5 ${active ? "text-white/70" : "text-faint"}`}>{n}</span>}
            </button>
          );
        })}
      </div>

      {/* Chip lọc nhanh — nhóm KN lên trước vì ≤2 năm là ràng buộc chính */}
      <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
        <Group label="KN yêu cầu" highlight>
          {[{ v: "", label: "Tất cả" }, { v: "0", label: "Fresher" }, { v: "1", label: "≤1 năm" },
            { v: "2", label: "≤2 năm" }, { v: "3", label: "≤3 năm" }, { v: "5", label: "≤5 năm" }].map((o) => (
            <Chip key={o.v || "all"} active={filters.exp === o.v}
              onClick={() => setF({ ...filters, exp: o.v })}>{o.label}</Chip>
          ))}
        </Group>
        <Group label="Đăng">
          {SINCE_OPTIONS.map((o) => (
            <Chip key={o.v} active={filters.since_hours === o.v}
              onClick={() => setF({ ...filters, since_hours: o.v })}>{o.label}</Chip>
          ))}
        </Group>
        <Group label="Phát hiện">
          <Chip active={!filters.first_seen_today && !filters.first_seen_hours}
            onClick={() => setF({ ...filters, first_seen_today: 0, first_seen_hours: 0 })}>Tất cả</Chip>
          <Chip active={!!filters.first_seen_today}
            onClick={() => setF({ ...filters, first_seen_today: 1, first_seen_hours: 0 })}>Hôm nay</Chip>
          {[72, 168].map((v) => (
            <Chip key={v} active={filters.first_seen_hours === v}
              onClick={() => setF({ ...filters, first_seen_today: 0, first_seen_hours: v })}>
              {v === 72 ? "3 ngày" : "7 ngày"}
            </Chip>
          ))}
        </Group>
        <Group label="Khớp CV">
          {REL_OPTIONS.map((o) => (
            <Chip key={o.v} active={filters.relevance_min === o.v}
              onClick={() => setF({ ...filters, relevance_min: o.v })}>{o.label}</Chip>
          ))}
        </Group>
        <Group label="Lương">
          {[0, 20, 30, 40].map((v) => (
            <Chip key={v} active={filters.salary_min === v}
              onClick={() => setF({ ...filters, salary_min: v })}>{v === 0 ? "Tất cả" : `≥${v}tr`}</Chip>
          ))}
        </Group>
      </div>

      <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
        <Group label="Quy mô công ty">
          <Chip active={!filters.company_size}
            onClick={() => setF({ ...filters, company_size: "" })}>Tất cả</Chip>
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
        <Group label="Nguồn">
          {[{ v: "", label: "Tất cả" }, { v: "itviec", label: "ITviec" }, { v: "topcv", label: "TopCV" }, { v: "topdev", label: "TopDev" }].map((o) => (
            <Chip key={o.v || "all"} active={filters.source === o.v}
              onClick={() => setF({ ...filters, source: o.v })}>{o.label}</Chip>
          ))}
        </Group>
        <Group label="Tình trạng">
          {([{v:"open",label:"Còn mở"},{v:"unknown",label:"Chưa xác nhận"},{v:"closed",label:"Đã đóng"},{v:"all",label:"Tất cả"}] as const).map(o =>
            <Chip key={o.v} active={filters.status === o.v} onClick={() => setF({...filters,status:o.v})}>{o.label}</Chip>)}
        </Group>
        <Group label="Hình thức">
          <select aria-label="Hình thức làm việc" value={filters.work_mode} onChange={e=>setF({...filters,work_mode:e.target.value})}
            className="bg-white border border-line rounded-full px-3 py-1 text-xs text-slate focus:outline-none focus:border-peri">
            <option value="">Mọi hình thức</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">Tại văn phòng</option>
          </select>
        </Group>
        <button onClick={() => setAdvOpen(!advOpen)}
          className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition ${advOpen ? "bg-peri-soft text-peri-deep border-peri/40" : "bg-white text-slate border-line hover:border-line-deep"}`}>
          Nâng cao {advOpen ? "▴" : "▾"}
        </button>
      </div>

      {/* Bộ lọc nâng cao — chỉ mở khi cần */}
      {advOpen && (
        <div className="soft-card rounded-2xl p-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {meta && (
            <AdvGroup title="Kỹ năng IT">
              <div className="flex flex-wrap gap-1.5 max-h-44 overflow-y-auto strip-scroll">
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
            <AdvGroup title="Tag gốc (TopCV)">
              <div className="flex flex-wrap gap-1.5 max-h-44 overflow-y-auto strip-scroll">
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

function ActivePills({ filters, setF }: { filters: Filters; setF: (f: Filters) => void }) {
  const pills: { label: string; clear: () => void }[] = [];
  if (filters.q) pills.push({ label: `“${filters.q}”`, clear: () => setF({ ...filters, q: "" }) });
  if (filters.relevance_min) pills.push({ label: `khớp ≥${filters.relevance_min}`, clear: () => setF({ ...filters, relevance_min: 0 }) });
  if (filters.source) pills.push({ label: `nguồn ${filters.source}`, clear: () => setF({ ...filters, source: "" }) });
  if (filters.company) pills.push({ label: `công ty ${filters.company.slice(0, 30)}`, clear: () => setF({ ...filters, company: "" }) });
  if (filters.since_hours) pills.push({ label: `đăng ${SINCE_OPTIONS.find((o) => o.v === filters.since_hours)?.label}`, clear: () => setF({ ...filters, since_hours: 0 }) });
  if (filters.skill) pills.push({ label: `kỹ năng ${filters.skill}`, clear: () => setF({ ...filters, skill: "" }) });
  if (filters.category) pills.push({ label: `ngành ${filters.category}`, clear: () => setF({ ...filters, category: "" }) });
  if (filters.exp) pills.push({ label: `KN ≤ ${filters.exp} năm`, clear: () => setF({ ...filters, exp: "" }) });
  if (filters.level) pills.push({ label: `cấp ${filters.level}`, clear: () => setF({ ...filters, level: "" }) });
  if (filters.salary_min) pills.push({ label: `lương ≥ ${filters.salary_min}tr`, clear: () => setF({ ...filters, salary_min: 0 }) });
  if (filters.tag) pills.push({ label: `tag ${filters.tag}`, clear: () => setF({ ...filters, tag: "" }) });
  if (filters.company_size) pills.push({ label: `quy mô ${filters.company_size}`, clear: () => setF({ ...filters, company_size: "" }) });
  if (pills.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 flex-wrap" aria-live="polite">
      <span className="font-mono text-[11px] text-faint">đang lọc:</span>
      {pills.map((p) => (
        <button key={p.label} onClick={p.clear} title="Gỡ lọc này"
          className="px-2.5 py-1 rounded-full text-[12px] bg-peri-soft text-peri-deep border border-peri/30 font-medium hover:bg-peri/15 transition">
          {p.label} <span aria-hidden>×</span>
        </button>
      ))}
    </div>
  );
}
