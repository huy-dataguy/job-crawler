import { useEffect, useRef, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import type { Filters, Job } from "./api";
import { fetchJobs, fetchMeta, fetchStats, fetchTrend } from "./api";
import Sidebar from "./Sidebar";
import JobTable from "./JobTable";
import { TrendChart, ExperienceChart, CategoryChart, SalaryChart } from "./Charts";
import Companies from "./Companies";

const PAGE_SIZE = 50;

declare global {
  interface Window { __searchTimer?: number }
}

const DEFAULT_FILTERS: Filters = {
  q: "", source: "", category: "", exp: "", tag: "", skill: "", level: "",
  salary_min: 0, it_only: 1, since_hours: 0, sort: "auto", show_hidden: 0, company_size: "",
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
  const [view, setView] = useState<"jobs" | "companies">("jobs");
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");

  const setF = (f: Filters) => { setFilters(f); setPage(1); };

  // Nút Home (logo + tên): reset toàn bộ search + filter + trang, cuộn lên đầu
  const goHome = () => {
    setSearchInput("");
    setFilters(DEFAULT_FILTERS);
    setPage(1);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

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
    filters.skill, filters.level, filters.salary_min ? "1" : "", filters.company_size ? "1" : "",
    filters.since_hours ? "1" : ""].filter(Boolean).length;

  const today = new Date();
  const dateLine = `T${today.getDay() === 0 ? "CN" : today.getDay() + 1} · ${String(today.getDate()).padStart(2, "0")}/${String(today.getMonth() + 1).padStart(2, "0")}`;

  return (
    <div className="min-h-screen bg-night text-mist">
      {/* Command bar — 2-tier, gọn & đồng nhất */}
      <header className="bg-panel/95 backdrop-blur border-b border-edge sticky top-0 z-20 hero-glow">
        <div className="max-w-[1760px] mx-auto px-4 md:px-6">
          {/* Row 1: brand + view switch + stats */}
          <div className="flex items-center justify-between gap-3 py-3 border-b border-edge/60">
            <button onClick={goHome} className="flex items-center gap-3 hover:opacity-85 transition" aria-label="Home">
              <span className="w-8 h-8 rounded-[10px] bg-gradient-to-br from-ember to-violet text-white font-extrabold flex items-center justify-center text-lg shadow-[0_0_18px_rgba(255,90,60,0.35)]">J</span>
              <span className="text-[18px] font-extrabold tracking-tight">IT Jobs HCMC</span>
              <span className="hidden md:inline font-mono text-xs text-faint ml-1">{dateLine}</span>
            </button>
            <div className="flex items-center gap-2">
              <div className="hidden sm:flex rounded-full bg-night border border-edge p-1">
                <button onClick={() => setView("jobs")} className={`px-4 py-1.5 rounded-full text-sm font-semibold transition ${view==="jobs" ? "bg-white text-night shadow" : "text-dim hover:text-mist"}`}>Jobs</button>
                <button onClick={() => setView("companies")} className={`px-4 py-1.5 rounded-full text-sm font-semibold transition ${view==="companies" ? "bg-white text-night shadow" : "text-dim hover:text-mist"}`}>Companies</button>
              </div>
              <span className="hidden lg:inline font-mono text-xs text-faint ml-2">{total} việc · {stats.data?.new_24h ?? "–"} mới 24h</span>
              <span className="sm:hidden font-mono text-xs text-faint">{total} · {stats.data?.new_24h ?? "–"} mới</span>
            </div>
          </div>
          {/* Row 2: search + sort + clear */}
          <div className="flex items-center gap-2 py-3">
            <div className="relative flex-1">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-faint">⌕</span>
              <input
                value={searchInput}
                onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Tìm java, react, senior, remote…"
                className="w-full bg-night border border-edge rounded-full pl-9 pr-4 py-2.5 text-[14px] placeholder:text-faint focus:outline-none focus:border-ember focus:ring-1 focus:ring-ember/30"
              />
            </div>
            <select value={filters.sort} onChange={(e) => setF({ ...filters, sort: e.target.value })}
              className="hidden sm:block bg-night border border-edge rounded-full px-3 py-2.5 text-sm text-dim focus:outline-none focus:border-ember">
              {SORTS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
            </select>
            {clearCount > 0 && (
              <button onClick={() => { setSearchInput(""); setF(DEFAULT_FILTERS); }}
                className="shrink-0 font-mono text-xs px-3 py-1.5 rounded-full border border-edge text-faint hover:text-mist hover:border-faint">xoá {clearCount} lọc</button>
            )}
          </div>
          {/* Row 3: segmented filters — chỉ hiện ở Jobs view */}
          {view === "jobs" && (
            <div className="flex items-center gap-2 pb-3 flex-wrap">
              <div className="flex rounded-full bg-night border border-edge p-1">
                {["", "itviec", "topcv", "topdev"].map((s) => (
                  <button key={s || "all"} onClick={() => setF({ ...filters, source: s })}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition ${filters.source === s ? "bg-ember text-white" : "text-dim hover:text-mist"}`}>{s || "Tất cả nguồn"}</button>
                ))}
              </div>
              <div className="h-5 w-px bg-edge hidden sm:block" />
              <div className="flex rounded-full bg-night border border-edge p-1">
                {["", "<50", "50-100", "101-150", "151-300", "301-1000", "1000+"].map((v) => (
                  <button key={v || "all-size"} onClick={() => setF({ ...filters, company_size: v })}
                    className={`px-2.5 py-1 rounded-full text-xs transition ${filters.company_size === v ? "bg-violet text-white" : "text-dim hover:text-mist"}`}>{v || "Mọi quy mô"}</button>
                ))}
              </div>
              <label className="ml-auto flex items-center gap-1.5 font-mono text-xs text-dim cursor-pointer select-none">
                <input type="checkbox" checked={!!filters.show_hidden} onChange={(e) => setF({ ...filters, show_hidden: e.target.checked ? 1 : 0 })} className="accent-ember w-3.5 h-3.5" /> Hiện Không OK
              </label>
            </div>
          )}
          {/* Mobile view switch */}
          <div className="sm:hidden flex rounded-full bg-night border border-edge p-1 mb-3">
            <button onClick={() => setView("jobs")} className={`flex-1 py-1.5 rounded-full text-sm font-semibold ${view==="jobs" ? "bg-white text-night" : "text-dim"}`}>Jobs</button>
            <button onClick={() => setView("companies")} className={`flex-1 py-1.5 rounded-full text-sm font-semibold ${view==="companies" ? "bg-white text-night" : "text-dim"}`}>Companies</button>
          </div>
        </div>
      </header>

      {view === "companies" ? (
        <main className="max-w-[1760px] mx-auto px-4 md:px-6 py-5">
          <Companies onFilterCompany={(c) => { setFilters({...filters, company_size: c.bucket || ""}); setView("jobs"); window.scrollTo({top:0, behavior:"smooth"}); }} />
        </main>
      ) : (
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
            <JobTable jobs={jobsQ.data?.jobs} loading={jobsQ.isPending} onChanged={() => jobsQ.refetch()} />
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
          crawl itviec · topcv · topdev — 9h/11h/14h/16h/21h · /api/jobs · /api/stats · /api/meta · /api/trend · /api/companies
        </p>
      </main>
      )}
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
  if (filters.show_hidden) pills.push({ label: "đang hiện việc Không OK", clear: () => setF({ ...filters, show_hidden: 0 }) });
  if (filters.company_size) pills.push({ label: `quy mô ${filters.company_size}`, clear: () => setF({ ...filters, company_size: "" }) });
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
       className="shrink-0 w-64 bg-panel border border-edge rounded-[14px] p-3 shadow-sm hover:border-ember transition flex gap-2.5">
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
