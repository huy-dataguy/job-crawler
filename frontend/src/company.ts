// Quy mô công ty (bucket) + màu đại diện — dùng chung Inbox / FilterBar / Công ty
// để cùng 1 công ty luôn hiện cùng màu ở mọi nơi.
export const BUCKETS = ["<50", "50-100", "101-150", "151-300", "301-1000", "1000+"] as const;

export const BUCKET_COLOR: Record<string, string> = {
  "<50": "#0da678", "50-100": "#0ea5e9", "101-150": "#8b5cf6",
  "151-300": "#ec4899", "301-1000": "#f97316", "1000+": "#ee5238",
};
