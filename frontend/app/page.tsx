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

import DataTable from "./components/DataTable";
import EmptyState from "./components/EmptyState";
import FilterBar from "./components/FilterBar";
import KpiCard from "./components/KpiCard";
import { runQuery } from "@/lib/api";
import {
  buildRequestFilters,
  describeFilters,
  EMPTY_FILTERS,
  formatCount,
  formatDays,
  formatPercent,
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
}

const CHART_LIMIT = 100;

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
      ]);

      const deliveredMap = new Map(deliveredByCarrier.rows.map((row) => [String(row[0]), Number(row[1])]));
      const delayedMap = new Map(delayedByCarrier.rows.map((row) => [String(row[0]), Number(row[1])]));
      const rateMap = new Map(delayRateByCarrier.rows.map((row) => [String(row[0]), row[1]]));

      const rows: CarrierRow[] = totalByCarrier.rows.map((row) => {
        const carrier = String(row[0]);
        const total = Number(row[1]);
        const carrierDelivered = deliveredMap.get(carrier) ?? 0;
        const carrierDelayed = delayedMap.get(carrier) ?? 0;
        const rawRate = rateMap.get(carrier);
        return {
          carrier,
          total,
          delivered: carrierDelivered,
          delayed: carrierDelayed,
          delayRate: rawRate === null || rawRate === undefined ? null : Number(rawRate),
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

  const isEmpty = (kpis?.total ?? 0) === 0;

  const avgBasis =
    kpis && kpis.delivered !== null && kpis.delayed !== null && kpis.exceptionCount !== null
      ? `n=${Number(kpis.delivered) + Number(kpis.delayed) + Number(kpis.exceptionCount)}, incl. exception`
      : undefined;

  return (
    <main className="page">
      <div className="page-header">
        <h1>Operations Dashboard</h1>
        <p className="page-subtitle">Delivery performance across the full 2025 order book.</p>
      </div>

      <FilterBar filters={filters} carriers={carriers} regions={regions} onChange={setFilters} />

      {error ? <div className="error-banner">{error}</div> : null}

      {loading && !kpis ? <p className="loading">Loading metrics…</p> : null}

      {kpis ? (
        <section className="kpi-grid" aria-label="Key performance indicators">
          <KpiCard label="Total Orders" value={formatCount(kpis.total)} />
          <KpiCard label="Delivered Orders" value={formatCount(kpis.delivered)} basis="on time + delayed" />
          <KpiCard label="Delayed Orders" value={formatCount(kpis.delayed)} />
          <KpiCard label="On-Time Rate" value={formatPercent(kpis.onTimeRate)} />
          <KpiCard label="Delay Rate" value={formatPercent(kpis.delayRate)} />
          <KpiCard label="Average Delivery Time" value={formatDays(kpis.avgDeliveryTime)} basis={avgBasis} />
        </section>
      ) : null}

      {isEmpty && !loading ? (
        <EmptyState activeFilters={activeFilters} onReset={() => setFilters({ ...EMPTY_FILTERS })} />
      ) : (
        <>
          <section className="panel">
            <h2 className="panel-title">Order volume by week</h2>
            {weekly.length === 0 ? (
              <EmptyState activeFilters={activeFilters} />
            ) : (
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={280}>
                  <AreaChart data={weekly} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                    <defs>
                      <linearGradient id="volumeFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#2563eb" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="#2563eb" stopOpacity={0.05} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="week" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                    <Tooltip />
                    <Area
                      type="monotone"
                      dataKey="orders"
                      stroke="#2563eb"
                      strokeWidth={2}
                      fill="url(#volumeFill)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="panel">
            <h2 className="panel-title">On-time vs delayed by carrier</h2>
            {carrierRows.length === 0 ? (
              <EmptyState activeFilters={activeFilters} />
            ) : (
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart
                    data={carrierRows.map((row) => ({
                      carrier: row.carrier,
                      "On-time": row.delivered - row.delayed,
                      Delayed: row.delayed,
                    }))}
                    margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="carrier" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="On-time" stackId="status" fill="#16a34a" />
                    <Bar dataKey="Delayed" stackId="status" fill="#dc2626" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="panel">
            <h2 className="panel-title">Carrier performance</h2>
            {carrierRows.length === 0 ? (
              <EmptyState activeFilters={activeFilters} />
            ) : (
              <DataTable
                result={{
                  columns: ["carrier", "total_orders", "delivered_orders", "delayed_orders", "delay_rate"],
                  rows: carrierRows.map((row) => [
                    row.carrier,
                    row.total,
                    row.delivered,
                    row.delayed,
                    row.delayRate,
                  ]),
                  row_count: carrierRows.length,
                  metric: "delay_rate",
                  resolved_time_range: null,
                  truncated: false,
                }}
              />
            )}
          </section>
        </>
      )}
    </main>
  );
}
