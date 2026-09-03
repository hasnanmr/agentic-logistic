import type { AskResponse, MetricName, QueryResult } from "./types";

export const GROUND_TRUTH: Record<MetricName, number> = {
  total_orders: 400,
  delivered_orders: 359,
  delayed_orders: 55,
  on_time_rate: 84.68,
  delay_rate: 15.32,
  avg_delivery_time: 3.83,
  order_demand: 400,
};

export const CARRIER_RESULT_FIXTURE: QueryResult = {
  columns: ["carrier", "delay_rate"],
  rows: [
    ["FedEx", 18.2],
    ["UPS", 12.4],
    ["DHL", 11.1],
  ],
  row_count: 3,
  metric: "delay_rate",
  resolved_time_range: { start: "2025-08-01", end: "2025-08-31" },
  truncated: false,
};

export const WEEKLY_RESULT_FIXTURE: QueryResult = {
  columns: ["week", "order_demand"],
  rows: [
    ["2025-W01", 8],
    ["2025-W02", 7],
    ["2025-W03", 9],
    ["2025-W04", 6],
  ],
  row_count: 4,
  metric: "order_demand",
  resolved_time_range: { start: "2025-01-01", end: "2025-12-30" },
  truncated: false,
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

export const ASK_RESPONSE_FIXTURE: AskResponse = {
  answer: "FedEx has the highest delay rate at 18.2%.",
  chart: {
    type: "bar",
    x: "carrier",
    y: "delay_rate",
    data: [
      { carrier: "FedEx", delay_rate: 18.2 },
      { carrier: "UPS", delay_rate: 12.4 },
      { carrier: "DHL", delay_rate: 11.1 },
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
    metric_definition: "delayed orders / delivered orders x 100",
    metric_basis: {
      row_count: 359,
      inclusion_rule: "status in (delivered, delayed); exception excluded",
    },
    resolved_filters: {
      time_range: { start: "2025-08-01", end: "2025-08-31", means: "reported_period" },
      filters: [{ field: "region", op: "in", value: ["US-E", "US-W"] }],
    },
    query_plan: "group by carrier -> compute delay_rate -> sort desc -> limit 10",
    result_preview: CARRIER_RESULT_FIXTURE,
    forecast_details: null,
  },
  unsupported: false,
  unsupported_reason: null,
};
