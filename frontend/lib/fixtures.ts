import type { AskResponse, AskResult, MetricName, QueryResult } from "./types";

export const GROUND_TRUTH: Record<MetricName, number> = {
  total_orders: 400,
  delivered_orders: 359,
  delayed_orders: 55,
  on_time_rate: 84.68,
  delay_rate: 15.32,
  avg_delivery_time: 3.83,
  order_demand: 400,
};

// What the backend actually returns for the request below: delay_rate by
// carrier, US-E/US-W, `previous_month` - which resolves against the data's
// last order date (2025-12-30), not today, so the window is November. Kept in
// step with the real query so switching out of fixtures mode does not change
// the numbers on screen.
export const CARRIER_RESULT_FIXTURE: QueryResult = {
  columns: ["carrier", "delay_rate"],
  rows: [
    ["UPS", 50.0],
    ["USPS", 25.0],
    ["LaserShip", 0.0],
    ["FedEx", 0.0],
    ["Royal Mail", 0.0],
    ["DPD", 0.0],
  ],
  row_count: 6,
  metric: "delay_rate",
  resolved_time_range: { start: "2025-11-01", end: "2025-11-30" },
  truncated: false,
};

// The first four weeks the query tool reports, limit 4 - hence `truncated`.
// A query counts every order in a week, including the part-week the data
// opens on; only the forecast drops part-weeks, because only it needs weeks
// that are comparable with one another.
export const WEEKLY_RESULT_FIXTURE: QueryResult = {
  columns: ["week", "order_demand"],
  rows: [
    ["2025-W01", 16],
    ["2025-W02", 28],
    ["2025-W03", 15],
    ["2025-W04", 9],
  ],
  row_count: 4,
  metric: "order_demand",
  resolved_time_range: null,
  truncated: true,
};

export function fixtureQueryResult(metric: MetricName, dimensions: string[]): QueryResult {
  if (dimensions.includes("carrier")) return CARRIER_RESULT_FIXTURE;
  if (dimensions.includes("week")) return WEEKLY_RESULT_FIXTURE;
  return {
    columns: [metric],
    rows: [[GROUND_TRUTH[metric]]],
    row_count: 1,
    metric,
    resolved_time_range: null,
    truncated: false,
  };
}

const CARRIER_ASK_RESULT: AskResult = {
  answer: "UPS has the highest delay rate at 50.0%.",
  chart: {
    type: "bar",
    x: "carrier",
    y: "delay_rate",
    data: [
      { carrier: "UPS", delay_rate: 50.0 },
      { carrier: "USPS", delay_rate: 25.0 },
      { carrier: "LaserShip", delay_rate: 0.0 },
      { carrier: "FedEx", delay_rate: 0.0 },
      { carrier: "Royal Mail", delay_rate: 0.0 },
      { carrier: "DPD", delay_rate: 0.0 },
    ],
  },
  table: CARRIER_RESULT_FIXTURE,
  explainability: {
    question: "Which carrier has the highest delay rate?",
    structured_request: {
      operation: "query",
      metric: "delay_rate",
      dimensions: ["carrier"],
      filters: [{ field: "region", op: "in", value: ["US-E", "US-W"] }],
      time_range: { preset: "previous_month" },
      sort: { by: "delay_rate", direction: "desc" },
      limit: 10,
      visualization: "auto",
    },
    metric_definition: "delayed orders / delivered orders x 100 (n=359)",
    metric_basis: {
      row_count: 359,
      inclusion_rule:
        "status in (delivered, delayed); exception, in_transit and canceled excluded",
    },
    resolved_filters: {
      time_range: { start: "2025-11-01", end: "2025-11-30", means: "reported_period" },
      filters: [{ field: "region", op: "in", value: ["US-E", "US-W"] }],
    },
    query_plan:
      "filter orders -> restrict to the resolved time range -> group by carrier " +
      "-> compute delay_rate -> sort by delay_rate desc -> limit 10",
    result_preview: CARRIER_RESULT_FIXTURE,
    forecast_details: null,
    runtime: { total_ms: 1840.5, model_ms: 1712.3, compute_ms: 128.2 },
  },
};

export const ASK_RESPONSE_FIXTURE: AskResponse = {
  answer: CARRIER_ASK_RESULT.answer,
  // One block per tool call. The legacy views below mirror the first block,
  // exactly as the server computes them.
  results: [CARRIER_ASK_RESULT],
  plan: [],
  narration: "composed",
  thread_id: "ask-fixture",
  narrated: false,
  chart: CARRIER_ASK_RESULT.chart,
  table: CARRIER_ASK_RESULT.table,
  explainability: CARRIER_ASK_RESULT.explainability,
  unsupported: false,
  unsupported_reason: null,
};
