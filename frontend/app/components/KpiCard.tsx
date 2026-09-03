import type { ReactNode } from "react";

import { useCountUp } from "@/lib/useCountUp";
import type { Scalar } from "@/lib/types";

export type KpiKind = "count" | "percent" | "days";
export type KpiTone = "neutral" | "good" | "critical" | "info";

interface KpiCardProps {
  label: string;
  value: Scalar;
  kind: KpiKind;
  icon: ReactNode;
  tone?: KpiTone;
  basis?: string;
}

function formatAnimated(value: number | null, kind: KpiKind): string {
  if (value === null) return "N/A";
  if (kind === "percent") return `${value.toFixed(2)}%`;
  if (kind === "days") return `${value.toFixed(2)} days`;
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

export default function KpiCard({ label, value, kind, icon, tone = "neutral", basis }: KpiCardProps) {
  const numeric = value === null ? null : Number(value);
  const animated = useCountUp(numeric);
  const toneClass = tone === "neutral" ? "" : ` kpi-card--${tone}`;

  return (
    <article className={`kpi-card${toneClass}`}>
      <div className="kpi-top">
        <h3 className="kpi-label">{label}</h3>
        <span className="kpi-icon" aria-hidden="true">
          {icon}
        </span>
      </div>
      <p className="kpi-value">{formatAnimated(animated, kind)}</p>
      {basis ? <p className="kpi-basis">{basis}</p> : null}
    </article>
  );
}
