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
import ChartTooltip from "./ChartTooltip";
import type { ChartSpec, Scalar } from "@/lib/types";

interface AskChartProps {
  chart: ChartSpec;
}

// Mirrors the brand tokens in globals.css - recharts renders raw SVG
// attributes, which don't reliably resolve CSS custom properties. Marks use a
// deeper mint than --brand-600: #17f082 is a fill color behind near-black text
// and only reaches ~1.5:1 against white, well under the 3:1 a line or bar needs.
const BRAND_600 = "#0a8f52";
const GRIDLINE = "#ececec";
const AXIS_INK = "#999999";
// Categorical slots come from the validated dataviz order (blue, orange, aqua,
// yellow, magenta, green), assigned in sequence and never cycled or reordered -
// that ordering is what keeps adjacent pairs separable for colorblind readers
// (worst adjacent CVD dE 9.1, normal-vision 19.6). Brand mint stays reserved for
// single-series marks. Three slots sit under 3:1 on white; the table rendered
// beside every chart is the relief that rule requires.
const PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];

/** The field `chart_rules.forecast_chart` uses to label each point. */
const SERIES_FIELD = "series";

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
            <CartesianGrid strokeDasharray="3 3" stroke={GRIDLINE} vertical={false} />
            <XAxis dataKey={chart.x} tick={{ fontSize: 12, fill: AXIS_INK }} axisLine={{ stroke: GRIDLINE }} tickLine={false} />
            <YAxis tick={{ fontSize: 12, fill: AXIS_INK }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: AXIS_INK, strokeWidth: 1 }} />
            {/* Recharts reads its children to build the chart, so these stay
                as a flat list rather than a wrapping fragment. */}
            {forecastMode ? <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: AXIS_INK }} /> : null}
            {forecastMode ? (
              [
                <Line
                  key="actual"
                  name="Actual"
                  type="monotone"
                  dataKey="actual"
                  stroke={BRAND_600}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 5, stroke: "#ffffff", strokeWidth: 2 }}
                  connectNulls={false}
                />,
                <Line
                  key="forecast"
                  name="Forecast"
                  type="monotone"
                  dataKey="forecast"
                  stroke={BRAND_600}
                  strokeWidth={2}
                  strokeDasharray="5 4"
                  dot={{ r: 3, fill: BRAND_600, strokeWidth: 0 }}
                  activeDot={{ r: 5, stroke: "#ffffff", strokeWidth: 2 }}
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
                  activeDot={{ r: 5, stroke: "#ffffff", strokeWidth: 2 }}
                />
              ))
            )}
          </LineChart>
        ) : (
          <BarChart data={chart.data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRIDLINE} vertical={false} />
            <XAxis dataKey={chart.x} tick={{ fontSize: 12, fill: AXIS_INK }} axisLine={{ stroke: GRIDLINE }} tickLine={false} />
            <YAxis tick={{ fontSize: 12, fill: AXIS_INK }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(75, 0, 249, 0.06)" }} />
            {seriesKeys.map((key, index) => (
              <Bar
                key={key}
                dataKey={key}
                fill={PALETTE[index % PALETTE.length]}
                radius={[4, 4, 0, 0]}
                maxBarSize={48}
                activeBar={{ fillOpacity: 0.85 }}
              />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
