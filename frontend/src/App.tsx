import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate, useNavigationType, useSearchParams } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import type { Filters } from "./api";
import {
  DEFAULT_FILTERS, parseFilters, serializeFilters, companyInboxFilters,
  fetchJobs, fetchMeta, fetchStats, fetchTrend, fetchHealth,
} from "./api";
import FilterBar from "./FilterBar";
import JobTable from "./JobTable";
import { TrendChart, ExperienceChart, CategoryChart, SalaryChart } from "./Charts";
import Companies from "./Companies";
import ProvinceFilter from "./ProvinceFilter";
import RoleSwitcher from "./RoleSwitcher";
import SectionHead from "./SectionHead";
import Logo from "./Logo";
import { useAuth } from "./auth";

const PAGE_SIZE = 50;

declare global {
  interface Window { __searchTimer?: number }
}

const SORTS = [
  { v: "auto", label: "Khớp CV" },
  { v: "posted", label: "Mới đăng" },
  { v: "salary", label: "Lương cao" },
];

// Route: "/" Inbox · "/thong-ke" Thống kê · "/cong-ty" Công ty.
// Bộ lọc + trang sống trong URL → refresh/back-forward giữ nguyên, chia sẻ
// link được (vd /?role=de&city=Hà Nội). Chỉ ghi param khác default cho URL gọn.

