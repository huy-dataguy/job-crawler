import { Fragment, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import SectionHead from "./SectionHead";
import type { HiringRole } from "./api";
import { apiFetch, apiGet, downloadCompaniesCsv, markJob } from "./api";
import { BUCKETS, BUCKET_COLOR } from "./company";

type Company = {
  website: string | null;
  address: string | null;
  company_type: string | null;
  country: string | null;
  working_days: string | null;
  overtime: string | null;
  tech_stack: string[];
  public_links: {label: string; url: string}[];
  it_status: string;
  it_evidence: string | null;
  completeness: number;
  enrichment_error: string | null;
  source: string;
  company: string;
  company_slug: string | null;
  detail_url: string | null;
  size_raw: string | null;
  size_min: number | null;
  size_max: number | null;
  num_employees: string | null;
  bucket: string | null;
  industry: string | null;
  description: string | null;
  fetched_at: string | null;
  is_hiring: number;
  job_count: number;
  hiring_roles: HiringRole[];
  hiring_role_tags: string[];
};

type JobLite = {
  source: string; source_id: string; title: string; url: string;
  salary: string; level: string; relevance: number | null; posted_at: string | null;
  viewed: number; applied: number; starred: number; hidden: number;
};

type CompanyStats = {
  total: number;
  enriched: number;
  it_profiles: number;
  websites: number;
  addresses: number;
  hiring: number;
  missing_counts: Record<MissingField, number>;
  buckets: { bucket: string; n: number }[];
  by_source: { source: string; n: number }[];
};

const MISSING_FIELDS = [
  {value: "size", label: "Missing size"},
  {value: "industry", label: "Missing industry"},
  {value: "website", label: "Missing website"},
  {value: "address", label: "Missing address"},
  {value: "description", label: "Missing description"},
] as const;
type MissingField = typeof MISSING_FIELDS[number]["value"];

const SOURCE_DOT: Record<string,string> = { itviec:"bg-[#f97316]", topcv:"bg-[#ec4899]", topdev:"bg-[#0ea5e9]" };
const GRID = "#e1e4f3";
const TICK = { fontSize: 11, fill: "#9aa0bf" };
const TOOLTIP = {
  background: "#ffffff", border: "1px solid #e1e4f3", borderRadius: 12,
  color: "#181c40", fontSize: 12, boxShadow: "0 12px 32px -18px rgba(24,28,64,0.35)",
};

async function get<T>(url: string): Promise<T> {
  return apiGet<T>(url);
}

// "Hunt via company": choose size → choose company → xem ngay họ hiring vị trí
// gì → nhảy thẳng vào Inbox lọc sẵn. Mặc định chỉ hiện công ty hiring.
export default function Companies({ city, onFilterCompany }: { city: string; onFilterCompany?: (c: Company) => void }) {
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [bucket, setBucket] = useState("");
  const [hiring, setHiring] = useState(1);
  const [itOnly, setItOnly] = useState(1);
  const [missingFields, setMissingFields] = useState<MissingField[]>([]);
  const [missingMode, setMissingMode] = useState<"all" | "any">("all");
  const [toolsOpen, setToolsOpen] = useState(false);
  const [page, setPage] = useState(1);
  // Card đang mở sống trong URL (?co=source:slug) — Back from Inbox keeps
  // detail card, share direct link to 1 công ty được.
  const [searchParams, setSearchParams] = useSearchParams();
  const openCo = searchParams.get("co");
  const coKey = (c: Company) => `${c.source}:${c.company_slug || c.company}`;
  const toggleCo = (key: string) => {
    const sp = new URLSearchParams(searchParams);
    if (openCo === key) sp.delete("co"); else sp.set("co", key);
    const qs = sp.toString();
    setSearchParams(qs, { replace: false });
  };
  const clearCo = () => { if (openCo) setSearchParams(new URLSearchParams(), { replace: true }); };

  // Chỉ reset khi city THẬT SỰ đổi — không chạy lúc remount (Back về phải giữ
  // card currently open + param ?co= trong URL).
  const prevCity = useRef(city);
  useEffect(() => {
    if (prevCity.current !== city) {
      prevCity.current = city;
      setPage(1);
      clearCo();
    }
  }, [city]);
  const filterParams = new URLSearchParams({q, source, bucket, hiring: String(hiring), it_only: String(itOnly), city,
    missing_fields: missingFields.join(","), missing_mode: missingMode});
  const filterKey = filterParams.toString();
  const toggleMissing = (field: MissingField) => {
    setMissingFields(current => current.includes(field) ? current.filter(f => f !== field) : [...current, field]);
    setPage(1);
    clearCo();
  };
  const stats = useQuery({
    queryKey: ["company-stats", filterKey],
    queryFn: () => get<CompanyStats>(`/api/company-stats?${filterParams}`),
  });
  const companies = useQuery({
    queryKey: ["companies", filterKey, page],
    queryFn: () => {
      const p = new URLSearchParams(filterKey);
      p.set("limit", "24");
      p.set("offset", String((page - 1) * 24));
      return get<{ total: number; companies: Company[] }>(`/api/companies?${p.toString()}`);
    },
  });

  const total = companies.data?.total ?? 0;
  const pages = Math.ceil(total / 24);
  const coverage = stats.data ? Math.round((stats.data.enriched / Math.max(1, stats.data.total)) * 100) : 0;

  return (
    <div className="space-y-4">
      <SectionHead eyebrow="HUNT VIA COMPANY" title={<>Chọn công ty, xem ngay họ <em className="accent-italic">what they are hiring</em>.</>} />
      <p className="text-slate text-[15px] max-w-2xl -mt-1">
        Cách săn thứ hai: choose a suitable headcount, inspect open roles,
        then jump to Inbox filtered by that company.
      </p>

      {/* KPI */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Company profiles by source" value={stats.data?.total ?? "–"} sub={`${stats.data?.by_source.map(s=>`${s.source} ${s.n}`).join(" · ") || ""}`} />
        <Kpi label="Has size" value={stats.data?.enriched ?? "–"} sub={`${coverage}% coverage`} />
        <Kpi label="Hiring" value={stats.data?.hiring ?? "–"} sub="has verified open jobs" accent />
        <Kpi label="Has IT signal / công nghệ" value={stats.data?.it_profiles ?? "–"} sub={`${stats.data?.websites ?? 0} website · ${stats.data?.addresses ?? 0} address`} />
      </div>

      {/* Headcount — main filter for company hunt */}
      <div className="soft-card rounded-2xl p-4">
        <div className="flex items-baseline justify-between mb-2.5">
          <h2 className="font-bold text-[14px]">Headcount</h2>
          {bucket && <button onClick={()=>{setBucket(""); setPage(1);}} className="font-mono text-xs text-peri-deep hover:text-peri">bỏ lọc quy mô ×</button>}
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {BUCKETS.map(b=>{
            const n = stats.data?.buckets.find(x=>x.bucket===b)?.n || 0;
            const c = BUCKET_COLOR[b];
            return (
              <button key={b} onClick={()=>{ setBucket(b===bucket?"":b); setPage(1); }} aria-pressed={bucket===b}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-xl border text-sm font-semibold transition
                  ${bucket===b ? "text-white border-transparent shadow-hard-sm" : "bg-white border-line text-slate hover:border-line-deep hover:-translate-y-px"}`
                }
                style={bucket===b ? {background: c} : {}}>
                <span className="w-2 h-2 rounded-full" style={{background: bucket===b ? "rgba(255,255,255,.85)" : c}} aria-hidden />
                {b}
                <span className={`font-mono text-[11px] ${bucket===b ? "text-white/80" : "text-faint"}`}>{n}</span>
              </button>
            );
          })}
        </div>
        {stats.data && stats.data.buckets.length > 0 && (
          <div className="mt-3 opacity-90">
            <ResponsiveContainer width="100%" height={110}>
              <BarChart data={BUCKETS.map(b => ({bucket: b, n: stats.data!.buckets.find(x=>x.bucket===b)?.n || 0}))}>
                <XAxis dataKey="bucket" tick={TICK} axisLine={false} tickLine={false} />
                <YAxis hide />
                <Bar dataKey="n" name="công ty" radius={[4,4,0,0]} onClick={(d:any)=>{ if(d?.bucket){ setBucket(d.bucket===bucket?"":d.bucket); setPage(1); }}}>
                  {BUCKETS.map(b=> <Cell key={b} fill={BUCKET_COLOR[b] || "#5566ff"} opacity={bucket && bucket!==b ? 0.3 : 1} cursor="pointer" />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Toolbar */}
      <div className="soft-card rounded-2xl p-3 flex gap-2 flex-wrap items-center">
        <div className="relative flex-1 min-w-[200px]">
          <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-faint text-sm" aria-hidden>⌕</span>
          <input value={q} onChange={e=>{setQ(e.target.value); setPage(1);}} placeholder="Search company, e.g. FPT, Viettel, VNPAY…" className="w-full bg-white border border-line rounded-full pl-9 pr-3 py-2 text-sm text-ink placeholder:text-faint focus:outline-none focus:border-peri" />
        </div>
        <div className="flex rounded-full bg-white border border-line p-1 shadow-sm">
          {["", "itviec", "topcv", "topdev"].map(s=>(
            <button key={s||"all"} onClick={()=>{setSource(s); setPage(1);}} className={`px-3 py-1 rounded-full text-xs font-medium transition ${source===s ? "bg-peri text-white" : "text-slate hover:text-ink"}`}>{s || "All"}</button>
          ))}
        </div>
        <button onClick={()=>{setItOnly(itOnly?0:1);setPage(1);}} aria-pressed={!!itOnly}
          className={`px-3.5 py-1.5 rounded-full text-xs border font-medium transition ${itOnly ? "text-peri-deep border-peri/50 bg-peri-soft" : "text-slate border-line bg-white"}`}>IT / công nghệ {itOnly ? "✓" : ""}</button>
        <button onClick={()=>{setHiring(hiring?0:1); setPage(1);}} aria-pressed={!!hiring}
          className={`px-3.5 py-1.5 rounded-full text-xs font-bold border transition ${hiring ? "bg-mint text-white border-mint shadow-sm" : "bg-white border-line text-slate hover:border-line-deep"}`}>
          💼 Hiring {hiring ? "✓" : ""}
        </button>
        <button onClick={()=>setToolsOpen(!toolsOpen)}
          className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition ${toolsOpen ? "bg-paper-deep text-ink border-line-deep" : "bg-white text-slate border-line hover:border-line-deep"}`}>
          Data tools {toolsOpen ? "▴" : "▾"}
        </button>
        <span className="font-mono text-xs text-faint self-center ml-auto">{total} công ty</span>
      </div>

      {toolsOpen && (
        <div className="soft-card rounded-2xl p-4 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-slate">Profiles missing info</span>
            {MISSING_FIELDS.map(field => <button key={field.value} aria-pressed={missingFields.includes(field.value)}
              onClick={() => toggleMissing(field.value)}
              className={`px-3 py-1.5 rounded-full text-xs border transition ${missingFields.includes(field.value) ? "bg-peri-soft border-peri/50 text-peri-deep" : "bg-white border-line text-slate hover:border-line-deep"}`}>
              {field.label} <span className="font-mono opacity-70">{stats.data?.missing_counts[field.value] ?? "–"}</span>
            </button>)}
            {missingFields.length > 1 && <select aria-label="Combine missing info" value={missingMode}
              onChange={e => { setMissingMode(e.target.value as "all" | "any"); setPage(1); }}
              className="bg-white border border-line rounded-full px-3 py-1.5 text-xs text-slate">
              <option value="all">Missing all selected</option>
              <option value="any">Missing at least one selected</option>
            </select>}
            <button onClick={() => downloadCompaniesCsv(filterParams)} className="px-3 py-1.5 rounded-full text-xs border border-line text-slate bg-white hover:border-line-deep ml-auto">Download CSV ↓</button>
          </div>
          <p className="text-faint text-xs">Used to inspect data quality and export the list to a spreadsheet.</p>
        </div>
      )}

      {companies.isError ? <p role="alert" className="text-coral p-6">Failed to load company directory.</p> : companies.isPending ? <div className="py-16 text-center font-mono text-sm text-faint">loading…</div> :
        !companies.data?.companies.length ? (
          <div className="soft-card rounded-2xl py-16 text-center">
            <p className="font-bold">No matching companies</p>
            <p className="text-sm text-slate mt-1">Thử bỏ "Hiring", change size or keyword.</p>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {companies.data.companies.map(c=>{
              const key = coKey(c);
              const isExp = openCo===key;
              return (
              <Fragment key={key}>
                <article onClick={()=>toggleCo(key)}
                  className={`soft-card rounded-2xl p-4 flex flex-col gap-2.5 cursor-pointer transition-all hover:-translate-y-0.5 ${isExp ? "ring-2 ring-peri/40" : ""}`}>
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${SOURCE_DOT[c.source] || "bg-faint"}`} title={c.source} />
                    <h3 className="font-bold text-[15px] truncate flex-1">{c.company}</h3>
                    {!!c.is_hiring && <span className="px-1.5 py-0.5 rounded-md bg-mint-soft text-mint text-[10px] font-bold shrink-0">ĐANG TUYỂN</span>}
                  </div>
                  <div className="flex items-center gap-2 flex-wrap text-xs">
                    {c.size_raw ? (
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-paper border border-line font-semibold">
                        <span className="w-1.5 h-1.5 rounded-full" style={{background: BUCKET_COLOR[c.bucket || ""] || "#9aa0bf"}} />
                        {c.size_raw}{c.num_employees ? ` · ${c.num_employees} NV` : ""}
                      </span>
                    ) : <span className="text-faint">— unknown size</span>}
                    {c.industry && <span className="text-mute truncate max-w-[200px]">{c.industry}</span>}
                  </div>
                  <div className="flex items-end justify-between gap-2 mt-0.5">
                    <div>
                      <div className="font-extrabold text-[22px] leading-none">{c.job_count}</div>
                      <div className="font-mono text-[10px] uppercase tracking-wider text-faint mt-0.5">việc còn mở</div>
                    </div>
                    <div className="flex flex-wrap gap-1 justify-end max-w-[70%]">
                      {(c.hiring_roles || []).map(r => (
                        <span key={r.name} className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-peri-soft text-peri-deep border border-peri/25">
                          {r.name} <span className="font-mono opacity-70">{r.n}</span>
                        </span>
                      ))}
                      {!c.hiring_roles?.length && <span className="text-[11px] text-faint">positions not yet extracted from collected jobs</span>}
                    </div>
                  </div>
                  <div className="flex gap-1.5 pt-1 border-t border-line" onClick={e => e.stopPropagation()}>
                    <button onClick={()=>onFilterCompany?.(c)} disabled={!c.job_count}
                      className="flex-1 px-3 py-1.5 rounded-[10px] bg-peri text-white text-xs font-bold border border-ink shadow-hard-sm press-hard disabled:opacity-40 disabled:cursor-not-allowed">
                      {c.job_count ? `View ${c.job_count} việc →` : "No open jobs"}
                    </button>
                    {c.detail_url && <a href={c.detail_url} target="_blank" rel="noreferrer"
                      className="px-3 py-1.5 rounded-[10px] bg-white border border-line text-xs font-medium text-slate hover:border-peri hover:text-peri">Open source ↗</a>}
                    <button onClick={()=>toggleCo(key)} aria-expanded={isExp}
                      className="px-3 py-1.5 rounded-[10px] bg-white border border-line text-xs font-medium text-slate hover:border-line-deep">
                      {isExp ? "Collapse ▴" : "Chi tiết ▾"}
                    </button>
                  </div>
                </article>
                {isExp && (
                  <div className="md:col-span-2 -mt-1 rounded-2xl border border-line bg-white/70 p-4">
                    <CompanyDetail company={c} city={city} onFilterCompany={onFilterCompany} />
                  </div>
                )}
              </Fragment>
            );})}
          </div>
        )}
      {pages > 1 && (
        <div className="flex items-center justify-center gap-2 py-2 font-mono text-sm">
          <button disabled={page<=1} onClick={()=>setPage(page-1)} className="px-2.5 py-1 rounded-full border border-line bg-white disabled:opacity-30 hover:border-line-deep">←</button>
          <span className="text-faint">{page}/{pages} · {total}</span>
          <button disabled={page>=pages} onClick={()=>setPage(page+1)} className="px-2.5 py-1 rounded-full border border-line bg-white disabled:opacity-30 hover:border-line-deep">→</button>
        </div>
      )}
      <p className="font-mono text-[11px] text-faint">
        {city && "Province/matching by company address or location of collected open jobs. "}
        Directory accumulated from ITviec sitemap, TopCV and TopDev directory; companies may overlap across sources. Profiles enriched continuously within budget; empty fields mean no data. Cannot claim full coverage of all Vietnamese companies.
      </p>
    </div>
  );
}

function CompanyDetail({ company: c, city, onFilterCompany }: { company: Company; city: string; onFilterCompany?: (c: Company) => void }) {
  const qc = useQueryClient();
  const jobs = useQuery({
    queryKey: ["company-jobs", c.source, c.company, c.detail_url, city],
    queryFn: async () => {
      const p = new URLSearchParams({
        company: c.company, company_url: c.detail_url || "", source: c.source, city,
        limit: "10", sort: "relevance", relevance_min: "0", since_hours: "0",
        show_hidden: "1",
      });
      const r = await apiFetch(`/api/jobs?${p.toString()}`);
      if (!r.ok) throw new Error(`${r.status}`);
      return (await r.json()) as { total: number; jobs: JobLite[] };
    },
    staleTime: 60_000,
  });
  const mark = async (j: JobLite, patch: { viewed?: number; applied?: number; starred?: number }) => {
    await markJob(j.source, j.source_id, patch);
    qc.invalidateQueries({ queryKey: ["company-jobs", c.source, c.company, c.detail_url, city] });
  };
  const openJob = (j: JobLite, apply = false) => {
    window.open(j.url, "_blank", "noopener,noreferrer");
    void mark(j, apply ? { viewed: 1, applied: 1 } : { viewed: 1 });
  };
  return (
    <div className="space-y-3">
      <div className="flex gap-2 flex-wrap text-xs">
        <span className="text-peri-deep font-medium" title={c.it_evidence || "No evidence yet"}>{c.it_status === "technology" ? "Technology" : c.it_status === "it_department" ? "Has IT signal" : "Unclassified"}</span>
        <span className="text-faint">Completeness {c.completeness}%</span>
        <span className="text-faint">{c.fetched_at ? `Check ${new Date(c.fetched_at).toLocaleString("vi-VN")}` : "Awaiting enrichment"}</span>
      </div>
      <dl className="grid gap-2 sm:grid-cols-2 text-sm text-slate">
        {c.website && <div><dt className="text-xs text-faint">Website / tuyển dụng</dt><dd><a className="text-peri-deep break-all" href={c.website} target="_blank" rel="noreferrer">{c.website}</a></dd></div>}
        {c.address && <div><dt className="text-xs text-faint">Address</dt><dd className="whitespace-pre-line">{c.address}</dd></div>}
        {c.company_type && <div><dt className="text-xs text-faint">Model</dt><dd>{c.company_type}</dd></div>}
        {c.country && <div><dt className="text-xs text-faint">Country</dt><dd>{c.country}</dd></div>}
        {c.working_days && <div><dt className="text-xs text-faint">Working schedule</dt><dd>{c.working_days}</dd></div>}
        {c.overtime && <div><dt className="text-xs text-faint">OT policy</dt><dd>{c.overtime}</dd></div>}
      </dl>
      {!!c.tech_stack?.length && <div className="text-xs text-peri-deep font-medium">Skills: {c.tech_stack.join(" · ")}</div>}
      {!!c.public_links?.length && <div className="flex gap-3 flex-wrap text-xs">{c.public_links.map(l=><a key={l.url} className="text-peri-deep" href={l.url} target="_blank" rel="noreferrer">{l.label || l.url} ↗</a>)}</div>}
      {c.it_evidence && <p className="text-xs text-faint">IT evidence: {c.it_evidence}</p>}
      {c.enrichment_error && <p className="text-xs text-coral">Last profile fetch failed; hệ thống sẽ thử lại.</p>}
      {c.description && <p className="text-sm text-slate leading-relaxed line-clamp-4">{c.description}</p>}
      <div>
        <div className="flex items-baseline justify-between mb-1.5">
          <h4 className="font-bold text-sm">Open jobs <span className="font-mono text-xs text-faint">{jobs.data?.total ?? ""}</span></h4>
          <button onClick={()=>onFilterCompany?.(c)} disabled={!c.job_count}
            className="px-2.5 py-1 rounded-full bg-peri text-white text-xs font-semibold hover:bg-peri-deep disabled:opacity-40 disabled:cursor-not-allowed">xem trong Inbox →</button>
        </div>
        {jobs.isPending ? <div className="font-mono text-xs text-faint">loading…</div> :
         !jobs.data?.jobs.length ? <p className="text-sm text-faint">No open jobs for this company.</p> : (
          <ul className="divide-y divide-line rounded-xl border border-line overflow-hidden bg-white">
            {jobs.data.jobs.map(j=>(
              <li key={`${j.source}-${j.source_id}`} className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-paper/70">
                <a href={j.url} target="_blank" rel="noreferrer" className="flex-1 min-w-0 truncate font-medium hover:text-peri-deep">{j.title}</a>
                {!!j.relevance && j.relevance >= 40 && <span className={`px-1.5 rounded-md text-[10px] font-bold shrink-0 ${j.relevance >= 70 ? "bg-mint-soft text-mint" : "bg-peri-soft text-peri-deep"}`}>{j.relevance}%</span>}
                {j.salary && j.salary !== "N/A" && <span className="font-mono text-xs text-amber shrink-0 hidden sm:inline">{j.salary}</span>}
                {j.level && <span className="text-xs text-faint shrink-0 hidden md:inline">{j.level}</span>}
                <span className="flex items-center gap-1 shrink-0">
                  <button onClick={()=>openJob(j)} title="Open job & mark viewed"
                    className="px-2 py-1 rounded-md border border-line text-[11px] text-slate hover:border-peri hover:text-peri">View</button>
                  <button onClick={()=>openJob(j, true)} title="Open job & mark applied"
                    className="px-2 py-1 rounded-md bg-peri text-white text-[11px] font-semibold hover:bg-peri-deep">Apply</button>
                  <button onClick={()=>void mark(j, { starred: j.starred ? 0 : 1 })} aria-pressed={!!j.starred}
                    title={j.starred ? "Bỏ sao" : "Star this job"}
                    className={`px-2 py-1 rounded-md border text-[11px] ${j.starred ? "bg-amber-soft border-amber text-amber" : "border-line text-faint hover:border-line-deep"}`}>
                    {j.starred ? "★" : "☆"}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Kpi({label, value, sub, accent}:{label:string; value:any; sub:string; accent?:boolean}) {
  return (
    <div className={accent ? "rounded-2xl p-3.5 bg-navy text-white border border-navy shadow-hard-sm" : "soft-card rounded-2xl p-3.5"}>
      <div className={`font-mono text-[10px] uppercase tracking-wider ${accent ? "text-white/60" : "text-faint"}`}>{label}</div>
      <div className="text-2xl font-extrabold mt-1">{value}</div>
      <div className={`font-mono text-[11px] truncate ${accent ? "text-white/60" : "text-faint"}`}>{sub}</div>
    </div>
  );
}
