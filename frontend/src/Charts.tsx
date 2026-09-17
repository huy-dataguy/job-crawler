import { useMemo } from "react";
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis, Area, AreaChart,
} from "recharts";
import type { Job, Meta } from "./api";
import { BUCKET_ORDER, salaryBucket } from "./salary";

export function TrendChart({ trend }: { trend: { date: string; itviec: number; topcv: number }[] | undefined }) {
  const data = (trend || []).map((d) => ({ ...d, total: d.itviec + d.topcv }));
  return (
    <Panel title="Từ khoá việc mới đăng theo ngày (14 ngày)">
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar isAnimationActive={false} dataKey="itviec" stackId="s" name="itviec" fill="#fb923c" />
          <Bar isAnimationActive={false} dataKey="topcv" stackId="s" name="topcv" fill="#f43f5e" />
        </ComposedChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function CategoryChart({ meta }: { meta: Meta | undefined }) {
  const data = meta?.categories.slice(0, 12) || [];
  return (
    <Panel title="Top ngành / category">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} layout="vertical" margin={{ left: 80 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={120} />
          <Tooltip />
          <Bar isAnimationActive={false} dataKey="n" name="số job" fill="#6366f1" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function ExperienceChart({ stats, onPick }: { stats: {
  topcv_top_exp: { experience: string; n: number }[]
} | undefined; onPick: (name: string) => void }) {
  const data = stats?.topcv_top_exp || [];
  return (
    <Panel title="Kinh nghiệm yêu cầu (topcv — click để lọc)">
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} onClick={(s: any) => s?.activeLabel && onPick(s.activeLabel)}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="experience" tick={{ fontSize: 11 }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
          <Tooltip />
          <Bar isAnimationActive={false} dataKey="n" name="số job" fill="#10b981" radius={[4, 4, 0, 0]} />
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
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="range" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
          <Tooltip />
          <Area isAnimationActive={false} dataKey="n" name="số job" stroke="#8b5cf6" fill="#ddd6fe" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </Panel>
  );
}

export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl shadow p-4">
      <h3 className="text-xs font-semibold uppercase text-slate-500 mb-3">{title}</h3>
      {children}
    </div>
  );
}
