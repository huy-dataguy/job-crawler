import type { Job } from "./api";

// "Mới" thống nhất toàn web = ngày đăng trong 72h qua (cùng gốc với KPI "mới 24h",
// chỉ khác cửa sổ). posted_at là ước tính từ "đăng N ngày trước"; thiếu thì fallback first_seen.
export function isFresh(postedAt: string | null, firstSeen: string) {
  const t = new Date(postedAt || firstSeen).getTime();
  return !isNaN(t) && Date.now() - t < 72 * 3600 * 1000;
}

const SOURCE_BAR: Record<string, string> = {
  itviec: "bg-[#ff9e4a]", topcv: "bg-[#ff6b8a]", topdev: "bg-[#4cc3ff]",
};

export default function JobTable({ jobs, loading }: { jobs: Job[] | undefined; loading: boolean }) {
  if (loading) return <div className="font-mono text-sm text-faint text-center py-16">đang tải…</div>;
  if (!jobs?.length)
    return (
      <div className="bg-panel border border-edge rounded-[10px] px-6 py-16 text-center">
        <p className="font-semibold">Không có việc nào khớp</p>
        <p className="text-sm text-dim mt-1">Nới lỏng từ khóa hoặc bỏ bớt điều kiện lọc rồi thử lại.</p>
      </div>
    );

  return (
    <ul className="bg-panel border border-edge rounded-[10px] overflow-hidden divide-y divide-edge">
      {jobs.map((j) => (
        <li key={`${j.source}-${j.source_id}`} className="flex gap-3 px-4 py-3.5 hover:bg-night transition">
          <span className={`w-1 self-stretch rounded-full shrink-0 ${SOURCE_BAR[j.source] || "bg-faint"}`} aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 font-mono text-xs text-faint">
              <span>{j.source}</span>
              <span aria-hidden>·</span>
              <span>{(j.posted_at || j.first_seen_at || "").slice(0, 10)}</span>
              {isFresh(j.posted_at, j.first_seen_at) && (
                <span className="px-1.5 rounded bg-mint text-night text-[10px] font-semibold">mới</span>
              )}
            </div>
            <a href={j.url} target="_blank" rel="noreferrer"
               className="font-semibold text-[15px] leading-snug block truncate hover:text-violet">
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
              {(j.skills || []).slice(0, 5).map((t) => t && (
                <Badge key={t}>{t}</Badge>
              ))}
            </div>
          </div>
          <a href={j.url} target="_blank" rel="noreferrer"
             className="shrink-0 self-center px-3.5 py-2 text-sm font-semibold rounded-[10px] bg-gradient-to-r from-ember to-[#ff8a3c] text-white hover:brightness-110 transition">
            Apply
          </a>
        </li>
      ))}
    </ul>
  );
}

function Badge({ cls = "", children }: { cls?: string; children: React.ReactNode }) {
  return (
    <span className={`px-2 py-0.5 rounded-[6px] text-xs border border-edge text-dim ${cls}`}>
      {children}
    </span>
  );
}
