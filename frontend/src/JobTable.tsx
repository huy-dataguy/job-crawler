import type { Job } from "./api";
import { markJob, fetchJobDetail } from "./api";
import { BUCKET_COLOR } from "./company";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

// "Mới" thống nhất toàn web = ngày đăng trong 72h qua. posted_at là ước tính
// từ "đăng N ngày trước"; thiếu thì fallback first_seen.
export function isFresh(postedAt: string | null, firstSeen: string) {
  const t = new Date(postedAt || "").getTime();
  return !isNaN(t) && Date.now() >= t && Date.now() - t < 72 * 3600 * 1000;
}

export const jobKey = (j: Pick<Job, "source" | "source_id">) => `${j.source}:${j.source_id}`;

const SOURCE_DOT: Record<string, string> = {
  itviec: "bg-[#f97316]", topcv: "bg-[#ec4899]", topdev: "bg-[#0ea5e9]",
};

function relTier(r: number | null) {
  if (r == null || r < 40) return { label: "", cls: "", pct: 0 };
  if (r >= 70) return { label: "Rất khớp", cls: "bg-mint-soft text-mint border-mint/40", bar: "bg-mint", pct: r };
  return { label: "Khớp", cls: "bg-peri-soft text-peri-deep border-peri/40", bar: "bg-peri", pct: r };
}

