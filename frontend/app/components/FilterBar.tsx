"use client";

import { useEffect, useRef, useState } from "react";

import { EMPTY_FILTERS, type DashboardFilters } from "@/lib/format";
import { CalendarIcon, CheckIcon } from "./icons";

interface FilterBarProps {
  filters: DashboardFilters;
  carriers: string[];
  regions: string[];
  onChange: (filters: DashboardFilters) => void;
}

const DATASET_START = "2025-01-01";
const DATASET_END = "2025-12-30";

interface DatePreset {
  id: string;
  label: string;
  start: string;
  end: string;
}

const DATE_PRESETS: DatePreset[] = [
  { id: "all", label: "Full year (2025)", start: "", end: "" },
  { id: "last90", label: "Last 90 days of data", start: "2025-10-02", end: DATASET_END },
  { id: "last30", label: "Last 30 days of data", start: "2025-12-01", end: DATASET_END },
];

function matchPreset(filters: DashboardFilters): string | null {
  const preset = DATE_PRESETS.find((p) => p.start === filters.start && p.end === filters.end);
  return preset?.id ?? null;
}

function dateRangeLabel(filters: DashboardFilters): string {
  const presetId = matchPreset(filters);
  if (presetId) return DATE_PRESETS.find((p) => p.id === presetId)!.label;
  if (filters.start && filters.end) return `${filters.start} → ${filters.end}`;
  if (filters.start) return `From ${filters.start}`;
  if (filters.end) return `Through ${filters.end}`;
  return "Full year (2025)";
}

export default function FilterBar({ filters, carriers, regions, onChange }: FilterBarProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const activePreset = matchPreset(filters);

  const set = (patch: Partial<DashboardFilters>) => onChange({ ...filters, ...patch });

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const chips: { key: string; label: string; onRemove: () => void }[] = [];
  if (filters.start || filters.end) {
    chips.push({ key: "dates", label: dateRangeLabel(filters), onRemove: () => set({ start: "", end: "" }) });
  }
  if (filters.carrier) {
    chips.push({ key: "carrier", label: `Carrier: ${filters.carrier}`, onRemove: () => set({ carrier: "" }) });
  }
  if (filters.region) {
    chips.push({ key: "region", label: `Region: ${filters.region}`, onRemove: () => set({ region: "" }) });
  }

  return (
    <section className="panel filter-bar" aria-label="Filters">
      <div className="filter-toolbar">
        <div className="filter-field date-preset" ref={rootRef}>
          <label id="date-preset-label">Date range</label>
          <button
            type="button"
            className="date-preset-trigger"
            aria-haspopup="true"
            aria-expanded={open}
            aria-labelledby="date-preset-label"
            onClick={() => setOpen((current) => !current)}
          >
            <CalendarIcon />
            {dateRangeLabel(filters)}
          </button>
          {open ? (
            <div className="date-preset-menu" role="menu">
              {DATE_PRESETS.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={activePreset === preset.id}
                  className="date-preset-option"
                  onClick={() => {
                    set({ start: preset.start, end: preset.end });
                    setOpen(false);
                  }}
                >
                  {preset.label}
                  {activePreset === preset.id ? <CheckIcon className="date-preset-check" /> : null}
                </button>
              ))}
              <div className="date-preset-custom">
                <input
                  type="date"
                  aria-label="Custom start date"
                  min={DATASET_START}
                  max={DATASET_END}
                  value={filters.start}
                  onChange={(event) => set({ start: event.target.value })}
                />
                <input
                  type="date"
                  aria-label="Custom end date"
                  min={DATASET_START}
                  max={DATASET_END}
                  value={filters.end}
                  onChange={(event) => set({ end: event.target.value })}
                />
              </div>
            </div>
          ) : null}
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
      </div>

      {chips.length > 0 ? (
        <div className="filter-chips">
          {chips.map((chip) => (
            <span key={chip.key} className="filter-chip">
              {chip.label}
              <button
                type="button"
                className="filter-chip-remove"
                aria-label={`Remove filter: ${chip.label}`}
                onClick={chip.onRemove}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}
