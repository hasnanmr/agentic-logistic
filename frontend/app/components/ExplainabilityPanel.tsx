"use client";

import { useState } from "react";
import type { Explainability, QueryStructuredRequest } from "@/lib/types";

interface ExplainabilityPanelProps {
  explainability: Explainability;
}

function isQueryRequest(request: Explainability["structured_request"]): request is QueryStructuredRequest {
  return request.operation === "query";
}

function formatFilter(request: { field: string; op: string; value: unknown }): string {
  const value = Array.isArray(request.value) ? request.value.join(", ") : String(request.value);
  return `${request.field} ${request.op} ${value}`;
}

export default function ExplainabilityPanel({ explainability }: ExplainabilityPanelProps) {
  const [open, setOpen] = useState(false);
  const { structured_request, resolved_filters, forecast_details } = explainability;
  const timeRange = resolved_filters.time_range;
  const meansLabel =
    timeRange === null
      ? null
      : timeRange.means === "history_window"
        ? "History window (learning data, not a reported period)"
        : "Reported period";

  return (
    <section className="panel explainability">
      <button
        type="button"
        className="explainability-toggle"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        {open ? "Hide" : "Show"} how this answer was produced
      </button>

      {open ? (
        <dl className="explainability-grid">
          <dt>Question</dt>
          <dd>{explainability.question}</dd>

          <dt>Metric definition</dt>
          <dd>
            {explainability.metric_definition}
            <span className="muted"> · n={explainability.metric_basis.row_count} ({explainability.metric_basis.inclusion_rule})</span>
          </dd>

          <dt>Resolved time range</dt>
          <dd>
            {timeRange === null ? (
              "All available history"
            ) : (
              <>
                {timeRange.start} to {timeRange.end} — <em>{meansLabel}</em>
              </>
            )}
          </dd>

          <dt>Filters</dt>
          <dd>
            {resolved_filters.filters.length === 0
              ? "None"
              : resolved_filters.filters.map((filter) => formatFilter(filter)).join("; ")}
          </dd>

          <dt>Query plan</dt>
          <dd>{explainability.query_plan}</dd>

          {forecast_details ? (
            <>
              <dt>Forecast horizon</dt>
              <dd>{forecast_details.horizon_weeks} weeks</dd>
              <dt>Method</dt>
              <dd>{forecast_details.method}</dd>
              <dt>History window</dt>
              <dd>
                {forecast_details.history_window.start} to {forecast_details.history_window.end} (
                {forecast_details.history_window.observations} observations)
              </dd>
              <dt>Baseline vs forecast</dt>
              <dd>
                {forecast_details.baseline_weekly_orders === null ||
                forecast_details.forecast_level === null
                  ? "N/A (insufficient history)"
                  : `${forecast_details.baseline_weekly_orders} orders/week baseline vs ${forecast_details.forecast_level} forecast`}
              </dd>
              <dt>Recommendation rule</dt>
              <dd>{forecast_details.recommendation_rule}</dd>
            </>
          ) : null}

          {isQueryRequest(structured_request) ? (
            <>
              <dt>Structured request</dt>
              <dd>
                <code>{JSON.stringify(structured_request)}</code>
              </dd>
            </>
          ) : null}
        </dl>
      ) : null}
    </section>
  );
}
