import { useState } from "react";
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
  itviec: "bg-orange-500", topcv: "bg-rose-500", topdev: "bg-sky-500",
};

const SORTS = [
  { v: "auto", label: "Liên quan nhất" },
  { v: "posted", label: "Mới đăng trước" },
  { v: "salary", label: "Lương cao trước" },
  { v: "new", label: "Mới crawl trước" },
];

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
  const fresh = (jobsQ.data?.jobs ?? []).slice(0, 8);

  const clearCount = [filters.q, filters.source, filters.category, filters.exp, filters.tag,
    filters.skill, filters.level, filters.salary_min ? "1" : "",
    filters.since_hours ? "1" : ""].filter(Boolean).length;

  const today = new Date();
  const dateLine = `T${today.getDay() === 0 ? "CN" : today.getDay() + 1} · ${String(today.getDate()).padStart(2, "0")}/${String(today.getMonth() + 1).padStart(2, "0")}`;

  return (
    <div className="min-h-screen bg-paper text-ink">
      {/* Command bar */}
      <header className="bg-card border-b border-line sticky top-0 z-10">
        <div className="max-w-[1200px] mx-auto px-5 pt-4 pb-3">
          <div className="flex items-baseline justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              <span className="w-8 h-8 rounded-[10px] bg-cobalt text-white font-extrabold flex items-center justify-center text-lg">J</span>
              <h1 className="text-xl font-extrabold tracking-tight">IT Jobs HCMC</h1>
              <span className="font-mono text-xs text-ink-faint hidden md:inline">{dateLine}</span>
            </div>
            <p className="font-mono text-xs text-ink-faint">
              {total} việc · {stats.data?.new_24h ?? "–"} mới 24h · crawl 9h/11h/14h/16h/21h
            </p>
          </div>
          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <input
              value={searchInput}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Từ khóa: java backend, tester manual…"
              className="flex-1 min-w-52 bg-paper border border-line rounded-[10px] px-4 py-2.5 text-[15px] placeholder:text-ink-faint focus:outline-none focus:border-cobalt"
            />
            <div className="flex rounded-[10px] border border-line overflow-hidden" role="group" aria-label="Nguồn">
              {["", "itviec", "topcv", "topdev"].map((s) => (
                <button key={s || "all"}
                  onClick={() => setF({ ...filters, source: s })}
                  className={`px-3 py-2.5 text-sm font-medium border-r border-line last:border-0 transition ${filters.source === s ? "bg-ink text-paper" : "bg-card text-ink-soft hover:bg-paper-deep"}`}>
                  {s || "Mọi nguồn"}
                </button>
              ))}
            </div>
            <select
              value={filters.sort}
              onChange={(e) => setF({ ...filters, sort: e.target.value })}
              className="bg-card border border-line rounded-[10px] px-3 py-2.5 text-sm text-ink-soft focus:outline-none focus:border-cobalt"
              aria-label="Sắp xếp">
              {SORTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
            {clearCount > 0 && (
              <button
                onClick={() => { setSearchInput(""); setF(DEFAULT_FILTERS); }}
                className="font-mono text-xs text-ink-faint hover:text-ink whitespace-nowrap">
                xoá {clearCount} lọc
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-[1200px] mx-auto px-5 py-5">
        {/* Dải tin mới — điểm nhấn duy nhất */}
        {fresh.length > 0 && (
          <section aria-label="Tin mới nhất" className="mb-6">
            <div className="flex items-baseline justify-between mb-2">
              <h2 className="font-bold">Mới lên sóng</h2>
              <span className="font-mono text-xs text-ink-faint">kéo ngang →</span>
            </div>
            <div className="strip-scroll flex gap-3 overflow-x-auto pb-2">
              {fresh.map((j, i) => (
                <FreshCard key={`${j.source}-${j.source_id}`} job={j} index={i} />
              ))}
            </div>
          </section>
        )}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
          <section className="min-w-0">
            <div className="flex items-baseline justify-between mb-2">
              <h2 className="font-bold">
                Tất cả việc làm
                <span className="font-mono font-normal text-sm text-ink-faint ml-2">{total}</span>
              </h2>
              {pages > 1 && (
                <div className="flex items-center gap-2 font-mono text-sm">
                  <button disabled={page <= 1} onClick={() => setPage(page - 1)}
                    className="px-2 py-1 rounded-[8px] border border-line disabled:opacity-30 hover:bg-paper-deep">←</button>
                  <span className="text-ink-faint">{page}/{pages}</span>
                  <button disabled={page >= pages} onClick={() => setPage(page + 1)}
                    className="px-2 py-1 rounded-[8px] border border-line disabled:opacity-30 hover:bg-paper-deep">→</button>
                </div>
              )}
            </div>
            <JobTable jobs={jobsQ.data?.jobs} loading={jobsQ.isFetching} />
          </section>

          <aside className="min-w-0 space-y-5">
            <Sidebar filters={filters} setFilters={setF} meta={meta.data} />
            <TrendChart trend={trend.data} />
            <ExperienceChart stats={stats.data} onPick={(v) => setF({ ...filters, exp: v })} />
          </aside>
        </div>

        <div className="grid gap-5 md:grid-cols-2 mt-5">
          <CategoryChart stats={stats.data} />
          <SalaryChart jobs={jobsQ.data?.jobs ?? []} />
        </div>

        <p className="font-mono text-xs text-ink-faint mt-8">
          crawl itviec · topcv · topdev — 9h/11h/14h/16h/21h · /api/jobs · /api/stats · /api/meta · /api/trend
        </p>
      </main>
    </div>
  );
}

function FreshCard({ job: j, index }: { job: Job; index: number }) {
  return (
    <a href={j.url} target="_blank" rel="noreferrer"
       className="shrink-0 w-64 bg-card border border-line rounded-[10px] p-3 hover:border-cobalt transition flex gap-2.5">
      <span className="font-mono text-2xl font-semibold text-ink-faint/40 select-none">
        {String(index + 1).padStart(2, "0")}
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 mb-1">
          <span className={`w-2 h-2 rounded-full ${SOURCE_DOT[j.source] || "bg-ink-faint"}`} />
          <span className="font-mono text-[11px] text-ink-faint">{(j.posted_at || j.first_seen_at || "").slice(5, 10)}</span>
        </span>
        <span className="block font-semibold text-sm leading-snug line-clamp-2">{j.title}</span>
        <span className="block text-[13px] text-ink-soft truncate mt-0.5">{j.company}</span>
      </span>
    </a>
  );
}
