interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className = "" }: SkeletonProps) {
  return <div className={`skeleton ${className}`} />;
}

export function KpiSkeletonRow({ count = 6 }: { count?: number }) {
  return (
    <section className="kpi-grid" aria-hidden="true">
      {Array.from({ length: count }).map((_, index) => (
        <Skeleton key={index} className="skeleton-kpi" />
      ))}
    </section>
  );
}

export function ChartSkeleton() {
  return <Skeleton className="skeleton-chart" />;
}
