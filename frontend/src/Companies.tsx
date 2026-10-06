import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";

type Company = {
  source: string;
  company: string;
  company_slug: string | null;
  detail_url: string | null;
  size_raw: string | null;
  size_min: number | null;
  size_max: number | null;
  num_employees: string | null;
  bucket: string | null;
  fetched_at: string | null;
  is_hiring: number;
  job_count: number;
};

type CompanyStats = {
  total: number;
  enriched: number;
  hiring: number;
  buckets: { bucket: string; n: number }[];
  by_source: { source: string; n: number }[];
};

const BUCKETS = ["<50", "50-100", "101-150", "151-300", "301-1000", "1000+"];
const BUCKET_COLOR: Record<string,string> = {
  "<50":"#34d399", "50-100":"#60a5fa", "101-150":"#a78bfa", "151-300":"#f472b6", "301-1000":"#fb923c", "1000+":"#ef4444"
};
const SOURCE_DOT: Record<string,string> = { itviec:"bg-[#ff9e4a]", topcv:"bg-[#ff6b8a]", topdev:"bg-[#4cc3ff]" };

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

export default function Companies({ onFilterCompany }: { onFilterCompany?: (c: Company) => void }) {
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [bucket, setBucket] = useState("");
  const [hiring, setHiring] = useState(0);
  const [page, setPage] = useState(1);

  const stats = useQuery({ queryKey: ["company-stats"], queryFn: () => get<CompanyStats>("/api/company-stats") });
  const companies = useQuery({
    queryKey: ["companies", q, source, bucket, hiring, page],
    queryFn: () => {
      const p = new URLSearchParams();
      if (q) p.set("q", q);
      if (source) p.set("source", source);
      if (bucket) p.set("bucket", bucket);
      if (hiring) p.set("hiring", "1");
      p.set("limit", "30");
      p.set("offset", String((page - 1) * 30));
      return get<{ total: number; companies: Company[] }>(`/api/companies?${p.toString()}`);
    },
  });

  const total = companies.data?.total ?? 0;
  const pages = Math.ceil(total / 30);
  const coverage = stats.data ? Math.round((stats.data.enriched / Math.max(1, stats.data.total)) * 100) : 0;

  return (
    <div className="space-y-4">
      {/* KPI */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Tổng công ty" value={stats.data?.total ?? "–"} sub={`${stats.data?.by_source.map(s=>`${s.source} ${s.n}`).join(" · ") || ""}`} />
        <Kpi label="Đã có quy mô" value={stats.data?.enriched ?? "–"} sub={`${coverage}% coverage`} accent />
        <Kpi label="Đang tuyển" value={stats.data?.hiring ?? "–"} sub="có tin đang đăng" accent />
        <Kpi label="Bucket nổi bật" value={useMemo(()=>{ if(!stats.data) return "–"; const m = [...stats.data.buckets].sort((a,b)=>b.n-a.n)[0]; return m ? `${m.bucket} (${m.n})` : "–";}, [stats.data])} sub="nhiều nhất" />
      </div>

      {/* Bucket chart — dùng Recharts đồng nhất */}
      <div className="bg-panel border border-edge rounded-[14px] p-4">
        <div className="flex items-baseline justify-between mb-2">
          <h2 className="font-semibold text-[14px]">Phân bố quy mô</h2>
          <span className="font-mono text-xs text-faint">click bucket để lọc</span>
        </div>
        {stats.isPending ? <div className="font-mono text-sm text-faint py-8 text-center">đang tải…</div> : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={stats.data?.buckets || []}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#2a3052" />
              <XAxis dataKey="bucket" tick={{fontSize:11, fill:"#6f7590"}} />
              <YAxis allowDecimals={false} tick={{fontSize:11, fill:"#6f7590"}} />
              <Tooltip contentStyle={{background:"#161a30", border:"1px solid #2a3052", borderRadius:10, color:"#f4f5fa", fontSize:12}} />
              <Bar dataKey="n" name="công ty" radius={[6,6,0,0]} onClick={(d:any)=>{ if(d?.bucket){ setBucket(d.bucket===bucket?"":d.bucket); setPage(1); }}}>
                {(stats.data?.buckets || []).map((b)=> <Cell key={b.bucket} fill={BUCKET_COLOR[b.bucket] || "#8b7cff"} opacity={bucket && bucket!==b.bucket ? 0.35 : 1} cursor="pointer" />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
        <div className="flex gap-1.5 flex-wrap mt-2">
          {BUCKETS.map(b=>{
            const n = stats.data?.buckets.find(x=>x.bucket===b)?.n || 0;
            return (
              <button key={b} onClick={()=>{ setBucket(b===bucket?"":b); setPage(1);}}
                className={`px-2.5 py-1 rounded-full text-xs border transition ${bucket===b ? "bg-ember text-white border-ember" : "bg-night border-edge text-dim hover:border-faint"}`}>{b} <span className="font-mono opacity-60">{n}</span></button>
            );
          })}
          {bucket && <button onClick={()=>setBucket("")} className="font-mono text-xs text-faint hover:text-mist">xoá ×</button>}
        </div>
      </div>

      {/* Filters + Table */}
      <div className="bg-panel border border-edge rounded-[14px] overflow-hidden">
        <div className="p-3 flex gap-2 flex-wrap border-b border-edge bg-panel-deep/50">
          <div className="relative flex-1 min-w-[200px]">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-faint text-sm">⌕</span>
            <input value={q} onChange={e=>{setQ(e.target.value); setPage(1);}} placeholder="Tìm công ty, ví dụ FPT, Viettel, 1000+…" className="w-full bg-night border border-edge rounded-full pl-9 pr-3 py-2 text-sm focus:outline-none focus:border-ember" />
          </div>
          <div className="flex rounded-full bg-night border border-edge p-1">
            {["", "itviec", "topcv", "topdev"].map(s=>(
              <button key={s||"all"} onClick={()=>{setSource(s); setPage(1);}} className={`px-3 py-1 rounded-full text-xs font-medium transition ${source===s ? "bg-ember text-white" : "text-dim hover:text-mist"}`}>{s || "Tất cả"}</button>
            ))}
          </div>
          <button onClick={()=>{setHiring(hiring?0:1); setPage(1);}}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition ${hiring ? "bg-mint text-night border-mint" : "bg-night border-edge text-dim hover:border-faint"}`}>
            💼 Đang tuyển
          </button>
          <span className="font-mono text-xs text-faint self-center hidden sm:inline">{total} công ty</span>
        </div>

        {companies.isPending ? <div className="py-16 text-center font-mono text-sm text-faint">đang tải…</div> :
          !companies.data?.companies.length ? (
            <div className="py-16 text-center">
              <p className="font-semibold">Không có công ty nào khớp</p>
              <p className="text-sm text-dim mt-1">Thử đổi bucket hoặc từ khóa. {bucket==="1000+" ? "" : "Gợi ý: 1000+ có 29 cty đã enrich."}</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-night/60 font-mono text-xs text-faint border-b border-edge">
                  <tr>
                    <th className="text-left py-2.5 px-3 font-medium">Công ty</th>
                    <th className="text-left px-2 hidden sm:table-cell">Nguồn</th>
                    <th className="text-left px-2">Quy mô</th>
                    <th className="text-left px-2 hidden md:table-cell">Bucket</th>
                    <th className="text-right px-2">Jobs</th>
                    <th className="text-right px-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-edge">
                  {companies.data.companies.map(c=>(
                    <tr key={`${c.source}-${c.company}`} className="hover:bg-night/60 transition">
                      <td className="py-2.5 px-3">
                        <div className="flex items-center gap-2">
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${SOURCE_DOT[c.source] || "bg-faint"}`} />
                          <span className="font-medium truncate max-w-[260px]">{c.company}</span>
                          {!!c.is_hiring && <span className="px-1.5 rounded bg-mint/15 text-mint text-[10px] font-semibold shrink-0">đang tuyển</span>}
                        </div>
                        <span className="sm:hidden font-mono text-xs text-faint">{c.source} · {c.bucket || "unknown"}</span>
                      </td>
                      <td className="px-2 hidden sm:table-cell font-mono text-xs text-faint">{c.source}</td>
                      <td className="px-2">
                        {c.size_raw ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-night border border-edge text-xs">
                            <span className="w-1.5 h-1.5 rounded-full" style={{background: BUCKET_COLOR[c.bucket || ""] || "#6f7590"}} />
                            {c.size_raw}
                          </span>
                        ) : <span className="text-faint text-xs">— chưa có</span>}
                      </td>
                      <td className="px-2 hidden md:table-cell">
                        <span className={`px-2 py-0.5 rounded-full text-xs border ${c.bucket ? "bg-ember/10 border-ember/30 text-ember" : "border-edge text-faint"}`}>{c.bucket || "unknown"}</span>
                      </td>
                      <td className="px-2 text-right font-mono text-sm">{c.job_count}</td>
                      <td className="px-3 text-right">
                        <div className="flex justify-end gap-1">
                          {c.detail_url && <a href={c.detail_url} target="_blank" rel="noreferrer" className="px-2 py-1 rounded-full bg-night border border-edge text-xs hover:border-violet hover:text-violet">mở</a>}
                          <button onClick={()=>onFilterCompany?.(c)} className="px-2.5 py-1 rounded-full bg-violet text-white text-xs font-medium hover:brightness-110">lọc jobs →</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        {pages > 1 && (
          <div className="flex items-center justify-center gap-2 py-3 border-t border-edge bg-panel-deep/30 font-mono text-sm">
            <button disabled={page<=1} onClick={()=>setPage(page-1)} className="px-2 py-1 rounded-full border border-edge disabled:opacity-30 hover:bg-white/5">←</button>
            <span className="text-faint">{page}/{pages} · {total}</span>
            <button disabled={page>=pages} onClick={()=>setPage(page+1)} className="px-2 py-1 rounded-full border border-edge disabled:opacity-30 hover:bg-white/5">→</button>
          </div>
        )}
      </div>
      <p className="font-mono text-xs text-faint">
        Thư mục harvest: TopCV qua sitemap (đầy đủ), ITviec directory phân trang, TopDev trang đầu + tích lũy từ tin đăng. Đã enrich quy mô {stats.data?.enriched}/{stats.data?.total} — enrich chạy tiếp mỗi ngày theo ngân sách.
      </p>
    </div>
  );
}

function Kpi({label, value, sub, accent}:{label:string; value:any; sub:string; accent?:boolean}) {
  return (
    <div className={`rounded-[14px] border p-3 ${accent ? "bg-gradient-to-br from-ember/15 to-violet/15 border-ember/30" : "bg-panel border-edge"}`}>
      <div className="font-mono text-xs text-faint">{label}</div>
      <div className="text-xl font-extrabold mt-1">{value}</div>
      <div className="font-mono text-xs text-faint truncate">{sub}</div>
    </div>
  );
}
