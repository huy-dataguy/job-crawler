import { useMemo } from "react";
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis, Area, AreaChart,
} from "recharts";
import type { Job } from "./api";
import { useT } from "./i18n";
import { BUCKET_ORDER, salaryBucket } from "./salary";

const SOURCE_COLORS: Record<string, string> = {
  itviec: "#f97316", topcv: "#ec4899", topdev: "#0ea5e9",
};
const FALLBACK_COLORS = ["#5566ff", "#0da678", "#f59e0b", "#1d2249"];
const GRID = "#e1e4f3";
const TICK = { fontSize: 11, fill: "#9aa0bf" };
const TOOLTIP = {
  background: "#ffffff", border: "1px solid #e1e4f3", borderRadius: 12,
  color: "#181c40", fontSize: 12, boxShadow: "0 12px 32px -18px rgba(24,28,64,0.35)",
};

export function TrendChart({ trend }: { trend: { sources: string[]; days: any[] } | undefined }) {
  const t = useT();
  const sources = trend?.sources || [];
  const data = trend?.days || [];
  return (
    <Panel title="Việc mới đăng theo ngày (14 ngày, ước tính từ 'đăng N ngày trước')">
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={GRID} />
          <XAxis dataKey="date" tick={TICK} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis tick={TICK} allowDecimals={false} />
          <Tooltip contentStyle={TOOLTIP} />
          <Legend wrapperStyle={{ fontSize: 12, color: "#474d74" }} />
          {sources.map((s, i) => (
            <Bar key={s} isAnimationActive={false} dataKey={s} stackId="s" name={s}
                 fill={SOURCE_COLORS[s] || FALLBACK_COLORS[i % FALLBACK_COLORS.length]} radius={[3, 3, 0, 0]} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function CategoryChart({ stats }: { stats: {
  top_categories: { category: string; n: number }[]
} | undefined }) {
  const t = useT();
  const data = (stats?.top_categories || []).slice(0, 12).map((c) => ({ name: c.category, n: c.n }));
  return (
    <Panel title="Top ngành / category">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} layout="vertical" margin={{ left: 80 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={GRID} />
          <XAxis type="number" allowDecimals={false} tick={TICK} />
          <YAxis type="category" dataKey="name" tick={TICK} width={120} />
          <Tooltip contentStyle={TOOLTIP} />
          <Bar isAnimationActive={false} dataKey="n" name={t("jobs")} fill="#5566ff" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function ExperienceChart({ stats, onPick }: { stats: {
  top_exp?: { experience: string; n: number }[];
  topcv_top_exp: { experience: string; n: number }[]
} | undefined; onPick: (name: string) => void }) {
  const t = useT();
  const data = stats?.top_exp || stats?.topcv_top_exp || [];
  return (
    <Panel title="Năm kinh nghiệm — click để lọc">
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} onClick={(s: any) => s?.activeLabel && onPick(s.activeLabel)}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={GRID} />
          <XAxis dataKey="experience" tick={TICK} />
          <YAxis allowDecimals={false} tick={TICK} />
          <Tooltip contentStyle={TOOLTIP} />
          <Bar isAnimationActive={false} dataKey="n" name={t("jobs")} fill="#1d2249" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function SalaryChart({ jobs }: { jobs: Job[] }) {
  const t = useT();
  const data = useMemo(() => {
    const buckets = new Map<string, number>(BUCKET_ORDER.map((b) => [b, 0]));
    for (const j of jobs) {
      const b = salaryBucket(j.salary);
      if (b) buckets.set(b, (buckets.get(b) || 0) + 1);
    }
    return BUCKET_ORDER.map((b) => ({ range: b, n: buckets.get(b) || 0 }));
  }, [jobs]);
  return (
    <Panel title="Phân bố lương (triệu VND/tháng, ước tính từ lương công khai)">
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={GRID} />
          <XAxis dataKey="range" tick={TICK} />
          <YAxis tick={TICK} allowDecimals={false} />
          <Tooltip contentStyle={TOOLTIP} />
          <Area isAnimationActive={false} dataKey="n" name={t("jobs")} stroke="#0da678" fill="#0da67822" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="soft-card rounded-2xl p-4">
      <h3 className="font-mono text-[11px] uppercase tracking-wider text-faint mb-3">{title}</h3>
      {children}
    </div>
  );
}
