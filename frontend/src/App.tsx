import { useEffect, useRef, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import type { Filters, Job } from "./api";
import { fetchJobs, fetchMeta, fetchStats, fetchTrend } from "./api";
import Sidebar from "./Sidebar";
import JobTable from "./JobTable";
import { TrendChart, ExperienceChart, CategoryChart, SalaryChart } from "./Charts";

const PAGE_SIZE = 50;

declare global {
  interface Window { __searchTimer?: number }
}

const DEFAULT_FILTERS: Filters = {
  q: "", source: "", category: "", exp: "", tag: "", skill: "", level: "",
  salary_min: 0, it_only: 1, since_hours: 0, sort: "auto",
};

const SOURCE_DOT: Record<string, string> = {
  itviec: "bg-[#ff9e4a]", topcv: "bg-[#ff6b8a]", topdev: "bg-[#4cc3ff]",
};

// Sort thời gian chỉ còn 1 nghĩa duy nhất: theo NGÀY ĐĂNG (posted_at).
// Lọc cửa sổ thời gian nằm ở "Ngày đăng trong" (sidebar). Hai cái bổ sung
// nhau chứ không đá nhau: cửa sổ chọn tập, sort xếp thứ tự trong tập.
const SORTS = [
  { v: "auto", label: "Xếp: liên quan" },
  { v: "posted", label: "Xếp: mới đăng trước" },
  { v: "salary", label: "Xếp: lương cao trước" },
];

const SINCE_LABEL: Record<number, string> = {
  0: "", 24: "trong 24 giờ qua", 72: "trong 3 ngày qua", 168: "trong 7 ngày qua",
};

export default function App() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");

  const setF = (f: Filters) => { setFilters(f); setPage(1); };

  const onSearchChange = (value: string) => {
    setSearchInput(value);
    window.clearTimeout(window.__searchTimer);
    window.__searchTimer = window.setTimeout(() => setF({ ...filters, q: value }), 350);
  };

  const meta = useQuery({ queryKey: ["meta", filters], queryFn: () => fetchMeta(filters), placeholderData: keepPreviousData });
  const stats = useQuery({ queryKey: ["stats", filters], queryFn: () => fetchStats(filters), refetchInterval: 60_000, placeholderData: keepPreviousData });
  const trend = useQuery({ queryKey: ["trend", filters], queryFn: () => fetchTrend(filters), refetchInterval: 300_000, placeholderData: keepPreviousData });
  const jobsQ = useQuery({
    queryKey: ["jobs", filters, page],
    queryFn: () => fetchJobs(filters, page),
    placeholderData: keepPreviousData,
  });

  const total = jobsQ.data?.total ?? 0;
  const pages = Math.ceil(total / PAGE_SIZE);
  const listTopRef = useRef<HTMLDivElement>(null);
  const goPage = (p: number) => {
    setPage(p);
    listTopRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  // Dải "mới đăng nhất" LUÔN xếp theo ngày đăng, không ăn theo sort của danh sách.
  // Các filter khác (từ khóa/nguồn/kỹ năng/…) vẫn áp dụng chung.
  const freshFilters = { ...filters, sort: "posted" };
  const freshQ = useQuery({
    queryKey: ["fresh", freshFilters],
    queryFn: () => fetchJobs(freshFilters, 1),
    placeholderData: keepPreviousData,
  });
  const fresh = (freshQ.data?.jobs ?? []).slice(0, 8);

  const clearCount = [filters.q, filters.source, filters.category, filters.exp, filters.tag,
    filters.skill, filters.level, filters.salary_min ? "1" : "",
    filters.since_hours ? "1" : ""].filter(Boolean).length;

  const today = new Date();
  const dateLine = `T${today.getDay() === 0 ? "CN" : today.getDay() + 1} · ${String(today.getDate()).padStart(2, "0")}/${String(today.getMonth() + 1).padStart(2, "0")}`;

  return (
    <div className="min-h-screen bg-night text-mist">
      {/* Command bar */}
      <header className="bg-panel/95 backdrop-blur border-b border-edge sticky top-0 z-10 hero-glow">
        <div className="max-w-[1760px] mx-auto px-4 md:px-6 pt-4 pb-3">
          <div className="flex items-baseline justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <span className="w-8 h-8 rounded-[10px] bg-gradient-to-br from-ember to-violet text-white font-extrabold flex items-center justify-center text-lg shadow-[0_0_18px_rgba(255,90,60,0.45)]">J</span>
              <h1 className="text-xl font-extrabold tracking-tight">IT Jobs HCMC</h1>
              <span className="font-mono text-xs text-faint hidden md:inline">{dateLine}</span>
            </div>
            <p className="font-mono text-xs text-faint">
              {total} việc · {stats.data?.new_24h ?? "–"} mới 24h · crawl 9h/11h/14h/16h/21h
            </p>
          </div>
          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <input
              value={searchInput}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Từ khóa: java backend, tester manual…"
              className="flex-1 min-w-52 bg-night border border-edge rounded-[10px] px-4 py-2.5 text-[15px] placeholder:text-faint focus:outline-none focus:border-ember"
            />
            <div className="flex rounded-[10px] border border-edge overflow-hidden" role="group" aria-label="Nguồn">
              {["", "itviec", "topcv", "topdev"].map((s) => (
                <button key={s || "all"}
                  onClick={() => setF({ ...filters, source: s })}
                  className={`px-3 py-2.5 text-sm font-medium border-r border-edge last:border-0 transition ${filters.source === s ? "bg-gradient-to-r from-ember to-[#ff8a3c] text-white font-semibold" : "bg-panel text-dim hover:text-mist"}`}>
                  {s || "Mọi nguồn"}
                </button>
              ))}
            </div>
            <select
              value={filters.sort}
              onChange={(e) => setF({ ...filters, sort: e.target.value })}
              className="bg-panel border border-edge rounded-[10px] px-3 py-2.5 text-sm text-dim focus:outline-none focus:border-ember"
              aria-label="Sắp xếp">
              {SORTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
            {clearCount > 0 && (
              <button
                onClick={() => { setSearchInput(""); setF(DEFAULT_FILTERS); }}
                className="font-mono text-xs text-faint hover:text-mist whitespace-nowrap">
                xoá {clearCount} lọc
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-[1760px] mx-auto px-4 md:px-6 py-5">
        {/* Dải tin mới đăng nhất — luôn xếp theo ngày đăng, tôn trọng mọi filter khác */}
        {fresh.length > 0 && (
          <section aria-label="Tin mới nhất" className="mb-6">
            <div className="flex items-baseline justify-between mb-2">
              <h2 className="font-bold">
                Mới đăng nhất
                {SINCE_LABEL[filters.since_hours] && (
                  <span className="font-normal text-sm text-dim ml-2">{SINCE_LABEL[filters.since_hours]}</span>
                )}
              </h2>
              <span className="font-mono text-xs text-faint">kéo ngang →</span>
            </div>
            <div className="strip-scroll flex gap-3 overflow-x-auto pb-2">
              {fresh.map((j, i) => (
                <FreshCard key={`${j.source}-${j.source_id}`} job={j} index={i} />
              ))}
            </div>
          </section>
        )}

        <ActivePills filters={filters} setF={setF} />

        <div className="grid gap-5 md:grid-cols-[280px_minmax(0,1fr)] 2xl:grid-cols-[280px_minmax(0,1fr)_360px]">
          {/* Rail trái: bộ lọc */}
          <aside className="min-w-0 order-2 md:order-1 space-y-5">
            <Sidebar filters={filters} setFilters={setF} meta={meta.data} />
          </aside>

          <section className="min-w-0 order-1 md:order-2">
            <div ref={listTopRef} className="scroll-mt-36" />
            <div className="flex items-baseline justify-between mb-2">
              <h2 className="font-bold">
                Tất cả việc làm
                <span className="font-mono font-normal text-sm text-faint ml-2">{total}</span>
              </h2>
              {pages > 1 && (
                <div className="flex items-center gap-2 font-mono text-sm">
                  <button disabled={page <= 1} onClick={() => goPage(page - 1)}
                    className="px-2 py-1 rounded-[8px] border border-edge disabled:opacity-30 hover:bg-white/5">←</button>
                  <span className="text-faint">{page}/{pages}</span>
                  <button disabled={page >= pages} onClick={() => goPage(page + 1)}
                    className="px-2 py-1 rounded-[8px] border border-edge disabled:opacity-30 hover:bg-white/5">→</button>
                </div>
              )}
            </div>
            <JobTable jobs={jobsQ.data?.jobs} loading={jobsQ.isPending} />
          </section>

          {/* Rail phải: biểu đồ — chỉ hiện trên màn rất rộng */}
          <aside className="min-w-0 order-3 hidden 2xl:block space-y-5">
            <TrendChart trend={trend.data} />
            <ExperienceChart stats={stats.data} onPick={(v) => setF({ ...filters, exp: v })} />
            <CategoryChart stats={stats.data} />
            <SalaryChart jobs={jobsQ.data?.jobs ?? []} />
          </aside>
        </div>

        {/* Màn vừa: biểu đồ xuống dưới danh sách */}
        <div className="grid gap-5 md:grid-cols-2 mt-5 2xl:hidden">
          <TrendChart trend={trend.data} />
          <ExperienceChart stats={stats.data} onPick={(v) => setF({ ...filters, exp: v })} />
          <CategoryChart stats={stats.data} />
          <SalaryChart jobs={jobsQ.data?.jobs ?? []} />
        </div>

        <p className="font-mono text-xs text-faint mt-8">
          crawl itviec · topcv · topdev — 9h/11h/14h/16h/21h · /api/jobs · /api/stats · /api/meta · /api/trend
        </p>
      </main>
    </div>
  );
}

// Dải trạng thái lọc: cho biết chính xác đang lọc gì, bấm × để gỡ từng cái.
// Khắc phục việc sort "mới đăng" và lọc "7 ngày" đá nhau mà không nhìn thấy.
function ActivePills({ filters, setF }: { filters: Filters; setF: (f: Filters) => void }) {
  const pills: { label: string; clear: () => void }[] = [];
  if (filters.q) pills.push({ label: `từ khóa “${filters.q}”`, clear: () => setF({ ...filters, q: "" }) });
  if (filters.source) pills.push({ label: `nguồn ${filters.source}`, clear: () => setF({ ...filters, source: "" }) });
  if (filters.skill) pills.push({ label: `kỹ năng ${filters.skill}`, clear: () => setF({ ...filters, skill: "" }) });
  if (filters.category) pills.push({ label: `ngành ${filters.category}`, clear: () => setF({ ...filters, category: "" }) });
  if (filters.exp) pills.push({ label: `${filters.exp} năm kinh nghiệm`, clear: () => setF({ ...filters, exp: "" }) });
  if (filters.level) pills.push({ label: `cấp ${filters.level}`, clear: () => setF({ ...filters, level: "" }) });
  if (filters.salary_min) pills.push({ label: `lương ≥ ${filters.salary_min}tr`, clear: () => setF({ ...filters, salary_min: 0 }) });
  if (filters.since_hours) pills.push({
    label: `đăng ${SINCE_LABEL[filters.since_hours] || "gần đây"}`,
    clear: () => setF({ ...filters, since_hours: 0 }),
  });
  if (filters.tag) pills.push({ label: `tag ${filters.tag}`, clear: () => setF({ ...filters, tag: "" }) });
  if (filters.it_only !== 1) pills.push({ label: "cả tin ngoài IT", clear: () => setF({ ...filters, it_only: 1 }) });
  if (pills.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 flex-wrap mb-4" aria-live="polite">
      <span className="font-mono text-xs text-faint">đang lọc:</span>
      {pills.map((p) => (
        <button key={p.label} onClick={p.clear} title="Bấm để gỡ lọc này"
          className="px-2.5 py-1 rounded-full text-[13px] bg-gradient-to-r from-ember to-[#ff8a3c] text-white font-semibold hover:brightness-110 transition">
          {p.label} <span aria-hidden>×</span>
        </button>
      ))}
      <span className="font-mono text-xs text-faint">xếp: {SORTS.find((s) => s.v === filters.sort)?.label.replace("Xếp: ", "")}</span>
    </div>
  );
}

function FreshCard({ job: j, index }: { job: Job; index: number }) {
  return (
    <a href={j.url} target="_blank" rel="noreferrer"
       className="shrink-0 w-64 bg-panel border border-edge rounded-[10px] p-3 hover:border-ember transition flex gap-2.5">
      <span className="font-mono text-2xl font-semibold select-none text-transparent bg-clip-text bg-gradient-to-b from-violet to-ember">
        {String(index + 1).padStart(2, "0")}
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 mb-1">
          <span className={`w-2 h-2 rounded-full ${SOURCE_DOT[j.source] || "bg-faint"}`} />
          <span className="font-mono text-[11px] text-faint">{(j.posted_at || j.first_seen_at || "").slice(5, 10)}</span>
        </span>
        <span className="block font-semibold text-sm leading-snug line-clamp-2">{j.title}</span>
        <span className="block text-[13px] text-dim truncate mt-0.5">{j.company}</span>
      </span>
    </a>
  );
}
