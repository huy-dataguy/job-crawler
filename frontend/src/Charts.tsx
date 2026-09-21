import { useMemo } from "react";
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis, Area, AreaChart,
} from "recharts";
import type { Job, Meta } from "./api";
import { BUCKET_ORDER, salaryBucket } from "./salary";

const SOURCE_COLORS: Record<string, string> = {
  itviec: "#ff9e4a", topcv: "#ff6b8a", topdev: "#4cc3ff",
};
const FALLBACK_COLORS = ["#8b5cf6", "#10b981", "#f59e0b", "#6366f1"];

export function TrendChart({ trend }: { trend: { sources: string[]; days: any[] } | undefined }) {
  const sources = trend?.sources || [];
  const data = trend?.days || [];
  return (
    <Panel title="Việc mới đăng theo ngày (14 ngày, ước tính từ 'đăng N ngày trước')">
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#2a3052" />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#6f7590" }} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis tick={{ fontSize: 11, fill: "#6f7590" }} allowDecimals={false} />
          <Tooltip contentStyle={{ background: "#161a30", border: "1px solid #2a3052", borderRadius: 10, color: "#f4f5fa", fontSize: 12 }} />
          <Legend wrapperStyle={{ fontSize: 12, color: "#a7acc2" }} />
          {sources.map((s, i) => (
            <Bar key={s} isAnimationActive={false} dataKey={s} stackId="s" name={s}
                 fill={SOURCE_COLORS[s] || FALLBACK_COLORS[i % FALLBACK_COLORS.length]} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function CategoryChart({ stats }: { stats: {
  top_categories: { category: string; n: number }[]
} | undefined }) {
  const data = (stats?.top_categories || []).slice(0, 12).map((c) => ({ name: c.category, n: c.n }));
  return (
    <Panel title="Top ngành / category">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} layout="vertical" margin={{ left: 80 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#2a3052" />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: "#6f7590" }} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#6f7590" }} width={120} />
          <Tooltip contentStyle={{ background: "#161a30", border: "1px solid #2a3052", borderRadius: 10, color: "#f4f5fa", fontSize: 12 }} />
          <Bar isAnimationActive={false} dataKey="n" name="số job" fill="#a7acc2" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function ExperienceChart({ stats, onPick }: { stats: {
  top_exp?: { experience: string; n: number }[];
  topcv_top_exp: { experience: string; n: number }[]
} | undefined; onPick: (name: string) => void }) {
  const data = stats?.top_exp || stats?.topcv_top_exp || [];
  return (
    <Panel title="Năm kinh nghiệm — click để lọc">
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} onClick={(s: any) => s?.activeLabel && onPick(s.activeLabel)}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#2a3052" />
          <XAxis dataKey="experience" tick={{ fontSize: 11, fill: "#6f7590" }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#6f7590" }} />
          <Tooltip contentStyle={{ background: "#161a30", border: "1px solid #2a3052", borderRadius: 10, color: "#f4f5fa", fontSize: 12 }} />
          <Bar isAnimationActive={false} dataKey="n" name="số job" fill="#8b7cff" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function SalaryChart({ jobs }: { jobs: Job[] }) {
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
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#2a3052" />
          <XAxis dataKey="range" tick={{ fontSize: 11, fill: "#6f7590" }} />
          <YAxis tick={{ fontSize: 11, fill: "#6f7590" }} allowDecimals={false} />
          <Tooltip contentStyle={{ background: "#161a30", border: "1px solid #2a3052", borderRadius: 10, color: "#f4f5fa", fontSize: 12 }} />
          <Area isAnimationActive={false} dataKey="n" name="số job" stroke="#34d399" fill="#34d39922" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-panel border border-edge rounded-[14px] p-4 shadow-sm">
      <h3 className="font-mono text-xs text-faint mb-3">{title}</h3>
      {children}
    </div>
  );
}
