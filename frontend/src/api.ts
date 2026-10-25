import { supabase, authToken } from "./auth";

export type Meta = {
  sources: string[];
  categories: { name: string; n: number }[];
  experience: { value: string; name: string; n: number }[];
  top_tags: { name: string; n: number }[];
  top_skills: { name: string; n: number }[];
  levels: { value: string; n: number }[];
  role_counts: Record<string, number>;
  company_sizes: { bucket: string; n: number }[];
  it_count: number;
  non_it_count: number;
};

// Vị trí một công ty đang tuyển (gom từ jobs còn mở theo category + role)
export type HiringRole = { name: string; n: number };

export type Job = {
  effective_status: "open" | "closed" | "unknown";
  status: string;
  status_reason: string | null;
  detail_checked_at: string | null;
  valid_through: string | null;
  date_source: string;
  work_mode: string | null;
  employment_type: string | null;
  company_url: string | null;
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
  starred: number;
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
  queue?: { unseen: number; viewed: number; applied: number; hidden: number; starred: number };
  generated_at: string;
};

export type MarkState = "unseen" | "viewed" | "applied" | "hidden" | "starred" | "all";

export type Filters = {
  status: "open" | "closed" | "unknown" | "all";
  city: string;
  work_mode: string;
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
  role: string; // "de,backend,fullstack,ds" — hướng ứng tuyển, rỗng = mọi ngành
};

export const MY_ROLES: { slug: string; name: string; desc: string; main?: boolean }[] = [
  { slug: "de", name: "Data Engineer", desc: "lakehouse · ETL · pipeline", main: true },
  { slug: "backend", name: "Backend", desc: "API · Node.js" },
  { slug: "fullstack", name: "Fullstack", desc: "React · Node.js" },
  { slug: "ds", name: "Data Science", desc: "ML · AI" },
];

/** fetch kèm Bearer token của phiên đăng nhập. 401 → signOut ngay để
 *  AuthGate quay về màn đăng nhập thay vì để các query chết treo. */
export async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  const token = await authToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const r = await fetch(url, { ...init, headers });
  if (r.status === 401) {
    supabase?.auth.signOut();
    throw new Error(`401 ${url}`);
  }
  return r;
}

export async function apiGet<T>(url: string): Promise<T> {
  const r = await apiFetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

async function get<T>(url: string): Promise<T> {
  return apiGet<T>(url);
}

export function filterParams(f: Filters): string {
  const p = new URLSearchParams();
  p.set("it_only", String(f.it_only ?? 1));
  p.set("since_hours", String(f.since_hours || "0"));
  p.set("salary_min", String(f.salary_min || "0"));
  p.set("show_hidden", String(f.show_hidden ?? 0));
  if (f.company_size) p.set("company_size", f.company_size);
  if (f.sort && f.sort !== "auto") p.set("sort", f.sort);
  if (f.relevance_min) p.set("relevance_min", String(f.relevance_min));
  if (f.mark && f.mark !== "all") p.set("mark", f.mark);
  if (f.company) p.set("company", f.company);
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

export async function markJob(source: string, source_id: string, patch: { viewed?: number; hidden?: number; applied?: number; starred?: number }) {
  const r = await apiFetch("/api/mark", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, source_id, ...patch }),
  });
  if (!r.ok) throw new Error(`${r.status} /api/mark`);
  return r.json();
}

/** Export CSV cần Authorization header — thẻ <a href> trực tiếp không gắn
 *  được nên tải bằng fetch rồi bung blob xuống file. */
export async function downloadCompaniesCsv(query: string | URLSearchParams) {
  const r = await apiFetch(`/api/companies/export?${query}`);
  if (!r.ok) throw new Error(`${r.status} /api/companies/export`);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "companies.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

export type Health = {
  status: string;
  generated_at: string;
  counts: {total_jobs: number; recent_open: number; company_profiles: number};
  sources: {source: string; status: string; healthy: boolean; finished_at?: string; note?: string}[];
};
export const fetchHealth = () => get<Health>("/api/health");
export const fetchLocations = () => get<{provinces: {value: string; label: string}[]}>("/api/locations");
export type JobDetail = Job & {description: string | null; requirements: string | null; benefits: string | null; application_url: string | null};
export const fetchJobDetail = (j: Job) => get<JobDetail>(`/api/job/${encodeURIComponent(j.source)}/${encodeURIComponent(j.source_id)}`);
