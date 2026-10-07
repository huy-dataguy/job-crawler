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
  relevance: number | null;
  matched: string[];
  first_seen_at: string;
  last_seen_at: string;
  is_new: number;
  viewed: number;
  hidden: number;
  applied: number;
  company_size_raw: string | null;
  company_bucket: string | null;
  company_num_employees: string | null;
};

export type Stats = {
  total: number;
  active: number;
  new_24h: number;
  companies: number;
  top_exp: { experience: string; n: number }[];
  top_categories: { category: string; n: number }[];
  topcv_top_exp: { experience: string; n: number }[];
  itviec_top_categories: { category: string; n: number }[];
  queue?: { unseen: number; viewed: number; applied: number; hidden: number };
  generated_at: string;
};

export type MarkState = "unseen" | "viewed" | "applied" | "hidden" | "all";

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
  sort: string;
  show_hidden: number;
  company_size: string;
  relevance_min: number;
  mark: MarkState;
  company: string;
};

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

export function filterParams(f: Filters): string {
  const p = new URLSearchParams();
  p.set("it_only", String(f.it_only ?? 1));
  p.set("since_hours", String(f.since_hours || "0"));
  p.set("salary_min", String(f.salary_min || "0"));
  p.set("show_hidden", String(f.show_hidden ?? 0));
  if ((f as any).company_size) p.set("company_size", (f as any).company_size);
  if (f.sort && f.sort !== "auto") p.set("sort", f.sort);
  if (f.relevance_min) p.set("relevance_min", String(f.relevance_min));
  if (f.mark && f.mark !== "all") p.set("mark", f.mark);
  if ((f as any).company) p.set("company", (f as any).company);
  for (const [k, v] of Object.entries(f)) {
    if (["it_only", "since_hours", "salary_min", "sort", "show_hidden", "company_size",
         "relevance_min", "mark", "company"].includes(k)) continue;
    if (v) p.set(k, String(v));
  }
  return p.toString();
}

export const fetchMeta = (f: Filters) => get<Meta>("/api/meta?" + filterParams(f));

export const fetchStats = (f: Filters) =>
  get<Stats>("/api/stats?" + filterParams(f));

export const fetchTrend = (f: Filters) =>
  get<{ sources: string[]; days: any[] }>("/api/trend?days=14&" + filterParams(f));

export function fetchJobs(f: Filters, page: number) {
  const p = new URLSearchParams(filterParams(f));
  p.set("offset", String((page - 1) * 50));
  p.set("limit", "50");
  return get<{ total: number; jobs: Job[] }>("/api/jobs?" + p.toString());
}

export async function markJob(source: string, source_id: string, patch: { viewed?: number; hidden?: number; applied?: number }) {
  const r = await fetch("/api/mark", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, source_id, ...patch }),
  });
  if (!r.ok) throw new Error(`${r.status} /api/mark`);
  return r.json();
}
