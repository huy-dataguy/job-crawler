import type { Job } from "./api";
import { markJob } from "./api";
import { useState } from "react";

// "Mới" thống nhất toàn web = ngày đăng trong 72h qua (cùng gốc với KPI "mới 24h",
// chỉ khác cửa sổ). posted_at là ước tính từ "đăng N ngày trước"; thiếu thì fallback first_seen.
export function isFresh(postedAt: string | null, firstSeen: string) {
  const t = new Date(postedAt || firstSeen).getTime();
  return !isNaN(t) && Date.now() - t < 72 * 3600 * 1000;
}

const SOURCE_BAR: Record<string, string> = {
  itviec: "bg-[#ff9e4a]", topcv: "bg-[#ff6b8a]", topdev: "bg-[#4cc3ff]",
};

export default function JobTable({ jobs, loading, onChanged }: { jobs: Job[] | undefined; loading: boolean; onChanged?: () => void }) {
  if (loading) return (
    <div className="bg-panel border border-edge rounded-[14px] overflow-hidden divide-y divide-edge">
      {[1,2,3,4].map(i=>(
        <div key={i} className="px-4 py-4 flex gap-3 animate-pulse">
          <div className="w-1 h-14 bg-edge rounded-full" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-24 bg-edge rounded" />
            <div className="h-4 w-3/4 bg-edge rounded" />
            <div className="h-3 w-1/2 bg-edge rounded" />
          </div>
        </div>
      ))}
    </div>
  );
  if (!jobs?.length)
    return (
      <div className="bg-panel border border-edge rounded-[14px] px-6 py-12 text-center">
        <div className="w-10 h-10 rounded-full bg-night border border-edge flex items-center justify-center mx-auto text-faint">⌕</div>
        <p className="font-semibold mt-3">Không có việc nào khớp</p>
        <p className="text-sm text-dim mt-1 max-w-[36ch] mx-auto">Thử nới lỏng từ khóa, đổi bucket quy mô hoặc bật “Hiện Không OK”.</p>
      </div>
    );

  return (
    <ul className="bg-panel border border-edge rounded-[14px] overflow-hidden divide-y divide-edge shadow-sm">
      {jobs.map((j) => (
        <JobRow key={`${j.source}-${j.source_id}`} job={j} onChanged={onChanged} />
      ))}
    </ul>
  );
}

function JobRow({ job: j, onChanged }: { job: Job; onChanged?: () => void }) {
  const [busy, setBusy] = useState(false);
  const viewed = !!j.viewed;
  const hidden = !!j.hidden;

  const toggleViewed = async () => {
    setBusy(true);
    try { await markJob(j.source, j.source_id, { viewed: viewed ? 0 : 1 }); onChanged?.(); } finally { setBusy(false); }
  };
  const toggleHidden = async () => {
    setBusy(true);
    try { await markJob(j.source, j.source_id, { hidden: hidden ? 0 : 1 }); onChanged?.(); } finally { setBusy(false); }
  };

  return (
    <li className={`flex gap-3 px-4 py-3.5 hover:bg-night/60 transition ${viewed ? "opacity-[0.58]" : ""} ${hidden ? "bg-red-950/10" : ""}`}>
      <span className={`w-1 self-stretch rounded-full shrink-0 ${SOURCE_BAR[j.source] || "bg-faint"}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 font-mono text-xs text-faint">
          <span>{j.source}</span>
          <span aria-hidden>·</span>
          <span>{(j.posted_at || j.first_seen_at || "").slice(0, 10)}</span>
          {isFresh(j.posted_at, j.first_seen_at) && (
            <span className="px-1.5 rounded bg-mint text-night text-[10px] font-semibold">mới</span>
          )}
          {!!j.relevance && j.relevance >= 40 && (
            <span
              title={`Khớp profile CV: ${(j.matched || []).join(", ")}`}
              className={`px-1.5 rounded text-[10px] font-semibold cursor-help ${j.relevance >= 70 ? "bg-mint/20 text-mint" : "bg-violet/15 text-violet"}`}
            >
              {j.relevance}% khớp
            </span>
          )}
          {viewed && <span className="px-1.5 rounded bg-edge text-faint text-[10px]">đã xem</span>}
          {hidden && <span className="px-1.5 rounded bg-red-500 text-white text-[10px]">không OK</span>}
        </div>
        <a href={j.url} target="_blank" rel="noreferrer" onClick={() => { if (!viewed) markJob(j.source, j.source_id, { viewed: 1 }).then(() => onChanged?.()); }}
           className={`font-semibold text-[15px] leading-snug block truncate hover:text-violet ${viewed ? "text-dim" : ""}`}>
          {j.title}
        </a>
        <div className="text-sm text-dim truncate">{j.company}</div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {j.salary && j.salary !== "N/A" && (
            <Badge cls="border-mint/40 text-mint font-mono">{j.salary}</Badge>
          )}
          {j.experience && <Badge>{j.experience} KN</Badge>}
          {j.level && <Badge>cấp {j.level}</Badge>}
          {j.category && <Badge cls="text-violet border-violet/40">{j.category}</Badge>}
          {j.company_bucket && <Badge cls="bg-amber-500/10 border-amber-500/20 text-amber-700">🏢 {j.company_bucket}</Badge>}
          {(j.skills || []).slice(0, 5).map((t) => t && (
            <Badge key={t}>{t}</Badge>
          ))}
        </div>
      </div>
      <div className="shrink-0 self-center flex flex-col gap-1.5">
        <button onClick={toggleViewed} disabled={busy}
          className={`px-3 py-1.5 text-xs font-semibold rounded-[8px] border transition ${viewed ? "bg-edge text-mist border-edge" : "bg-panel border-edge hover:border-ember text-dim"}`}>
          {viewed ? "✓ Đã xem" : "👁 Đã xem"}
        </button>
        <button onClick={toggleHidden} disabled={busy}
          className={`px-3 py-1.5 text-xs font-semibold rounded-[8px] border transition ${hidden ? "bg-red-500 text-white border-red-500" : "bg-panel border-edge hover:border-red-400 text-dim hover:text-red-400"}`}>
          {hidden ? "↩ Bỏ ẩn" : "✕ Không OK"}
        </button>
        <a href={j.url} target="_blank" rel="noreferrer"
           className="px-3.5 py-1.5 text-xs font-semibold rounded-[8px] bg-gradient-to-r from-ember to-[#ff8a3c] text-white hover:brightness-110 transition text-center">
          Apply
        </a>
      </div>
    </li>
  );
}

function Badge({ cls = "", children }: { cls?: string; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border border-edge text-dim ${cls}`}>
      {children}
    </span>
  );
}
