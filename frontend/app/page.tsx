"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import ChartTooltip from "./components/ChartTooltip";
import DataTable from "./components/DataTable";
import EmptyState from "./components/EmptyState";
import FilterBar from "./components/FilterBar";
import KpiCard from "./components/KpiCard";
import { AlertTriangleIcon, CheckCircleIcon, ClockIcon, GaugeIcon, PackageIcon } from "./components/icons";
import { ChartSkeleton, KpiSkeletonRow, Skeleton } from "./components/Skeleton";
import { runQuery } from "@/lib/api";
import {
  buildRequestFilters,
  describeFilters,
  EMPTY_FILTERS,
  type DashboardFilters,
} from "@/lib/format";
import { ApiError, type QueryStructuredRequest, type Scalar } from "@/lib/types";

interface KpiSet {
  total: Scalar;
  delivered: Scalar;
  delayed: Scalar;
  onTimeRate: Scalar;
  delayRate: Scalar;
  avgDeliveryTime: Scalar;
  exceptionCount: Scalar;
}

interface CarrierRow {
  carrier: string;
  total: number;
  delivered: number;
  delayed: number;
  delayRate: number | null;
  onTimeRate: number | null;
  avgDeliveryTime: number | null;
}

const CHART_LIMIT = 100;

// Mirrors globals.css's status tokens - recharts renders raw SVG attributes,
// which don't reliably resolve CSS custom properties. Marks use a deeper mint
// than --brand-600 for contrast against white; see AskChart for the reasoning.
const BRAND_600 = "#0a8f52";
const STATUS_GOOD = "#0ca30c";
const STATUS_CRITICAL = "#d03b3b";
const GRIDLINE = "#ececec";
const AXIS_INK = "#999999";

function scalarQuery(metric: QueryStructuredRequest["metric"], filters: QueryStructuredRequest["filters"]): QueryStructuredRequest {
  return { operation: "query", metric, filters, limit: 1 };
}

