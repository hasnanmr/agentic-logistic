import type { Scalar } from "@/lib/types";

export interface TooltipPayloadEntry {
  name?: string;
  value: Scalar;
  color?: string;
  dataKey?: string;
}

function formatValue(value: Scalar): string {
  if (value === null || value === undefined) return "N/A";
  return typeof value === "number" ? new Intl.NumberFormat("en-US").format(value) : String(value);
}

/** Shared recharts tooltip content: value leads, series name follows (see the
 * dataviz skill's interaction spec). Used by every chart so hover styling is
 * consistent across the dashboard and Ask Operations. */
export default function ChartTooltip({
  active,
  label,
  payload,
}: {
  active?: boolean;
  label?: string;
  payload?: TooltipPayloadEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const visible = payload.filter((entry) => entry.value !== null && entry.value !== undefined);
  if (visible.length === 0) return null;

  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip-label">{label}</p>
      {visible.map((entry, index) => (
        <div className="chart-tooltip-row" key={entry.dataKey ?? index}>
          <span className="chart-tooltip-key">
            <span className="chart-tooltip-swatch" style={{ background: entry.color }} />
            {entry.name}
          </span>
          <span className="chart-tooltip-value">{formatValue(entry.value)}</span>
        </div>
      ))}
    </div>
  );
}
