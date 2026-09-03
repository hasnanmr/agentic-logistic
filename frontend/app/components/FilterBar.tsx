"use client";

import { EMPTY_FILTERS, type DashboardFilters } from "@/lib/format";

interface FilterBarProps {
  filters: DashboardFilters;
  carriers: string[];
  regions: string[];
  onChange: (filters: DashboardFilters) => void;
}

export default function FilterBar({ filters, carriers, regions, onChange }: FilterBarProps) {
  const set = (patch: Partial<DashboardFilters>) => onChange({ ...filters, ...patch });

  return (
    <section className="panel filter-bar" aria-label="Filters">
      <div className="filter-field">
        <label htmlFor="filter-start">From</label>
        <input
          id="filter-start"
          type="date"
          min="2025-01-01"
          max="2025-12-30"
          value={filters.start}
          onChange={(event) => set({ start: event.target.value })}
        />
      </div>
      <div className="filter-field">
        <label htmlFor="filter-end">To</label>
        <input
          id="filter-end"
          type="date"
          min="2025-01-01"
          max="2025-12-30"
          value={filters.end}
          onChange={(event) => set({ end: event.target.value })}
        />
      </div>
      <div className="filter-field">
        <label htmlFor="filter-carrier">Carrier</label>
        <select
          id="filter-carrier"
          value={filters.carrier}
          onChange={(event) => set({ carrier: event.target.value })}
        >
          <option value="">All carriers</option>
          {carriers.map((carrier) => (
            <option key={carrier} value={carrier}>
              {carrier}
            </option>
          ))}
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-region">Region</label>
        <select
          id="filter-region"
          value={filters.region}
          onChange={(event) => set({ region: event.target.value })}
        >
          <option value="">All regions</option>
          {regions.map((region) => (
            <option key={region} value={region}>
              {region}
            </option>
          ))}
        </select>
      </div>
      <button type="button" className="button-secondary" onClick={() => onChange({ ...EMPTY_FILTERS })}>
        Reset
      </button>
    </section>
  );
}
