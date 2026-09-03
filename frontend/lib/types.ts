export type MetricName =
  | "total_orders"
  | "delivered_orders"
  | "delayed_orders"
  | "on_time_rate"
  | "delay_rate"
  | "avg_delivery_time"
  | "order_demand";

export type DimensionName =
  | "order_date"
  | "week"
  | "month"
  | "carrier"
  | "origin_city"
  | "destination_city"
  | "status"
  | "region"
  | "product_category";

export type FilterField =
  | "order_date"
  | "delivery_date"
  | "carrier"
  | "origin_city"
  | "destination_city"
  | "status"
  | "region"
  | "product_category";

export type FilterOperator = "eq" | "neq" | "in" | "not_in" | "gt" | "gte" | "lt" | "lte";

export type Scalar = string | number | boolean | null;

export interface RequestFilter {
  field: FilterField;
  op: FilterOperator;
  value: Scalar | Scalar[];
}

export interface PresetTimeRange {
  preset: string;
}

export interface ExplicitTimeRange {
  start: string;
  end: string;
}

export type TimeRange = PresetTimeRange | ExplicitTimeRange;

export interface SortSpec {
  by: MetricName | DimensionName;
  direction: "asc" | "desc";
}

export interface QueryStructuredRequest {
  operation: "query";
  metric: MetricName;
  dimensions?: DimensionName[];
  filters?: RequestFilter[];
  time_range?: TimeRange | null;
  sort?: SortSpec;
  limit?: number;
  visualization?: "auto";
}

export interface ResolvedTimeRange {
  start: string;
  end: string;
}

export interface QueryResult {
  columns: string[];
  rows: Scalar[][];
  row_count: number;
  metric: MetricName;
  resolved_time_range: ResolvedTimeRange | null;
  truncated: boolean;
}

export interface ChartSpec {
  type: "bar" | "line" | "column";
  x: string;
  y: string | string[];
  data: Record<string, Scalar>[];
}

export interface MetricBasis {
  row_count: number;
  inclusion_rule: string;
}

export interface ExplainedTimeRange extends ResolvedTimeRange {
  means: "reported_period" | "history_window";
}

export interface ResolvedFilters {
  time_range: ExplainedTimeRange | null;
  filters: RequestFilter[];
}

export interface HistoryWindow extends ResolvedTimeRange {
  observations: number;
}

export interface ForecastDetails {
  horizon_weeks: number;
  method: string;
  history_window: HistoryWindow;
  baseline_weekly_orders: number | null;
  forecast_level: number | null;
  recommendation_rule: string;
  insufficient_data: boolean;
}

export interface Runtime {
  total_ms: number;
  model_ms: number;
  compute_ms: number;
}

export interface Explainability {
  question: string;
  structured_request: QueryStructuredRequest | ForecastStructuredRequest;
  metric_definition: string;
  metric_basis: MetricBasis;
  resolved_filters: ResolvedFilters;
  query_plan: string;
  result_preview: QueryResult;
  forecast_details: ForecastDetails | null;
  runtime?: Runtime | null;
}

export interface ForecastStructuredRequest {
  operation: "forecast";
  metric: "order_demand";
  grain: "week";
  horizon_weeks: number;
  filters?: RequestFilter[];
  time_range?: TimeRange | null;
  visualization?: "auto";
}

export interface HistoryTurn {
  question: string;
  answer: string;
}

export interface AskResponse {
  answer: string;
  chart: ChartSpec | null;
  table: QueryResult | null;
  explainability: Explainability | null;
  unsupported: boolean;
  unsupported_reason: string | null;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
