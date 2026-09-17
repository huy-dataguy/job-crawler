export type Meta = {
  sources: string[];
  categories: { name: string; n: number }[];
  experience: { name: string; n: number }[];
  top_tags: { name: string; n: number }[];
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
  category: string;
  tags: string[];
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
  get<{ date: string; itviec: number; topcv: number }[]>("/api/trend?days=14");

export function fetchJobs(f: Filters, page: number) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...f, page, page_size: 50 })) {
    if (k === "page_size") continue;
    if (k === "page") p.set("offset", String((page - 1) * 50));
    else if (k === "since_hours") p.set("since_hours", String(f.since_hours || "0"));
    else if (v) p.set(k, String(v));
  }
  p.set("limit", "50");
  return get<{ total: number; jobs: Job[] }>("/api/jobs?" + p.toString());
}
