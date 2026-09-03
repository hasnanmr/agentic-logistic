"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec, Scalar } from "@/lib/types";

interface AskChartProps {
  chart: ChartSpec;
}

const PALETTE = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2"];

/** The field `chart_rules.forecast_chart` uses to label each point. */
const SERIES_FIELD = "series";
const ACTUAL_COLOR = "#2563eb";
const FORECAST_COLOR = "#f59e0b";

type ForecastPoint = Record<string, Scalar>;

/** True when every point carries an actual/forecast label, i.e. a forecast. */
function isForecastSeries(data: ForecastPoint[]): boolean {
  return (
    data.length > 0 &&
    data.every(
      (point) => point[SERIES_FIELD] === "actual" || point[SERIES_FIELD] === "forecast",
    )
  );
}

/**
 * Split one labelled series into two dataKeys so the projection can be drawn
 * dashed while the history stays solid. The final observed point is copied into
 * the forecast key as well, otherwise the two lines render with a visible gap
 * between them instead of the projection continuing from where data ends.
 */
function splitForecast(data: ForecastPoint[], valueKey: string): ForecastPoint[] {
  const rows = data.map((point) => ({
    ...point,
    actual: point[SERIES_FIELD] === "actual" ? point[valueKey] : null,
    forecast: point[SERIES_FIELD] === "forecast" ? point[valueKey] : null,
  }));

  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (rows[index].actual !== null) {
      rows[index].forecast = rows[index].actual;
      break;
    }
  }

  return rows;
}

export default function AskChart({ chart }: AskChartProps) {
  const seriesKeys = Array.isArray(chart.y) ? chart.y : [chart.y];
  const valueKey = seriesKeys[0];
  const forecastMode = chart.type === "line" && isForecastSeries(chart.data);
  const lineData = forecastMode ? splitForecast(chart.data, valueKey) : chart.data;

  return (
    <div className="chart-container">
      <ResponsiveContainer width="100%" height={280}>
        {chart.type === "line" ? (
          <LineChart data={lineData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey={chart.x} tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip />
            {/* Recharts reads its children to build the chart, so these stay
                as a flat list rather than a wrapping fragment. */}
            {forecastMode ? <Legend /> : null}
            {forecastMode ? (
              [
                <Line
                  key="actual"
                  name="Actual"
                  type="monotone"
                  dataKey="actual"
                  stroke={ACTUAL_COLOR}
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                />,
                <Line
                  key="forecast"
                  name="Forecast"
                  type="monotone"
                  dataKey="forecast"
                  stroke={FORECAST_COLOR}
                  strokeWidth={2}
                  strokeDasharray="5 4"
                  dot={{ r: 3, fill: FORECAST_COLOR }}
                  connectNulls={false}
                />,
              ]
            ) : (
              seriesKeys.map((key, index) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={PALETTE[index % PALETTE.length]}
                  strokeWidth={2}
                  dot={false}
                />
              ))
            )}
          </LineChart>
        ) : (
          <BarChart data={chart.data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey={chart.x} tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip />
            {seriesKeys.map((key, index) => (
              <Bar
                key={key}
                dataKey={key}
                fill={PALETTE[index % PALETTE.length]}
                radius={[4, 4, 0, 0]}
              />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

export function chartValue(data: Record<string, Scalar>, key: string): Scalar {
  return data[key] ?? null;
}
