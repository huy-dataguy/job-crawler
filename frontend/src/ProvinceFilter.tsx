import { useQuery } from "@tanstack/react-query";
import { fetchLocations } from "./api";
import { useT } from "./i18n";

export default function ProvinceFilter({ value, onChange }: {
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useT();
  const locations = useQuery({
    queryKey: ["locations"], queryFn: fetchLocations, staleTime: 300_000,
  });
  return (
    <div className="flex items-center gap-2 flex-wrap text-sm">
      <label htmlFor="province-filter" className="text-mute shrink-0">{t("📍 Province / city")}</label>
      <select id="province-filter" value={value} onChange={e => onChange(e.target.value)}
        className="min-w-40 flex-1 sm:flex-none sm:min-w-52 bg-white border border-line rounded-full px-3.5 py-1.5 text-ink shadow-sm focus:outline-none focus:border-peri">
        <option value="">{t("Nationwide")}</option>
        {locations.data?.provinces.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
        <option value="__unknown__">{t("Unknown province / city")}</option>
      </select>
      {value && <button onClick={() => onChange("")} className="text-xs font-medium text-peri-deep hover:text-peri">{t("Clear filter ×")}</button>}
      {locations.isError && <span role="alert" className="text-xs text-coral">{t("Failed to load province list")}</span>}
    </div>
  );
}
