import type { Job } from "./api";
import { markJob } from "./api";
import { useEffect, useRef, useState } from "react";

// "Mới" thống nhất toàn web = ngày đăng trong 72h qua. posted_at là ước tính
// từ "đăng N ngày trước"; thiếu thì fallback first_seen.
export function isFresh(postedAt: string | null, firstSeen: string) {
  const t = new Date(postedAt || firstSeen).getTime();
  return !isNaN(t) && Date.now() - t < 72 * 3600 * 1000;
}

const SOURCE_BAR: Record<string, string> = {
  itviec: "bg-[#ff9e4a]", topcv: "bg-[#ff6b8a]", topdev: "bg-[#4cc3ff]",
};

function relTier(r: number | null) {
  if (r == null || r < 40) return { label: "", cls: "bg-edge text-faint", bar: "bg-edge", pct: 0 };
  if (r >= 70) return { label: "Rất khớp", cls: "bg-mint/15 text-mint border border-mint/40", bar: "bg-mint", pct: r };
  return { label: "Khớp", cls: "bg-violet/15 text-violet border border-violet/40", bar: "bg-violet", pct: r };
}

export default function JobTable({ jobs, loading, onChanged, listKey }: {
  jobs: Job[] | undefined; loading: boolean; onChanged?: () => void; listKey: string;
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
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [items, sel, onChanged]);

  useEffect(() => {
    rowRefs.current[sel]?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  if (loading) return (
    <div className="bg-panel border border-edge rounded-[14px] overflow-hidden divide-y divide-edge">
      {[1, 2, 3, 4].map((i) => (
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

  if (!items.length) return (
    <div className="bg-panel border border-edge rounded-[14px] px-6 py-14 text-center">
      <div className="w-10 h-10 rounded-full bg-night border border-edge flex items-center justify-center mx-auto text-faint">✓</div>
      <p className="font-semibold mt-3">Sạch rồi — không còn job nào ở mục này</p>
      <p className="text-sm text-dim mt-1">Thử nới "Khớp" xuống Tất cả, hoặc mở rộng thời gian đăng.</p>
    </div>
  );

  return (
    <ul className="bg-panel border border-edge rounded-[14px] overflow-hidden divide-y divide-edge shadow-sm">
      {items.map((j, i) => (
        <JobRow key={`${j.source}-${j.source_id}`} job={j} selected={i === sel}
          onHover={() => setSel(i)}
          rowRef={(el) => { rowRefs.current[i] = el; }}
          onOpen={() => act.current.open(j)}
          onApply={() => (j.applied ? markJob(j.source, j.source_id, { applied: 0 }).then(() => onChanged?.()) : act.current.apply(j))}
          onHide={() => markJob(j.source, j.source_id, { hidden: j.hidden ? 0 : 1 }).then(() => onChanged?.())}
          onViewed={() => markJob(j.source, j.source_id, { viewed: j.viewed ? 0 : 1 }).then(() => onChanged?.())} />
      ))}
    </ul>
  );
}

function JobRow({ job: j, selected, onHover, rowRef, onOpen, onApply, onHide, onViewed }: {
  job: Job; selected: boolean; onHover: () => void;
  rowRef: (el: HTMLLIElement | null) => void;
  onOpen: () => void; onApply: () => void; onHide: () => void; onViewed: () => void;
}) {
  const rel = relTier(j.relevance);
  const viewed = !!j.viewed;
  const applied = !!j.applied;
  const hidden = !!j.hidden;
  const matched = j.matched || [];
  const others = (j.skills || []).filter((s) => !matched.includes(s)).slice(0, 4);

  return (
    <li ref={rowRef} onMouseEnter={onHover}
      className={`relative flex gap-3 px-4 py-3.5 transition
        ${selected ? "bg-night/80 ring-1 ring-inset ring-ember/60" : "hover:bg-night/50"}
        ${applied ? "bg-mint/[0.04]" : ""} ${hidden ? "opacity-50" : ""}`}>
      <span className={`absolute left-0 top-0 bottom-0 w-1 ${selected ? "bg-ember" : SOURCE_BAR[j.source] || "bg-edge"}`} aria-hidden />
      <div className="min-w-0 flex-1">
        {/* dòng meta: điểm khớp · nguồn · thời gian · trạng thái */}
        <div className="flex items-center gap-2 font-mono text-xs text-faint flex-wrap">
          {rel.pct > 0 && (
            <span className={`px-1.5 rounded font-semibold cursor-help ${rel.cls}`}
              title={`Khớp profile CV: ${matched.join(", ")}`}>
              {rel.label} {j.relevance}
            </span>
          )}
          <span>{j.source}</span>
          <span aria-hidden>·</span>
          <span>{(j.posted_at || j.first_seen_at || "").slice(5, 10)}</span>
          {isFresh(j.posted_at, j.first_seen_at) && !applied && (
            <span className="px-1.5 rounded bg-mint text-night text-[10px] font-semibold">mới</span>
          )}
          {applied && <span className="px-1.5 rounded bg-mint text-night text-[10px] font-semibold">ĐÃ APPLY</span>}
          {viewed && !applied && <span className="px-1.5 rounded bg-edge text-faint text-[10px]">đã xem</span>}
          {hidden && <span className="px-1.5 rounded bg-red-500 text-white text-[10px]">không OK</span>}
          {j.company_bucket && <span className="hidden sm:inline">🏢 {j.company_bucket}</span>}
        </div>
        <a href={j.url} target="_blank" rel="noreferrer" onClick={onOpen}
          className={`font-semibold text-[15px] leading-snug block truncate hover:text-violet ${viewed && !applied ? "text-dim" : ""} ${applied ? "text-dim" : ""}`}>
          {j.title}
        </a>
        <div className="text-sm text-dim truncate">
          {j.company}
          {j.salary && j.salary !== "N/A" && <span className="text-mint font-mono text-[13px]"> · {j.salary}</span>}
          {(j.experience || j.level) && <span> · {j.experience || j.level}</span>}
          {j.city && <span className="hidden sm:inline"> · {j.city}</span>}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {matched.slice(0, 5).map((t) => (
            <span key={t} className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-violet/15 text-violet border border-violet/30">🎯 {t}</span>
          ))}
          {others.map((t) => (
            <span key={t} className="px-2 py-0.5 rounded-full text-[11px] text-dim border border-edge">{t}</span>
          ))}
          {j.category && <span className="px-2 py-0.5 rounded-full text-[11px] text-dim border border-edge">{j.category}</span>}
        </div>
      </div>
      {/* hành động: apply là primary */}
      <div className="shrink-0 self-center flex flex-col gap-1.5">
        {applied ? (
          <button onClick={onApply} title="Bỏ đánh dấu đã apply (a)"
            className="px-3.5 py-1.5 text-xs font-semibold rounded-[8px] bg-mint/15 text-mint border border-mint/40 hover:bg-mint/25 transition">
            ✓ Đã apply
          </button>
        ) : (
          <a href={j.url} target="_blank" rel="noreferrer" onClick={onApply}
            title="Mở job + đánh dấu đã apply (a)"
            className="px-3.5 py-1.5 text-xs font-semibold rounded-[8px] bg-gradient-to-r from-ember to-[#ff8a3c] text-white hover:brightness-110 transition text-center">
            Apply →
          </a>
        )}
        <div className="flex gap-1.5">
          <button onClick={onViewed} disabled={false}
            title="Đánh dấu đã xem (v)"
            className={`flex-1 px-2 py-1.5 text-xs rounded-[8px] border transition ${viewed ? "bg-edge text-mist border-edge" : "bg-panel border-edge hover:border-faint text-dim"}`}>
            {viewed ? "✓" : "👁"}
          </button>
          <button onClick={onHide} title="Không OK — ẩn (x)"
            className={`flex-1 px-2 py-1.5 text-xs rounded-[8px] border transition ${hidden ? "bg-red-500 text-white border-red-500" : "bg-panel border-edge hover:border-red-400 text-dim hover:text-red-400"}`}>
            ✕
          </button>
        </div>
      </div>
    </li>
  );
}
