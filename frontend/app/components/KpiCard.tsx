interface KpiCardProps {
  label: string;
  value: string;
  basis?: string;
}

export default function KpiCard({ label, value, basis }: KpiCardProps) {
  return (
    <article className="kpi-card">
      <h3 className="kpi-label">{label}</h3>
      <p className="kpi-value">{value}</p>
      {basis ? <p className="kpi-basis">{basis}</p> : null}
    </article>
  );
}