export default function App() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchInput, setSearchInput] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const { state: authState, signOut } = useAuth();
  const authEmail = authState.status === "ok" ? authState.email : null;

  const { filters, page } = useMemo(() => parseFilters(searchParams), [searchParams]);
  // JD đang mở = param ?job=source:source_id → Back/Escape thu gọn, deep-link được.
  const openJob = searchParams.get("job");
  const view = location.pathname === "/thong-ke" ? "stats"
    : location.pathname === "/cong-ty" ? "companies" : "inbox";

  const setF = (f: Filters) => setSearchParams(serializeFilters(f, 1), { replace: true });
  // mở/thu gọn JD là PUSH history — Back thu gọn lại đúng chỗ đang xem
  const toggleOpenJob = (key: string) => {
    const sp = new URLSearchParams(searchParams);
    if (openJob === key) sp.delete("job"); else sp.set("job", key);
    const qs = sp.toString();
    navigate(qs ? { search: `?${qs}` } : { search: "" }, { replace: false });
  };
  // nhảy về Inbox kèm bộ lọc mới (vd từ view Công ty) — push để Back quay lại được
  const goInboxWith = (f: Filters) => {
    const qs = serializeFilters(f, 1);
    navigate(qs ? { pathname: "/", search: `?${qs}` } : "/");
  };
  const goHome = () => {
    window.clearTimeout(window.__searchTimer);
    setSearchInput("");
    navigate("/");
  };
  const listTopRef = useRef<HTMLDivElement>(null);
  const goPage = (p: number) => {
    setSearchParams(serializeFilters(filters, p), { replace: true });
    listTopRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // Scroll restoration: mỗi history entry nhớ vị trí cuộn (sessionStorage) —
  // Back/Forward quay lại đúng chỗ đang xem (danh sách công ty, hàng đợi apply);
  // đổi view (pathname mới) thì cuộn về đầu. Đổi filter/JD giữ nguyên vị trí.
  const navType = useNavigationType();
  const yRef = useRef(0);
  const lastEntryKey = useRef("");
  const prevPath = useRef("");
  useEffect(() => {
    const onScroll = () => { yRef.current = window.scrollY; };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    if (lastEntryKey.current) {
      sessionStorage.setItem("sv:" + lastEntryKey.current, String(yRef.current));
    }
    if (navType === "POP") {
      const y = Number(sessionStorage.getItem("sv:" + location.key) || 0);
      requestAnimationFrame(() => window.scrollTo(0, y));
    } else if (location.pathname !== prevPath.current) {
      window.scrollTo(0, 0);
    }
    prevPath.current = location.pathname;
    lastEntryKey.current = location.key;
  }, [location.key, navType]);
  useEffect(() => { setSearchInput((cur) => (cur === filters.q ? cur : filters.q)); }, [filters.q]);

  const onSearchChange = (value: string) => {
    setSearchInput(value);
    window.clearTimeout(window.__searchTimer);
    window.__searchTimer = window.setTimeout(() => {
      // Bắt đầu gõ tìm = tìm trên toàn bộ tin còn mở. Nếu giữ nguyên hàng đợi
      // (4 hướng · ≤2 năm · chưa xem) thì tên công ty ngoài phạm vi sẽ ra 0.
      const startingSearch = value.trim() !== "" && filters.q.trim() === "";
      const next: Filters = startingSearch
        ? { ...filters, q: value, role: "", exp: "", mark: "all", since_hours: 0,
            relevance_min: 0, company: "", company_url: "" }
        : { ...filters, q: value };
      setSearchParams(serializeFilters(next, 1), { replace: true });
    }, 350);
  };

  // "/" focus ô tìm kiếm — không cần chuột; Escape đóng JD đang mở
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
      if (e.key === "/" && !typing) { e.preventDefault(); searchRef.current?.focus(); }
      if (e.key === "Escape") {
        if (typing === true) searchRef.current?.blur();
        else if (openJob) navigate(-1);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [openJob, navigate]);

  const health = useQuery({queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 60_000});
  const meta = useQuery({ queryKey: ["meta", filters], queryFn: () => fetchMeta(filters), placeholderData: keepPreviousData });
  const stats = useQuery({ queryKey: ["stats", filters], queryFn: () => fetchStats(filters), refetchInterval: 60_000, placeholderData: keepPreviousData });
  const trend = useQuery({ queryKey: ["trend", filters], queryFn: () => fetchTrend(filters), refetchInterval: 300_000, placeholderData: keepPreviousData });
  const jobsQ = useQuery({
    queryKey: ["jobs", filters, page],
    queryFn: () => fetchJobs(filters, page),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });

  const total = jobsQ.data?.total ?? 0;
  const pages = Math.ceil(total / PAGE_SIZE);
  const searchingAll = filters.q.trim() !== "" && filters.company === "" &&
    filters.role === "" && filters.exp === "" && filters.mark === "all" &&
    filters.since_hours === 0 && filters.relevance_min === 0;

  const today = new Date();
  const dateLine = `T${today.getDay() === 0 ? "CN" : today.getDay() + 1} · ${String(today.getDate()).padStart(2, "0")}/${String(today.getMonth() + 1).padStart(2, "0")}`;

  return (
    <div className="min-h-screen paper-bg text-ink">
      {/* ===== Nav pill nổi giữa đỉnh — chữ ký teamtechvibe ===== */}
      <header className="fixed top-3 inset-x-0 z-30 px-3">
        <div className="mx-auto max-w-[1120px] rounded-2xl bg-white/90 backdrop-blur border border-line shadow-[0_2px_6px_rgba(24,28,64,0.05),0_16px_40px_-20px_rgba(24,28,64,0.25)]">
          <div className="flex items-center justify-between gap-2 px-3 py-2">
            <button onClick={goHome} className="flex items-center gap-2.5 hover:opacity-80 transition shrink-0" aria-label="Home">
              <Logo size={34} />
              <span className="font-extrabold tracking-tight text-[16px] hidden sm:block">Săn Việc</span>
              <span className="hidden lg:inline font-mono text-[11px] text-faint">{dateLine}</span>
            </button>
            <nav className="flex rounded-full bg-paper p-1" aria-label="Chế độ xem">
              {([["/", "Inbox", "end"], ["/thong-ke", "Thống kê", ""], ["/cong-ty", "Công ty", ""]] as const).map(([to, label, end]) => (
                <NavLink key={to} to={to} end={end === "end"}
                  className={({ isActive }) => `px-3.5 md:px-4 py-1.5 rounded-full text-[13px] font-semibold transition
                    ${isActive ? "bg-navy text-white shadow-sm" : "text-slate hover:text-ink"}`}>{label}</NavLink>
              ))}
            </nav>
            <div className="hidden md:flex items-center gap-1.5 font-mono text-[11px] text-faint">
              <span className="px-2 py-1 rounded-full bg-paper border border-line">+{stats.data?.new_24h ?? "–"}/24h</span>
              <span className="px-2 py-1 rounded-full bg-paper border border-line">{total} việc</span>
            </div>
            {authEmail && (
              <button onClick={signOut} title={`Đăng xuất (${authEmail})`} aria-label="Đăng xuất"
                className="w-7 h-7 shrink-0 rounded-full bg-navy text-white text-[11px] font-extrabold flex items-center justify-center hover:bg-peri transition">
                {authEmail[0].toUpperCase()}
              </button>
            )}
          </div>
        </div>
      </header>

      <div className="max-w-[1120px] mx-auto px-4 md:px-6 pt-[76px]">
        {/* Thanh ngữ cảnh toàn cục: tỉnh/thành + sức khỏe crawler — áp cả 3 view */}
        <div className="flex items-center gap-3 flex-wrap py-2.5 text-[13px]">
          <ProvinceFilter value={filters.city} onChange={city => setF({ ...filters, city })} />
          <span className="ml-auto flex gap-2 flex-wrap font-mono text-[11px]">
            {health.data?.sources.map(s => <span key={s.source} title={`${s.finished_at || "Chưa chạy"} · ${s.note || s.status}`}
              className={s.healthy ? "text-mint" : "text-coral"}>● {s.source}{s.status === "partial" ? " (một phần)" : ""}</span>)}
            {health.isError && <span className="text-coral">Không tải được trạng thái crawler</span>}
          </span>
        </div>
      </div>

      {view === "companies" ? (
        <main className="max-w-[1120px] mx-auto px-4 md:px-6 pb-10">
          <Companies city={filters.city} onFilterCompany={(c) => goInboxWith(companyInboxFilters(c, filters.city))} />
        </main>
      ) : view === "stats" ? (
        <main className="max-w-[1120px] mx-auto px-4 md:px-6 pb-10 space-y-5">
          <SectionHead eyebrow="THỊ TRƯỜNG" title={<>Toàn cảnh theo <em className="accent-italic">bộ lọc</em> hiện tại.</>} />
          <div className="grid gap-4 md:grid-cols-2">
            <TrendChart trend={trend.data} />
            <ExperienceChart stats={stats.data} onPick={(v) => goInboxWith({ ...filters, exp: v === "4" || v === "5+" ? "5" : v })} />
            <CategoryChart stats={stats.data} />
            <SalaryChart jobs={jobsQ.data?.jobs ?? []} />
          </div>
        </main>
      ) : (
        <main className="max-w-[1120px] mx-auto px-4 md:px-6 pb-10">
          {/* ===== Hero: 1 dòng, nói đúng bài toán của Huy ===== */}
          <section className="pt-7 pb-5">
            <p className="flex items-center gap-2 font-mono text-[11px] tracking-[0.18em] text-mute font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-peri inline-block" aria-hidden />
              4 HƯỚNG ỨNG TUYỂN · ≤ 2 NĂM KN · CÒN MỞ · 14 NGÀY
            </p>
            <h1 className="mt-3 text-[34px] md:text-[44px] font-extrabold tracking-tight leading-[1.05]">
              Chỉ xem việc <em className="accent-italic">đúng nghề</em>,<br className="hidden md:block" /> sẵn sàng <em className="accent-italic">apply.</em>
            </h1>
            <p className="mt-3 text-slate max-w-xl text-[15px] leading-relaxed">
              Hàng đợi tự xếp theo độ khớp CV — crawl liên tục từ ITviec, TopCV, TopDev,
              tin được kiểm tra còn mở trước khi đến tay bạn.
            </p>
          </section>

          <RoleSwitcher
            counts={meta.data?.role_counts}
            value={filters.role}
            onChange={(role) => setF({ ...filters, role })}
          />

          {/* Search + sort — luôn trong tầm mắt */}
          <div className="flex items-center gap-2 mt-6">
            <div className="relative flex-1">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-faint" aria-hidden>⌕</span>
              <input ref={searchRef} value={searchInput} onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Tìm kỹ năng, công ty, chức danh…  (phím /)"
                className="w-full bg-white border border-line rounded-full pl-10 pr-4 py-2.5 text-[14px] text-ink placeholder:text-faint shadow-sm focus:outline-none focus:border-peri focus:ring-2 focus:ring-peri/20" />
            </div>
            <select value={filters.sort} onChange={(e) => setF({ ...filters, sort: e.target.value })} aria-label="Sắp xếp"
              className="bg-white border border-line rounded-full px-3.5 py-2.5 text-sm text-slate shadow-sm focus:outline-none focus:border-peri">
              {SORTS.map((o) => <option key={o.v} value={o.v}>Xếp: {o.label}</option>)}
            </select>
          </div>

          {searchingAll && (
            <div className="mt-2.5 flex items-center gap-2 flex-wrap text-[12px] text-slate">
              <span>Đang tìm trên toàn bộ tin còn mở — không giới hạn hướng ứng tuyển, kinh nghiệm hay trạng thái đã xem.</span>
              <button
                onClick={() => goInboxWith({ ...DEFAULT_FILTERS, q: filters.q, city: filters.city, source: filters.source })}
                className="px-2.5 py-1 rounded-full border border-line bg-white text-[11px] font-semibold text-slate hover:border-line-deep">
                Chỉ tìm trong hàng đợi
              </button>
            </div>
          )}

          <FilterBar filters={filters} setF={setF} meta={meta.data} stats={stats.data} />

          <div ref={listTopRef} className="scroll-mt-24 pt-5" />
          <div className="flex items-baseline justify-between mb-2.5">
            <h2 className="font-bold text-[17px]">
              {filters.q.trim() ? "Kết quả tìm kiếm" : "Hàng đợi apply"}
              <span className="font-mono font-medium text-sm text-faint ml-2">{total}</span>
            </h2>
            {pages > 1 && (
              <div className="flex items-center gap-2 font-mono text-sm">
                <button disabled={page <= 1} onClick={() => goPage(page - 1)}
                  className="px-2.5 py-1 rounded-full border border-line bg-white disabled:opacity-30 hover:border-line-deep">←</button>
                <span className="text-faint text-[13px]">{page}/{pages}</span>
                <button disabled={page >= pages} onClick={() => goPage(page + 1)}
                  className="px-2.5 py-1 rounded-full border border-line bg-white disabled:opacity-30 hover:border-line-deep">→</button>
              </div>
            )}
          </div>
          {jobsQ.isError && <p role="alert" className="text-coral py-4">Không tải được việc làm. Hãy kiểm tra kết nối dashboard.</p>}
          <JobTable jobs={jobsQ.data?.jobs} loading={jobsQ.isPending} onChanged={() => { jobsQ.refetch(); stats.refetch(); }}
            listKey={JSON.stringify(filters) + page} openKey={openJob} onToggleOpen={toggleOpenJob} />

          <p className="font-mono text-[11px] text-faint mt-8 flex flex-wrap gap-x-3 gap-y-1 items-center">
            <span>phím tắt:</span>
            <span><Kbd>j</Kbd>/<Kbd>k</Kbd> di chuyển</span>
            <span><Kbd>Enter</Kbd> mở job</span>
            <span><Kbd>a</Kbd> mở + apply</span>
            <span><Kbd>s</Kbd> sao việc này</span>
            <span><Kbd>v</Kbd> đã xem</span>
            <span><Kbd>x</Kbd> ẩn</span>
            <span><Kbd>/</Kbd> tìm kiếm</span>
            <span className="ml-auto hidden md:inline">crawl 15 phút/lượt · itviec · topcv · topdev</span>
          </p>
        </main>
      )}
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="px-1.5 py-0.5 rounded-md border border-line bg-white font-mono text-[10px] text-slate shadow-sm">{children}</kbd>;
}
