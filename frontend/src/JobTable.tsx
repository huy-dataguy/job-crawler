import type { Job } from "./api";

// NEW = hệ thống mới thấy tin này trong 72 giờ qua (tính từ first_seen_at)
function isFresh(firstSeen: string) {
  const t = new Date(firstSeen).getTime();
  return !isNaN(t) && Date.now() - t < 72 * 3600 * 1000;
}

const SOURCE_BAR: Record<string, string> = {
  itviec: "bg-orange-500", topcv: "bg-rose-500", topdev: "bg-sky-500",
};

export default function JobTable({ jobs, loading }: { jobs: Job[] | undefined; loading: boolean }) {
  if (loading) return <div className="font-mono text-sm text-ink-faint text-center py-16">đang tải…</div>;
  if (!jobs?.length)
    return (
      <div className="bg-card border border-line rounded-[10px] px-6 py-16 text-center">
        <p className="font-semibold">Không có việc nào khớp</p>
        <p className="text-sm text-ink-soft mt-1">Nới lỏng từ khóa hoặc bỏ bớt điều kiện lọc rồi thử lại.</p>
      </div>
    );

  return (
    <ul className="bg-card border border-line rounded-[10px] overflow-hidden divide-y divide-line">
      {jobs.map((j) => (
        <li key={`${j.source}-${j.source_id}`} className="flex gap-3 px-4 py-3.5 hover:bg-paper transition">
          <span className={`w-1 self-stretch rounded-full shrink-0 ${SOURCE_BAR[j.source] || "bg-ink-faint"}`} aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 font-mono text-xs text-ink-faint">
              <span>{j.source}</span>
              <span aria-hidden>·</span>
              <span>{(j.posted_at || j.first_seen_at || "").slice(0, 10)}</span>
              {isFresh(j.first_seen_at) && (
                <span className="px-1.5 rounded bg-moss text-paper text-[10px] font-semibold">mới</span>
              )}
            </div>
            <a href={j.url} target="_blank" rel="noreferrer"
               className="font-semibold text-[15px] leading-snug block truncate hover:text-cobalt">
              {j.title}
            </a>
            <div className="text-sm text-ink-soft truncate">{j.company}</div>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {j.salary && j.salary !== "N/A" && (
                <Badge cls="border-moss/40 text-moss font-mono">{j.salary}</Badge>
              )}
              {j.experience && <Badge>{j.experience} KN</Badge>}
              {j.level && <Badge>cấp {j.level}</Badge>}
              {j.category && <Badge cls="text-cobalt border-cobalt/30">{j.category}</Badge>}
              {(j.skills || []).slice(0, 5).map((t) => t && (
                <Badge key={t}>{t}</Badge>
              ))}
            </div>
          </div>
          <a href={j.url} target="_blank" rel="noreferrer"
             className="shrink-0 self-center px-3.5 py-2 text-sm font-semibold rounded-[10px] bg-cobalt text-white hover:bg-cobalt-deep transition">
            Apply
          </a>
        </li>
      ))}
    </ul>
  );
}

function Badge({ cls = "", children }: { cls?: string; children: React.ReactNode }) {
  return (
    <span className={`px-2 py-0.5 rounded-[6px] text-xs border border-line text-ink-soft ${cls}`}>
      {children}
    </span>
  );
}
