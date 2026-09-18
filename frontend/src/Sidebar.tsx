import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import type { Filters, Meta } from "./api";

const SOURCES = ["itviec", "topcv", "topdev"];
const SINCE_OPTIONS = [
  { v: 0, label: "Toàn bộ" },
  { v: 24, label: "24 giờ" },
  { v: 72, label: "3 ngày" },
  { v: 168, label: "7 ngày" },
];

export default function Sidebar({ filters, setFilters, meta }: {
  filters: Filters;
  setFilters: (f: Filters) => void;
  meta: Meta | undefined;
}) {
  return (
    <aside className="w-full lg:w-72 shrink-0 space-y-4">
      {/* Lĩnh vực */}
      <Card title="Lĩnh vực">
        <div className="flex flex-wrap gap-1.5">
          <Chip active={filters.it_only === 1}
                onClick={() => setFilters({ ...filters, it_only: 1 })}>
            💻 IT{meta ? ` (${meta.it_count})` : ""}
          </Chip>
          <Chip active={filters.it_only === 0}
                onClick={() => setFilters({ ...filters, it_only: 0 })}>
            Tất cả{meta ? ` (${meta.it_count + meta.non_it_count})` : ""}
          </Chip>
        </div>
      </Card>

      {/* Kỹ năng IT — facet chính thay cho tags thô */}
      {meta && (
        <Card title="Kỹ năng IT (click để lọc)">
          <div className="flex flex-wrap gap-1.5 max-h-56 overflow-y-auto">
            <Chip active={!filters.skill} onClick={() => setFilters({ ...filters, skill: "" })}>Tất cả</Chip>
            {meta.top_skills.map((t) => (
              <Chip key={t.name} active={filters.skill === t.name}
                    onClick={() => setFilters({ ...filters, skill: filters.skill === t.name ? "" : t.name })}>
                {t.name} <span className="opacity-50">{t.n}</span>
              </Chip>
            ))}
          </div>
        </Card>
      )}

      {/* Level + Lương — canonical xuyên nguồn */}
      <Card title="Cấp bậc">
        <div className="flex flex-wrap gap-1.5">
          <Chip active={!filters.level} onClick={() => setFilters({ ...filters, level: "" })}>Tất cả</Chip>
          {(meta?.levels || []).filter((l) => l.n > 0).map((l) => (
            <Chip key={l.value} active={filters.level === l.value}
                  onClick={() => setFilters({ ...filters, level: filters.level === l.value ? "" : l.value })}>
              {l.value} <span className="opacity-50">{l.n}</span>
            </Chip>
          ))}
        </div>
      </Card>

      <Card title="Lương tới ít nhất (tr/tháng)">
        <div className="flex flex-wrap gap-1.5">
          {[0, 10, 20, 35, 50].map((v) => (
            <Chip key={v} active={filters.salary_min === v}
                  onClick={() => setFilters({ ...filters, salary_min: v })}>
              {v === 0 ? "Tất cả" : `≥ ${v}tr`}
            </Chip>
          ))}
        </div>
      </Card>

      {/* Source */}
      <Card title="Nguồn">
        <div className="flex flex-wrap gap-1.5">
          <Chip active={!filters.source} onClick={() => setFilters({ ...filters, source: "" })}>Tất cả</Chip>
          {SOURCES.map((s) => (
            <Chip key={s} active={filters.source === s} onClick={() => setFilters({ ...filters, source: s })}>{s}</Chip>
          ))}
        </div>
      </Card>

      {/* Thời gian */}
      <Card title="Đăng gần đây">
        <div className="flex flex-wrap gap-1.5">
          {SINCE_OPTIONS.map((o) => (
            <Chip key={o.v} active={filters.since_hours === o.v} onClick={() => setFilters({ ...filters, since_hours: o.v })}>
              {o.label}
            </Chip>
          ))}
        </div>
      </Card>

      {/* Category */}
      {meta && (
        <Card title="Ngành / category">
          <ul className="space-y-1 max-h-64 overflow-y-auto pr-1">
            <Item active={!filters.category} onClick={() => setFilters({ ...filters, category: "" })}>
              Tất cả
            </Item>
            {meta.categories.map((c) => (
              <Item key={c.name} active={filters.category === c.name}
                    onClick={() => setFilters({ ...filters, category: c.name })}>
                {c.name} <span className="text-slate-400">{c.n}</span>
              </Item>
            ))}
          </ul>
        </Card>
      )}

      {/* Experience — bucket số năm, lọc chính xác theo exp_min */}
      {meta && (
        <Card title="Năm kinh nghiệm">
          <ul className="space-y-1 max-h-52 overflow-y-auto pr-1">
            <Item active={!filters.exp} onClick={() => setFilters({ ...filters, exp: "" })}>Tất cả</Item>
            {meta.experience.map((e) => (
              <Item key={e.value} active={filters.exp === e.value}
                    onClick={() => setFilters({ ...filters, exp: e.value })}>
                {e.name} <span className="text-slate-400">{e.n}</span>
              </Item>
            ))}
          </ul>
        </Card>
      )}

      {/* Tags */}
      {meta && (
        <Card title="Tags TopCV (tham khảo)">
          <div className="flex flex-wrap gap-1.5 max-h-56 overflow-y-auto">
            <Chip active={!filters.tag} onClick={() => setFilters({ ...filters, tag: "" })}>Tất cả</Chip>
            {meta.top_tags.map((t) => (
              <Chip key={t.name} active={filters.tag === t.name}
                    onClick={() => setFilters({ ...filters, tag: filters.tag === t.name ? "" : t.name })}>
                {t.name} <span className="opacity-50">{t.n}</span>
              </Chip>
            ))}
          </div>
        </Card>
      )}
    </aside>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl shadow p-4">
      <h3 className="text-xs font-semibold uppercase text-slate-500 mb-2">{title}</h3>
      {children}
    </div>
  );
}

function Chip({ active, children, onClick }: {
  active: boolean; children: React.ReactNode; onClick: () => void;
}) {
  return (
    <button onClick={onClick}
      className={`px-2.5 py-1 rounded-full text-xs border transition
        ${active ? "bg-blue-600 text-white border-blue-600" : "bg-slate-100 text-slate-600 border-transparent hover:bg-blue-100"}`}>
      {children}
    </button>
  );
}

function Item({ active, children, onClick }: {
  active: boolean; children: React.ReactNode; onClick: () => void;
}) {
  return (
    <li>
      <button onClick={onClick}
        className={`w-full text-left text-sm px-2 py-1.5 rounded-lg flex justify-between
          ${active ? "bg-blue-50 text-blue-700 font-medium" : "hover:bg-slate-100 text-slate-600"}`}>
        {children}
      </button>
    </li>
  );
}
