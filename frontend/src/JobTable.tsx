import type { Job } from "./api";

// NEW = hệ thống mới thấy tin này trong 72 giờ qua (tính từ first_seen_at)
function isFresh(firstSeen: string) {
  const t = new Date(firstSeen).getTime();
  return !isNaN(t) && Date.now() - t < 72 * 3600 * 1000;
}

export default function JobTable({ jobs, loading }: { jobs: Job[] | undefined; loading: boolean }) {
  if (loading) return <div className="text-slate-400 text-center py-16">Đang tải…</div>;
  if (!jobs?.length) return <div className="text-slate-400 text-center py-16">Không có job nào khớp filter.</div>;

  return (
    <div className="bg-white rounded-xl shadow overflow-hidden">
      <ul className="divide-y divide-slate-100">
        {jobs.map((j) => (
          <li key={`${j.source}-${j.source_id}`} className="p-4 hover:bg-slate-50">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-0.5">
                  {isFresh(j.first_seen_at) ? <span className="px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-700 text-[10px] font-semibold">NEW</span> : null}
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium shrink-0
                    ${j.source === "itviec" ? "bg-orange-100 text-orange-700" : "bg-rose-100 text-rose-700"}`}>
                    {j.source}
                  </span>
                  <span className="text-xs text-slate-400">{fmtDate(j.posted_at || j.first_seen_at)}</span>
                </div>
                <a href={j.url} target="_blank" rel="noreferrer"
                   className="font-semibold text-blue-700 hover:underline leading-snug block truncate">
                  {j.title}
                </a>
                <div className="text-sm text-slate-500 truncate">{j.company}</div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {j.salary && j.salary !== "N/A" && (
                    <Badge cls="bg-emerald-50 text-emerald-700">💰 {j.salary}</Badge>
                  )}
                  {j.experience && <Badge cls="bg-slate-100 text-slate-600">🐟 {j.experience}</Badge>}
                  {j.category && <Badge cls="bg-indigo-50 text-indigo-600">{j.category}</Badge>}
                  {j.tags.slice(0, 6).map((t) => t && (
                    <Badge key={t} cls="bg-slate-50 text-slate-500 border border-slate-100">{t}</Badge>
                  ))}
                </div>
              </div>
              <a href={j.url} target="_blank" rel="noreferrer"
                 className="shrink-0 self-center px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700">
                Apply ↗
              </a>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function fmtDate(iso: string) {
  return iso ? iso.slice(0, 10) : "";
}

function Badge({ cls, children }: { cls: string; children: React.ReactNode }) {
  return <span className={`px-2 py-0.5 rounded text-xs ${cls}`}>{children}</span>;
}
