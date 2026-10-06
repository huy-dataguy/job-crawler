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
  company_size_raw: string | null;
  company_bucket: string | null;
  company_num_employees: string | null;
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
  sort: string;
  show_hidden: number;
  company_size: string;
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
  for (const [k, v] of Object.entries(f)) {
    if (k === "it_only" || k === "since_hours" || k === "salary_min" || k === "sort" || k === "show_hidden" || k === "company_size") continue;
    if (v) p.set(k, String(v));
  }
  return p.toString();
}

export const fetchMeta = (f: Filters) => get<Meta>("/api/meta?" + filterParams(f));

export const fetchStats = (f: Filters) =>
  get<{
    total: number;
    active: number;
    new_24h: number;
    companies: number;
    top_exp: { experience: string; n: number }[];
    top_categories: { category: string; n: number }[];
    topcv_top_exp: { experience: string; n: number }[];
    itviec_top_categories: { category: string; n: number }[];
    generated_at: string;
  }>("/api/stats?" + filterParams(f));

export const fetchTrend = (f: Filters) =>
  get<{ sources: string[]; days: any[] }>("/api/trend?days=14&" + filterParams(f));

export function fetchJobs(f: Filters, page: number) {
  const p = new URLSearchParams(filterParams(f));
  p.set("offset", String((page - 1) * 50));
  p.set("limit", "50");
  return get<{ total: number; jobs: Job[] }>("/api/jobs?" + p.toString());
}

export async function markJob(source: string, source_id: string, patch: { viewed?: number; hidden?: number }) {
  const r = await fetch("/api/mark", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, source_id, ...patch }),
  });
  if (!r.ok) throw new Error(`${r.status} /api/mark`);
  return r.json();
}