export default function DashboardPage() {
  const [filters, setFilters] = useState<DashboardFilters>(EMPTY_FILTERS);
  const [carriers, setCarriers] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [kpis, setKpis] = useState<KpiSet | null>(null);
  const [weekly, setWeekly] = useState<{ week: string; orders: number }[]>([]);
  const [carrierRows, setCarrierRows] = useState<CarrierRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const requestFilters = useMemo(() => buildRequestFilters(filters), [filters]);
  const activeFilters = useMemo(() => describeFilters(filters), [filters]);

  useEffect(() => {
    let cancelled = false;
    async function loadOptions() {
      try {
        const [carrierResult, regionResult] = await Promise.all([
          runQuery({
            operation: "query",
            metric: "total_orders",
            dimensions: ["carrier"],
            limit: CHART_LIMIT,
          }),
          runQuery({
            operation: "query",
            metric: "total_orders",
            dimensions: ["region"],
            limit: CHART_LIMIT,
          }),
        ]);
        if (cancelled) return;
        setCarriers(carrierResult.rows.map((row) => String(row[0])));
        setRegions(regionResult.rows.map((row) => String(row[0])));
      } catch {
        if (!cancelled) setCarriers([]);
      }
    }
    void loadOptions();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [
        total,
        delivered,
        delayed,
        onTimeRate,
        delayRate,
        avgDeliveryTime,
        exceptionCount,
        weeklyResult,
        deliveredByCarrier,
        delayedByCarrier,
        delayRateByCarrier,
        totalByCarrier,
        onTimeRateByCarrier,
        avgDeliveryTimeByCarrier,
      ] = await Promise.all([
        runQuery(scalarQuery("total_orders", requestFilters)),
        runQuery(scalarQuery("delivered_orders", requestFilters)),
        runQuery(scalarQuery("delayed_orders", requestFilters)),
        runQuery(scalarQuery("on_time_rate", requestFilters)),
        runQuery(scalarQuery("delay_rate", requestFilters)),
        runQuery(scalarQuery("avg_delivery_time", requestFilters)),
        runQuery({
          operation: "query",
          metric: "total_orders",
          filters: [...requestFilters, { field: "status", op: "eq", value: "exception" }],
          limit: 1,
        }),
        runQuery({
          operation: "query",
          metric: "order_demand",
          dimensions: ["week"],
          filters: requestFilters,
          sort: { by: "week", direction: "asc" },
          limit: CHART_LIMIT,
        }),
        runQuery({
          operation: "query",
          metric: "delivered_orders",
          dimensions: ["carrier"],
          filters: requestFilters,
          limit: CHART_LIMIT,
        }),
        runQuery({
          operation: "query",
          metric: "delayed_orders",
          dimensions: ["carrier"],
          filters: requestFilters,
          limit: CHART_LIMIT,
        }),
        runQuery({
          operation: "query",
          metric: "delay_rate",
          dimensions: ["carrier"],
          filters: requestFilters,
          sort: { by: "delay_rate", direction: "desc" },
          limit: CHART_LIMIT,
        }),
        runQuery({
          operation: "query",
          metric: "total_orders",
          dimensions: ["carrier"],
          filters: requestFilters,
          limit: CHART_LIMIT,
        }),
        runQuery({
          operation: "query",
          metric: "on_time_rate",
          dimensions: ["carrier"],
          filters: requestFilters,
          limit: CHART_LIMIT,
        }),
        runQuery({
          operation: "query",
          metric: "avg_delivery_time",
          dimensions: ["carrier"],
          filters: requestFilters,
          limit: CHART_LIMIT,
        }),
      ]);

      const deliveredMap = new Map(deliveredByCarrier.rows.map((row) => [String(row[0]), Number(row[1])]));
      const delayedMap = new Map(delayedByCarrier.rows.map((row) => [String(row[0]), Number(row[1])]));
      const rateMap = new Map(delayRateByCarrier.rows.map((row) => [String(row[0]), row[1]]));
      const onTimeRateMap = new Map(onTimeRateByCarrier.rows.map((row) => [String(row[0]), row[1]]));
      const avgDeliveryTimeMap = new Map(avgDeliveryTimeByCarrier.rows.map((row) => [String(row[0]), row[1]]));

      const rows: CarrierRow[] = totalByCarrier.rows.map((row) => {
        const carrier = String(row[0]);
        const total = Number(row[1]);
        const carrierDelivered = deliveredMap.get(carrier) ?? 0;
        const carrierDelayed = delayedMap.get(carrier) ?? 0;
        const rawRate = rateMap.get(carrier);
        const rawOnTimeRate = onTimeRateMap.get(carrier);
        const rawAvgDeliveryTime = avgDeliveryTimeMap.get(carrier);
        return {
          carrier,
          total,
          delivered: carrierDelivered,
          delayed: carrierDelayed,
          delayRate: rawRate === null || rawRate === undefined ? null : Number(rawRate),
          onTimeRate: rawOnTimeRate === null || rawOnTimeRate === undefined ? null : Number(rawOnTimeRate),
          avgDeliveryTime:
            rawAvgDeliveryTime === null || rawAvgDeliveryTime === undefined ? null : Number(rawAvgDeliveryTime),
        };
      });
      rows.sort((a, b) => {
        if (a.delayRate === null) return 1;
        if (b.delayRate === null) return -1;
        return b.delayRate - a.delayRate;
      });

      setKpis({
        total: total.rows[0]?.[0] ?? null,
        delivered: delivered.rows[0]?.[0] ?? null,
        delayed: delayed.rows[0]?.[0] ?? null,
        onTimeRate: onTimeRate.rows[0]?.[0] ?? null,
        delayRate: delayRate.rows[0]?.[0] ?? null,
        avgDeliveryTime: avgDeliveryTime.rows[0]?.[0] ?? null,
        exceptionCount: exceptionCount.rows[0]?.[0] ?? null,
      });
      setWeekly(
        weeklyResult.rows.map((row) => ({ week: String(row[0]), orders: Number(row[1]) })),
      );
      setCarrierRows(rows);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong loading the dashboard.");
    } finally {
      setLoading(false);
    }
  }, [requestFilters]);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  const isFirstLoad = loading && !kpis;
  const isEmpty = (kpis?.total ?? 0) === 0;

  // `delivered` already includes delayed orders (on-time + delayed together
  // form the Delivered population - see backend/core/status_rules.py), so the
  // Average Delivery Time basis is delivered + exception, not delivered +
  // delayed + exception (that would double-count the delayed group).
  const avgBasis =
    kpis && kpis.delivered !== null && kpis.exceptionCount !== null
      ? `n=${Number(kpis.delivered) + Number(kpis.exceptionCount)}, incl. exception`
      : undefined;

  const stackedByCarrier = carrierRows.map((row) => ({
    carrier: row.carrier,
    "On-time": row.delivered - row.delayed,
    Delayed: row.delayed,
  }));

  return (
    <main className="page">
      <div className="page-header">
        <h1>Operations Dashboard</h1>
        <p className="page-subtitle">Delivery performance across the full 2025 order book.</p>
      </div>

      <FilterBar filters={filters} carriers={carriers} regions={regions} onChange={setFilters} />

      {error ? <div className="error-banner">{error}</div> : null}

      {isFirstLoad ? (
        <KpiSkeletonRow />
      ) : kpis ? (
        <section
          className="kpi-grid"
          aria-label="Key performance indicators"
          style={{ opacity: loading ? 0.6 : 1, transition: "opacity 0.2s ease" }}
        >
          <KpiCard label="Total Orders" value={kpis.total} kind="count" icon={<PackageIcon />} />
          <KpiCard
            label="Delivered Orders"
            value={kpis.delivered}
            kind="count"
            icon={<CheckCircleIcon />}
            tone="info"
            basis="on time + delayed"
          />
          <KpiCard
            label="Delayed Orders"
            value={kpis.delayed}
            kind="count"
            icon={<AlertTriangleIcon />}
            tone="critical"
          />
          <KpiCard label="On-Time Rate" value={kpis.onTimeRate} kind="percent" icon={<GaugeIcon />} tone="good" />
          <KpiCard label="Delay Rate" value={kpis.delayRate} kind="percent" icon={<GaugeIcon />} tone="critical" />
          <KpiCard
            label="Average Delivery Time"
            value={kpis.avgDeliveryTime}
            kind="days"
            icon={<ClockIcon />}
            tone="info"
            basis={avgBasis}
          />
        </section>
      ) : null}

      {isFirstLoad ? (
        <>
          <ChartSkeleton />
          <ChartSkeleton />
          <Skeleton className="skeleton-chart" />
        </>
      ) : isEmpty && !loading ? (
        <EmptyState activeFilters={activeFilters} onReset={() => setFilters({ ...EMPTY_FILTERS })} />
      ) : (
        <div style={{ opacity: loading ? 0.6 : 1, transition: "opacity 0.2s ease", display: "flex", flexDirection: "column", gap: "1.4rem" }}>
          <section className="panel">
            <div className="panel-header">
              <h2 className="panel-title">Order volume by week</h2>
              <p className="panel-hint">Hover a point for the exact count</p>
            </div>
            {weekly.length === 0 ? (
              <EmptyState activeFilters={activeFilters} />
            ) : (
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={280}>
                  <AreaChart data={weekly} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                    <defs>
                      <linearGradient id="volumeFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={BRAND_600} stopOpacity={0.28} />
                        <stop offset="100%" stopColor={BRAND_600} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={GRIDLINE} vertical={false} />
                    <XAxis
                      dataKey="week"
                      tick={{ fontSize: 11, fill: AXIS_INK }}
                      interval="preserveStartEnd"
                      axisLine={{ stroke: GRIDLINE }}
                      tickLine={false}
                    />
                    <YAxis tick={{ fontSize: 12, fill: AXIS_INK }} allowDecimals={false} axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTooltip />} cursor={{ stroke: BRAND_600, strokeWidth: 1, strokeOpacity: 0.3 }} />
                    <Area
                      name="Orders"
                      type="monotone"
                      dataKey="orders"
                      stroke={BRAND_600}
                      strokeWidth={2}
                      fill="url(#volumeFill)"
                      activeDot={{ r: 5, stroke: "#ffffff", strokeWidth: 2, fill: BRAND_600 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2 className="panel-title">On-time vs delayed by carrier</h2>
              <p className="panel-hint">Hover a segment to break it down</p>
            </div>
            {carrierRows.length === 0 ? (
              <EmptyState activeFilters={activeFilters} />
            ) : (
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={stackedByCarrier} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={GRIDLINE} vertical={false} />
                    <XAxis dataKey="carrier" tick={{ fontSize: 11, fill: AXIS_INK }} axisLine={{ stroke: GRIDLINE }} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: AXIS_INK }} allowDecimals={false} axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(75, 0, 249, 0.05)" }} />
                    <Legend
                      wrapperStyle={{ fontSize: 12, color: AXIS_INK }}
                      formatter={(value) => <span style={{ color: "var(--ink-secondary)" }}>{value}</span>}
                    />
                    <Bar dataKey="On-time" name="On-time" stackId="status" fill={STATUS_GOOD} maxBarSize={28} />
                    <Bar
                      dataKey="Delayed"
                      name="Delayed"
                      stackId="status"
                      fill={STATUS_CRITICAL}
                      radius={[4, 4, 0, 0]}
                      maxBarSize={28}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2 className="panel-title">Carrier performance</h2>
              <p className="panel-hint">Click a column to sort</p>
            </div>
            {carrierRows.length === 0 ? (
              <EmptyState activeFilters={activeFilters} />
            ) : (
              <DataTable
                result={{
                  columns: [
                    "carrier",
                    "total_orders",
                    "delivered_orders",
                    "delayed_orders",
                    "on_time_rate",
                    "delay_rate",
                    "avg_delivery_time",
                  ],
                  rows: carrierRows.map((row) => [
                    row.carrier,
                    row.total,
                    row.delivered,
                    row.delayed,
                    row.onTimeRate,
                    row.delayRate,
                    row.avgDeliveryTime,
                  ]),
                  row_count: carrierRows.length,
                  total_groups: carrierRows.length,
                  metric: "delay_rate",
                  resolved_time_range: null,
                  truncated: false,
                }}
              />
            )}
          </section>
        </div>
      )}
    </main>
  );
}
