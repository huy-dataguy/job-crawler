import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import type { Filters } from "./api";
import { fetchJobs, fetchMeta, fetchStats, fetchTrend } from "./api";
import Sidebar from "./Sidebar";
import JobTable from "./JobTable";
import { TrendChart, ExperienceChart, CategoryChart, SalaryChart } from "./Charts";

const PAGE_SIZE = 50;

declare global {
  interface Window { __searchTimer?: number }
}

const DEFAULT_FILTERS: Filters = { q: "", source: "", category: "", exp: "", tag: "", skill: "", level: "", salary_min: 0, it_only: 1, since_hours: 0 };

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

  const meta = useQuery({ queryKey: ["meta"], queryFn: fetchMeta });
  const stats = useQuery({ queryKey: ["stats"], queryFn: fetchStats, refetchInterval: 60_000 });
  const trend = useQuery({ queryKey: ["trend"], queryFn: fetchTrend, refetchInterval: 300_000 });
  const jobsQ = useQuery({
    queryKey: ["jobs", filters, page],
    queryFn: () => fetchJobs(filters, page),
    placeholderData: keepPreviousData,
  });

  const total = jobsQ.data?.total ?? 0;
  const pages = Math.ceil(total / PAGE_SIZE);

  const clearCount = [filters.q, filters.source, filters.category, filters.exp, filters.tag,
    filters.skill, filters.level, filters.salary_min ? "1" : "",
    filters.since_hours ? "1" : ""].filter(Boolean).length;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      {/* Header */}
      <header className="bg-white border-b sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-bold">💼 IT Jobs HCMC</h1>
            <span className="text-xs text-slate-400 hidden md:inline">
              crawl 5x/ngày (9h · 11h · 14h · 16h · 21h) · crawl gần nhất: {stats.data?.generated_at?.slice(11, 16) ?? "—"}
            </span>
          </div>
          <div className="flex items-center gap-2 w-full md:w-auto">
            <input
              value={searchInput}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="🔍 Từ khóa: java backend, tester manual… (nhiều từ = phải có đủ)"
              className="w-full md:w-96 border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {clearCount > 0 && (
              <button
                onClick={() => { setSearchInput(""); setF(DEFAULT_FILTERS); }}
                className="text-xs text-slate-400 hover:text-slate-600 whitespace-nowrap">
                ⨯ Xoá {clearCount} filter
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto p-6 flex flex-col lg:flex-row gap-6">
        <Sidebar filters={filters} setFilters={setF} meta={meta.data} />

        <section className="flex-1 min-w-0 space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Kpi value={total} label="jobs khớp filter" />
            <Kpi value={stats.data?.new_24h ?? "–"} label="mới trong 24h" color="text-emerald-600" />
            <Kpi value={stats.data?.total ?? "–"} label="tổng trong DB" />
            <Kpi value={stats.data?.active ?? "–"} label="còn active" />
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            <TrendChart trend={trend.data} />
            <ExperienceChart stats={stats.data} onPick={(v) => setF({ ...filters, exp: v })} />
          </div>
          <div className="grid md:grid-cols-2 gap-6">
            <CategoryChart meta={meta.data} />
            <SalaryChart jobs={jobsQ.data?.jobs ?? []} />
          </div>

          <div className="flex items-center justify-between">
            <h2 className="font-semibold">
              Danh sách job
              <span className="text-slate-400 font-normal text-sm ml-2">{total} kết quả</span>
            </h2>
            {pages > 1 && (
              <div className="flex items-center gap-1 text-sm">
                <button disabled={page <= 1} onClick={() => setPage(page - 1)}
                  className="px-2 py-1 rounded hover:bg-slate-200 disabled:opacity-30">←</button>
                <span className="text-slate-500">trang {page}/{pages}</span>
                <button disabled={page >= pages} onClick={() => setPage(page + 1)}
                  className="px-2 py-1 rounded hover:bg-slate-200 disabled:opacity-30">→</button>
              </div>
            )}
          </div>

          <JobTable jobs={jobsQ.data?.jobs} loading={jobsQ.isFetching} />
        </section>
      </main>

      <p className="text-xs text-slate-400 text-center pb-6">
        Data sạch từ crawler itviec + topcv · API: /api/jobs · /api/stats · /api/meta · /api/trend
      </p>
    </div>
  );
}

function Kpi({ value, label, color = "text-slate-800" }: { value: React.ReactNode; label: string; color?: string }) {
  return (
    <div className="bg-white rounded-xl shadow p-4">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
