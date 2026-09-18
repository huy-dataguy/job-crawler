export type Meta = {
  sources: string[];
  categories: { name: string; n: number }[];
  experience: { value: string; name: string; n: number }[];
  top_tags: { name: string; n: number }[];
  top_skills: { name: string; n: number }[];
  levels: { value: string; n: number }[];
  it_count: number;
  non_it_count: number;
};

export type Job = {
  source: string;
  source_id: string;
  title: string;
  company: string;
  url: string;
  city: string;
  salary: string;
  experience: string;
  exp_min: number | null;
  category: string;
  tags: string[];
  skills: string[];
  is_it: number;
  level: string;
  salary_min: number | null;
  salary_max: number | null;
  posted_text: string;
  posted_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  is_new: number;
};

export type Filters = {
  q: string;
  source: string;
  category: string;
  exp: string;
  tag: string;
  skill: string;
  level: string;
  salary_min: number;
  it_only: number;
  since_hours: number;
};

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

export const fetchMeta = () => get<Meta>("/api/meta");

export const fetchStats = () =>
  get<{
    total: number;
    active: number;
    new_24h: number;
    topcv_top_exp: { experience: string; n: number }[];
    itviec_top_categories: { category: string; n: number }[];
    generated_at: string;
  }>("/api/stats");

export const fetchTrend = () =>
  get<{ sources: string[]; days: any[] }>("/api/trend?days=14");

export function fetchJobs(f: Filters, page: number) {
  const p = new URLSearchParams();
  p.set("offset", String((page - 1) * 50));
  p.set("limit", "50");
  p.set("it_only", String(f.it_only ?? 1));
  p.set("since_hours", String(f.since_hours || "0"));
  p.set("salary_min", String(f.salary_min || "0"));
  for (const [k, v] of Object.entries(f)) {
    if (k === "it_only" || k === "since_hours" || k === "salary_min") continue;
    if (v) p.set(k, String(v));
  }
  return get<{ total: number; jobs: Job[] }>("/api/jobs?" + p.toString());
}
