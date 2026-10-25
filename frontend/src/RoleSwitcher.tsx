import { MY_ROLES } from "./api";

// 4 hướng ứng tuyển của Huy — multi-select, chọn cả 4 = đúng phạm vi săn việc.
// Bỏ chọn hết = xem mọi ngành IT (role rỗng). Số việc lấy từ /api/meta
// (role_counts tính trên cùng bộ lọc nhưng không ràng buộc role) để badge
// luôn nói trước chọn vào sẽ được bao nhiêu việc.
export default function RoleSwitcher({ counts, value, onChange }: {
  counts?: Record<string, number>;
  value: string; // "de,backend,fullstack,ds" — rỗng = mọi ngành
  onChange: (role: string) => void;
}) {
  const selected = new Set(value.split(",").map(s => s.trim()).filter(Boolean));
  const toggle = (slug: string) => {
    const next = new Set(selected);
    if (next.has(slug)) next.delete(slug); else next.add(slug);
    // giữ thứ tự khai báo cho ổn định URL/API
    onChange(MY_ROLES.filter(r => next.has(r.slug)).map(r => r.slug).join(","));
  };

  return (
    <section aria-label="Hướng ứng tuyển">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="font-mono text-[11px] tracking-[0.18em] text-mute font-medium">HƯỚNG ỨNG TUYỂN</h2>
        {!selected.size && (
          <button onClick={() => onChange(MY_ROLES.map(r => r.slug).join(","))}
            className="text-[13px] font-semibold text-peri hover:text-peri-deep">
            Chọn lại cả 4 hướng ✓
          </button>
        )}
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        {MY_ROLES.map((r) => {
          const active = selected.has(r.slug);
          const n = counts?.[r.slug];
          return (
            <button key={r.slug} onClick={() => toggle(r.slug)} aria-pressed={active}
              className={`group text-left rounded-2xl px-4 py-3.5 border transition-all
                ${active
                  ? "bg-navy text-white border-navy shadow-hard press-hard"
                  : "soft-card hover:border-line-deep hover:-translate-y-px"}`}>
              <div className="flex items-center justify-between gap-2">
                <span className={`font-bold text-[15px] ${active ? "text-white" : "text-ink"}`}>{r.name}</span>
                {r.main
                  ? <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-bold ${active ? "bg-sun text-ink" : "bg-amber-soft text-amber"}`}>CHÍNH</span>
                  : null}
              </div>
              <p className={`mt-0.5 text-xs ${active ? "text-white/60" : "text-mute"}`}>{r.desc}</p>
              <p className={`mt-2 font-mono text-[12px] ${active ? "text-white/80" : "text-faint"}`}>
                {n != null ? <><span className={active ? "text-sun" : "text-peri"}>{n}</span> việc đang chờ</> : "— việc"}
              </p>
            </button>
          );
        })}
      </div>
      {!selected.size && (
        <p className="mt-2 text-[13px] text-slate">
          Đang xem <strong>mọi ngành IT</strong> — không giới hạn 4 hướng ứng tuyển.
        </p>
      )}
    </section>
  );
}
