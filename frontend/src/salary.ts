/** Parse salary text về giá trị số (triệu VND/tháng) để vẽ chart.
 *  Defaults: 1 triệu ≈ 1m VND; 1 USD ≈ 26 nghìn → 1 USD = 0.026 triệu. */
export function salaryMedian(text: string): number | null {
  if (!text) return null;
  const t = text.toLowerCase();
  const millions = t.match(/(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*(triệu|tr\b|million)/);
  if (millions) {
    return ((+millions[1] + +millions[2]) / 2) / (millions[3].startsWith("m") && millions[3] !== "million" ? 1 : 1);
  }
  const vnd = t.match(/(\d+) ?- ?(\d+) ?(triệu|tr)\b/);
  if (vnd) return (+vnd[1] + +vnd[2]) / 2;
  const usd = t.match(/\$([\d,]+)\s*[-–]\s*\$([\d,]+)/);
  if (usd) {
    const a = +usd[1].replace(/,/g, "");
    const b = +usd[2].replace(/,/g, "");
    return ((a + b) / 2) * 0.026; // USD → triệu VND
  }
  const k = t.match(/(\d+)\s*[-–]\s*(\d+)\s*(k\b|nghìn)/);
  if (k) return ((+k[1] + +k[2]) / 2) / 1000;
  return null;
}

export function salaryBucket(text: string): string | null {
  const m = salaryMedian(text);
  if (m == null) return null;
  if (m < 10) return "< 10tr";
  if (m < 20) return "10–20tr";
  if (m < 35) return "20–35tr";
  if (m < 50) return "35–50tr";
  return "≥ 50tr";
}

export const BUCKET_ORDER = ["< 10tr", "10–20tr", "20–35tr", "35–50tr", "≥ 50tr"];
