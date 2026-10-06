import { useEffect, useRef, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import type { Filters } from "./api";
import { fetchJobs, fetchMeta, fetchStats, fetchTrend } from "./api";
import FilterBar from "./FilterBar";
import JobTable from "./JobTable";
import { TrendChart, ExperienceChart, CategoryChart, SalaryChart } from "./Charts";
import Companies from "./Companies";

const PAGE_SIZE = 50;

declare global {
  interface Window { __searchTimer?: number }
}

// Inbox mặc định: chưa xem + khớp profile (≥40) + xếp liên quan nhất.
// → mở dashboard lên là có ngay hàng đợi việc nên xem/apply, không phải mò lọc.
const DEFAULT_FILTERS: Filters = {
  q: "", source: "", category: "", exp: "", tag: "", skill: "", level: "",
  salary_min: 0, it_only: 1, since_hours: 0, sort: "auto", show_hidden: 0,
  company_size: "", relevance_min: 40, mark: "unseen",
};

const SORTS = [
  { v: "auto", label: "Xếp: khớp profile" },
  { v: "posted", label: "Xếp: mới đăng trước" },
  { v: "salary", label: "Xếp: lương cao trước" },
];

export default function App() {
  const [view, setView] = useState<"inbox" | "stats" | "companies">("inbox");
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const setF = (f: Filters) => { setFilters(f); setPage(1); };
  const goHome = () => {
    setSearchInput("");
    setFilters(DEFAULT_FILTERS);
    setPage(1);
    setView("inbox");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const onSearchChange = (value: string) => {
    setSearchInput(value);
    window.clearTimeout(window.__searchTimer);
    window.__searchTimer = window.setTimeout(() => setF({ ...filters, q: value }), 350);
  };

  // "/" focus ô tìm kiếm — không cần chuột
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
      if (e.key === "/" && !typing) { e.preventDefault(); searchRef.current?.focus(); }
      if (e.key === "Escape" && typing === true) searchRef.current?.blur();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

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

  const q = stats.data?.queue;
  const today = new Date();
  const dateLine = `T${today.getDay() === 0 ? "CN" : today.getDay() + 1} · ${String(today.getDate()).padStart(2, "0")}/${String(today.getMonth() + 1).padStart(2, "0")}`;

  return (
    <div className="min-h-screen bg-night text-mist">
      <header className="bg-panel/95 backdrop-blur border-b border-edge sticky top-0 z-20 hero-glow">
        <div className="max-w-[1280px] mx-auto px-4 md:px-6">
          <div className="flex items-center justify-between gap-3 py-3">
            <button onClick={goHome} className="flex items-center gap-3 hover:opacity-85 transition" aria-label="Home">
              <span className="w-8 h-8 rounded-[10px] bg-gradient-to-br from-ember to-violet text-white font-extrabold flex items-center justify-center text-lg shadow-[0_0_18px_rgba(255,90,60,0.35)]">J</span>
              <span className="text-[18px] font-extrabold tracking-tight">Săn Việc</span>
              <span className="hidden md:inline font-mono text-xs text-faint ml-1">{dateLine}</span>
            </button>
            <div className="flex items-center gap-2">
              <div className="hidden sm:flex rounded-full bg-night border border-edge p-1">
                {([["inbox", "Inbox"], ["stats", "Thống kê"], ["companies", "Công ty"]] as const).map(([v, label]) => (
                  <button key={v} onClick={() => setView(v)}
                    className={`px-4 py-1.5 rounded-full text-sm font-semibold transition ${view === v ? "bg-white text-night shadow" : "text-dim hover:text-mist"}`}>{label}</button>
                ))}
              </div>
              <div className="hidden lg:flex items-center gap-1.5 font-mono text-xs">
                <span className="px-2 py-1 rounded bg-night border border-edge text-dim">{stats.data?.new_24h ?? "–"} mới 24h</span>
                {q && <span className="px-2 py-1 rounded bg-night border border-edge text-dim">{q.applied} đã apply</span>}
                <span className="px-2 py-1 rounded bg-night border border-edge text-dim">{total} trong tầm lọc</span>
              </div>
            </div>
          </div>
          {/* Mobile view switch */}
          <div className="sm:hidden flex rounded-full bg-night border border-edge p-1 mb-3">
            {([["inbox", "Inbox"], ["stats", "Thống kê"], ["companies", "Công ty"]] as const).map(([v, label]) => (
              <button key={v} onClick={() => setView(v)}
                className={`flex-1 py-1.5 rounded-full text-sm font-semibold ${view === v ? "bg-white text-night" : "text-dim"}`}>{label}</button>
            ))}
          </div>
        </div>
      </header>

      {view === "companies" ? (
        <main className="max-w-[1280px] mx-auto px-4 md:px-6 py-5">
          <Companies onFilterCompany={(c) => { setFilters({ ...DEFAULT_FILTERS, company_size: c.bucket || "" }); setView("inbox"); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
        </main>
      ) : view === "stats" ? (
        <main className="max-w-[1280px] mx-auto px-4 md:px-6 py-5 space-y-5">
          <h2 className="font-bold text-lg">Thống kê thị trường <span className="font-mono text-sm text-faint">— theo bộ lọc hiện tại</span></h2>
          <div className="grid gap-5 md:grid-cols-2">
            <TrendChart trend={trend.data} />
            <ExperienceChart stats={stats.data} onPick={(v) => { setView("inbox"); setF({ ...filters, exp: v }); }} />
            <CategoryChart stats={stats.data} />
            <SalaryChart jobs={jobsQ.data?.jobs ?? []} />
          </div>
        </main>
      ) : (
        <main className="max-w-[1280px] mx-auto px-4 md:px-6 py-5">
          {/* Search + sort — luôn trong tầm mắt */}
          <div className="flex items-center gap-2 mb-4">
            <div className="relative flex-1">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-faint">⌕</span>
              <input ref={searchRef} value={searchInput} onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Tìm kỹ năng, công ty, chức danh…   (phím /)"
                className="w-full bg-panel border border-edge rounded-full pl-9 pr-4 py-2.5 text-[14px] placeholder:text-faint focus:outline-none focus:border-ember focus:ring-1 focus:ring-ember/30" />
            </div>
            <select value={filters.sort} onChange={(e) => setF({ ...filters, sort: e.target.value })}
              className="bg-panel border border-edge rounded-full px-3 py-2.5 text-sm text-dim focus:outline-none focus:border-ember">
              {SORTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
          </div>

          <FilterBar filters={filters} setF={setF} meta={meta.data} stats={stats.data} />

          <div ref={listTopRef} className="scroll-mt-24 pt-4" />
          <div className="flex items-baseline justify-between mb-2">
            <h2 className="font-bold">
              Hàng đợi việc làm
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
          <JobTable jobs={jobsQ.data?.jobs} loading={jobsQ.isPending} onChanged={() => { jobsQ.refetch(); stats.refetch(); }}
            listKey={JSON.stringify(filters) + page} />

          <p className="font-mono text-xs text-faint mt-6 flex flex-wrap gap-x-3 gap-y-1 items-center">
            <span>phím tắt:</span>
            <span><Kbd>j</Kbd>/<Kbd>k</Kbd> hoặc <Kbd>↑</Kbd>/<Kbd>↓</Kbd> di chuyển</span>
            <span><Kbd>Enter</Kbd> mở job</span>
            <span><Kbd>a</Kbd> mở + đánh dấu đã apply</span>
            <span><Kbd>v</Kbd> đã xem</span>
            <span><Kbd>x</Kbd> ẩn (không OK)</span>
            <span><Kbd>/</Kbd> tìm kiếm</span>
            <span className="ml-auto hidden md:inline">crawl 15 phút/lượt · itviec · topcv · topdev</span>
          </p>
        </main>
      )}
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="px-1.5 py-0.5 rounded border border-edge bg-night font-mono text-[10px] text-dim">{children}</kbd>;
}