export default function JobTable({ jobs, loading, onChanged, listKey, openKey, onToggleOpen }: {
  jobs: Job[] | undefined; loading: boolean; onChanged?: () => void; listKey: string;
  openKey?: string | null; onToggleOpen?: (key: string) => void;
}) {
  const [sel, setSel] = useState(0);
  const items = jobs ?? [];

  // đổi filter/trang → chọn lại từ đầu; refetch (mark/xoá 1 job) → giữ vị trí
  useEffect(() => { setSel(0); }, [listKey]);
  useEffect(() => { setSel((s) => Math.min(s, Math.max(0, items.length - 1))); }, [items.length]);

  const act = useRef({
    open: (j: Job) => {
      window.open(j.url, "_blank", "noopener");
      if (!j.viewed) markJob(j.source, j.source_id, { viewed: 1 }).then(() => onChanged?.());
    },
    apply: (j: Job) => {
      window.open(j.url, "_blank", "noopener");
      markJob(j.source, j.source_id, { applied: 1, viewed: 1 }).then(() => onChanged?.());
    },
  });
  const rowRefs = useRef<(HTMLLIElement | null)[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const j = items[sel];
      if (e.key === "j" || e.key === "ArrowDown") { setSel((s) => Math.min(s + 1, items.length - 1)); e.preventDefault(); }
      else if (e.key === "k" || e.key === "ArrowUp") { setSel((s) => Math.max(s - 1, 0)); e.preventDefault(); }
      else if (!j) return;
      else if (e.key === "Enter" || e.key === "o") { act.current.open(j); e.preventDefault(); }
      else if (e.key === "a") {
        if (j.applied) markJob(j.source, j.source_id, { applied: 0 }).then(() => onChanged?.());
        else act.current.apply(j);
        e.preventDefault();
      }
      else if (e.key === "x") { markJob(j.source, j.source_id, { hidden: j.hidden ? 0 : 1 }).then(() => onChanged?.()); e.preventDefault(); }
      else if (e.key === "v") { markJob(j.source, j.source_id, { viewed: j.viewed ? 0 : 1 }).then(() => onChanged?.()); e.preventDefault(); }
      else if (e.key === "s") { markJob(j.source, j.source_id, { starred: j.starred ? 0 : 1 }).then(() => onChanged?.()); e.preventDefault(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [items, sel, onChanged]);

  useEffect(() => {
    rowRefs.current[sel]?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  // JD mở qua URL (deep-link/back) → cuộn row vào tầm nhìn, kể cả khi ở cuối danh sách
  useEffect(() => {
    if (!openKey) return;
    const i = items.findIndex((j) => jobKey(j) === openKey);
    if (i >= 0) rowRefs.current[i]?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openKey, items]);

  if (loading) return (
    <div className="space-y-2">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="soft-card rounded-2xl px-4 py-4 flex gap-3 animate-pulse">
          <div className="w-1 h-14 bg-line rounded-full" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-24 bg-line rounded" />
            <div className="h-4 w-3/4 bg-line rounded" />
            <div className="h-3 w-1/2 bg-line rounded" />
          </div>
        </div>
      ))}
    </div>
  );

  if (!items.length) return (
    <div className="soft-card rounded-2xl px-6 py-14 text-center">
      <div className="w-11 h-11 rounded-full bg-mint-soft text-mint flex items-center justify-center mx-auto text-lg">✓</div>
      <p className="font-bold mt-3">Sạch rồi — không còn job nào ở mục này</p>
      <p className="text-sm text-slate mt-1">Thử nới "KN yêu cầu", bật thêm hướng ứng tuyển, hoặc mở rộng thời gian đăng.</p>
    </div>
  );

  return (
    <ul className="space-y-2">
      {items.map((j, i) => (
        <JobRow key={`${j.source}-${j.source_id}`} job={j} selected={i === sel}
          onHover={() => setSel(i)}
          rowRef={(el) => { rowRefs.current[i] = el; }}
          onOpen={() => act.current.open(j)}
          onApply={() => (j.applied ? markJob(j.source, j.source_id, { applied: 0 }).then(() => onChanged?.()) : act.current.apply(j))}
          onHide={() => markJob(j.source, j.source_id, { hidden: j.hidden ? 0 : 1 }).then(() => onChanged?.())}
          onViewed={() => markJob(j.source, j.source_id, { viewed: j.viewed ? 0 : 1 }).then(() => onChanged?.())}
          onStar={() => markJob(j.source, j.source_id, { starred: j.starred ? 0 : 1 }).then(() => onChanged?.())}
          expanded={openKey === jobKey(j)}
          onToggleExpand={() => onToggleOpen?.(jobKey(j))} />
      ))}
    </ul>
  );
}

function JobRow({ job: j, selected, onHover, rowRef, onOpen, onApply, onHide, onViewed, onStar, expanded, onToggleExpand }: {
  job: Job; selected: boolean; onHover: () => void;
  rowRef: (el: HTMLLIElement | null) => void;
  onOpen: () => void; onApply: () => void; onHide: () => void; onViewed: () => void; onStar: () => void;
  expanded: boolean; onToggleExpand: () => void;
}) {
  const rel = relTier(j.relevance);
  const detail = useQuery({queryKey: ["job-detail",j.source,j.source_id], queryFn:()=>fetchJobDetail(j), enabled:expanded, staleTime:60_000});
  const viewed = !!j.viewed;
  const applied = !!j.applied;
  const hidden = !!j.hidden;
  const starred = !!j.starred;
  const matched = j.matched || [];
  const others = (j.skills || []).filter((s) => !matched.includes(s)).slice(0, 4);

  return (
    <li ref={rowRef} onMouseEnter={onHover}
      className={`relative rounded-2xl border px-4 py-3.5 transition-all
        ${selected ? "bg-white border-peri ring-2 ring-peri/30" : "bg-white border-line hover:border-line-deep hover:shadow-[0_10px_28px_-18px_rgba(24,28,64,0.35)]"}
        ${applied ? "!bg-mint-soft/40" : ""} ${hidden ? "opacity-50" : ""}`}>
      <div className="flex gap-3">
        <span className={`absolute left-0 top-3 bottom-3 w-[3px] rounded-full ${selected ? "bg-peri" : SOURCE_DOT[j.source] || "bg-line-deep"}`} aria-hidden />
        <div className="min-w-0 flex-1 pl-1.5">
          {/* dòng meta: điểm khớp · nguồn · thời gian · trạng thái */}
          <div className="flex items-center gap-2 font-mono text-[11px] text-faint flex-wrap">
            {rel.pct > 0 && (
              <span className={`px-1.5 rounded-md font-semibold border cursor-help ${rel.cls}`}
                title={`Khớp profile CV: ${matched.join(", ")}`}>
                {rel.label} {j.relevance}
              </span>
            )}
            <span>{j.source}</span>
            <span aria-hidden>·</span>
            <span>{j.posted_at ? `Đăng ${j.posted_at.slice(0, 10)}` : "Chưa rõ ngày đăng"}</span>
            <span title={j.detail_checked_at ? `Kiểm tra ${new Date(j.detail_checked_at).toLocaleString("vi-VN")}` : "Chưa kiểm tra trang chi tiết"}
              className={j.effective_status === "open" ? "text-mint" : "text-faint"}>
              {j.effective_status === "open" ? "● Còn mở" : j.effective_status === "closed" ? "Đã đóng" : "Chưa xác nhận"}
            </span>
            {j.work_mode && <span>{j.work_mode}</span>}
            {j.valid_through && <span>Hạn {j.valid_through.slice(0,10)}</span>}
            {isFresh(j.posted_at, j.first_seen_at) && !applied && (
              <span className="px-1.5 rounded-md bg-coral text-white text-[10px] font-bold">MỚI</span>
            )}
            {starred && (
              <span className="px-1.5 rounded-md bg-amber-soft text-amber text-[10px] font-bold" title="Đã sao (s)">★ SAO</span>
            )}
            {applied && <span className="px-1.5 rounded-md bg-mint text-white text-[10px] font-bold">ĐÃ APPLY</span>}
            {viewed && !applied && <span className="px-1.5 rounded-md bg-paper-deep text-mute text-[10px]">đã xem</span>}
            {hidden && <span className="px-1.5 rounded-md bg-coral text-white text-[10px]">không OK</span>}
            {j.company_bucket && (
              <span className="hidden sm:inline-flex items-center gap-1 px-1.5 rounded-md bg-paper border border-line" title={`Quy mô công ty: ${j.company_bucket} nhân sự`}>
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: BUCKET_COLOR[j.company_bucket] || "#9aa0bf" }} aria-hidden />
                {j.company_bucket}
              </span>
            )}
          </div>
          <a href={j.url} target="_blank" rel="noreferrer" onClick={onOpen}
            className={`mt-1 font-bold text-[15.5px] leading-snug block hover:text-peri-deep transition-colors ${viewed && !applied ? "text-slate" : "text-ink"}`}>
            {j.title}
          </a>
          <div className="text-[13.5px] text-slate truncate">
            <span className="font-medium">{j.company}</span>
            {j.salary && j.salary !== "N/A" && <span className="text-amber font-mono font-semibold text-[13px]"> · {j.salary}</span>}
            {(j.experience || j.level) && <span> · {j.experience || j.level}</span>}
            {j.city && <span className="hidden sm:inline"> · {j.city}</span>}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {matched.slice(0, 5).map((t) => (
              <span key={t} className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-peri-soft text-peri-deep border border-peri/25">🎯 {t}</span>
            ))}
            {others.map((t) => (
              <span key={t} className="px-2 py-0.5 rounded-full text-[11px] text-slate border border-line bg-white">{t}</span>
            ))}
            {j.category && <span className="px-2 py-0.5 rounded-full text-[11px] text-mute border border-line">{j.category}</span>}
            <button onClick={onToggleExpand} aria-expanded={expanded}
              className="text-[11.5px] font-semibold text-peri-deep px-2 py-0.5 rounded-full border border-peri/30 hover:bg-peri-soft transition">
              {expanded ? "Thu gọn JD ↑" : "Xem JD & phúc lợi ↓"}
            </button>
          </div>
          {expanded && <div className="mt-3 rounded-xl bg-paper border border-line p-3.5 space-y-3 text-sm">
            {detail.isPending ? <p className="text-faint">Đang tải…</p> : detail.isError ? <p className="text-coral">Không tải được chi tiết.</p> : <>
              <p className="text-faint text-xs">{j.employment_type || "Chưa rõ loại hợp đồng"} · {j.date_source === "structured" ? "Ngày đăng gốc từ nguồn" : "Ngày ước tính trên danh sách"}</p>
              <p className="whitespace-pre-wrap text-slate max-h-[480px] overflow-y-auto strip-scroll leading-relaxed">{detail.data?.description || "JD đang chờ thu thập. Mở trang nguồn để xem đầy đủ."}</p>
              {detail.data?.requirements && <div><h4 className="font-bold mb-1 text-ink">Yêu cầu</h4><p className="whitespace-pre-wrap text-slate">{detail.data.requirements}</p></div>}
              {detail.data?.benefits && <div><h4 className="font-bold mb-1 text-ink">Phúc lợi</h4><p className="whitespace-pre-wrap text-slate max-h-72 overflow-y-auto strip-scroll">{detail.data.benefits}</p></div>}
              {j.company_url && <a href={j.company_url} target="_blank" rel="noreferrer" className="text-peri-deep font-medium">Hồ sơ công ty trên nguồn →</a>}
            </>}
          </div>}
        </div>
        {/* hành động: apply là primary — periwinkle đổ cứng kiểu neo-brutalist */}
        <div className="shrink-0 self-center flex flex-col gap-1.5">
          {applied ? (
            <button onClick={onApply} title="Bỏ đánh dấu đã apply (a)"
              className="px-3.5 py-1.5 text-xs font-bold rounded-[10px] bg-mint-soft text-mint border border-mint/40 hover:bg-mint/20 transition">
              ✓ Đã apply
            </button>
          ) : (
            <a href={j.url} target="_blank" rel="noreferrer" onClick={onApply}
              title="Mở job + đánh dấu đã apply (a)"
              className="px-4 py-1.5 text-xs font-bold rounded-[10px] bg-peri text-white border border-ink shadow-hard-sm press-hard text-center">
              Apply →
            </a>
          )}
          <div className="flex gap-1.5">
            <button onClick={onStar} title="Sao — việc muốn giữ để quay lại (s)"
              aria-pressed={starred}
              className={`flex-1 px-2 py-1.5 text-xs rounded-[10px] border transition ${starred ? "bg-[#fef3e2] text-[#d97706] border-[#f59e0b]" : "bg-white border-line hover:border-[#f59e0b]/60 text-slate hover:text-[#d97706]"}`}>
              {starred ? "★" : "☆"}
            </button>
            <button onClick={onViewed}
              title="Đánh dấu đã xem (v)"
              className={`flex-1 px-2 py-1.5 text-xs rounded-[10px] border transition ${viewed ? "bg-navy text-white border-navy" : "bg-white border-line hover:border-line-deep text-slate"}`}>
              {viewed ? "✓" : "👁"}
            </button>
            <button onClick={onHide} title="Không OK — ẩn (x)"
              className={`flex-1 px-2 py-1.5 text-xs rounded-[10px] border transition ${hidden ? "bg-coral text-white border-coral" : "bg-white border-line hover:border-coral/60 text-slate hover:text-coral"}`}>
              ✕
            </button>
          </div>
        </div>
      </div>
    </li>
  );
}
