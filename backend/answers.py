"""Composition of grounded answers, explainability, and previews.

Split out of the orchestrator so both the agent's tools and the orchestrator
can compose from the same code. Everything here is pure: it turns a validated
request plus a computed result into prose and an explainability payload, and it
is the *only* place answer text is written. The model never writes a figure, so
a hallucinated number has nowhere to enter (PRD 9).
"""

from __future__ import annotations

from typing import Final

import pandas as pd

from backend.forecast import build_forecast_details
from backend.metrics import METRICS, get_metric
from backend.schemas import (
    Explainability,
    ExplainedTimeRange,
    ForecastResult,
    ForecastStructuredRequest,
    MetricBasis,
    QueryResult,
    QueryStructuredRequest,
    ResolvedFilters,
)


#: Reported back to the user whenever a question falls outside the grammar.
SUPPORTED_CAPABILITIES: Final = (
    "Supported metrics: "
    + ", ".join(sorted(METRICS))
    + ". Supported breakdowns: carrier, region, origin_city, destination_city, "
    "product_category, status, and time buckets (day, week, month). "
    "Demand can be forecast 1-8 weeks ahead."
)

_PERCENT_METRICS: Final[frozenset[str]] = frozenset({"on_time_rate", "delay_rate"})


def format_metric(metric_name: str, value: object) -> str:
    if value is None:
        return "not available"
    if metric_name in _PERCENT_METRICS:
        return f"{value}%"
    if metric_name == "avg_delivery_time":
        return f"{value} days"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def query_plan(request: QueryStructuredRequest) -> str:
    steps = ["filter orders"] if request.filters else []
    if request.time_range is not None:
        steps.append("restrict to the resolved time range")
    if request.dimensions:
        steps.append(f"group by {', '.join(request.dimensions)}")
    steps.append(f"compute {request.metric}")
    if request.sort is not None:
        steps.append(f"sort by {request.sort.by} {request.sort.direction}")
    if request.dimensions:
        steps.append(f"limit {request.limit}")
    return " -> ".join(steps)


def compose_query_answer(request: QueryStructuredRequest, result: QueryResult) -> str:
    metric = get_metric(request.metric)

    if not request.dimensions:
        return f"{metric.label} is {format_metric(metric.name, result.rows[0][0])}."

    if result.row_count == 0:
        return "No orders match those filters, so there is nothing to report."

    dimension = request.dimensions[0]
    leader = result.rows[0]
    if request.sort is not None and request.limit == 1:
        superlative = "highest" if request.sort.direction == "desc" else "lowest"
        return (
            f"{leader[0]} has the {superlative} {metric.label.lower()} at "
            f"{format_metric(metric.name, leader[-1])}."
        )

    summary = (
        f"{metric.label} by {dimension} across {result.row_count} "
        f"{'group' if result.row_count == 1 else 'groups'}."
    )
    if request.sort is not None:
        summary += f" Leading: {leader[0]} at {format_metric(metric.name, leader[-1])}."
    if result.truncated:
        summary += f" Showing the first {len(result.rows)}."
    return summary


def compose_forecast_answer(result: ForecastResult) -> str:
    if result.insufficient_data:
        return (
            "There is not enough history to forecast demand: "
            f"{result.insufficient_data_reason}."
        )
    level = result.recommendation.forecast_level
    weeks = result.horizon_weeks
    return (
        f"Order demand for the next {weeks} week{'s' if weeks != 1 else ''} projects "
        f"to about {level} orders per week. {result.recommendation.text}"
    )


def forecast_preview(result: ForecastResult) -> QueryResult:
    """The forecast's underlying series, as an inspectable table (FR-10)."""

    rows: list[list[object]] = [
        [point.period, point.value, "actual"] for point in result.history
    ]
    rows += [[point.period, point.value, "forecast"] for point in result.forecast]
    return QueryResult(
        columns=["period", "order_demand", "series"],
        rows=rows,
        row_count=len(rows),
        metric="order_demand",
        resolved_time_range=None,
        truncated=False,
    )


def query_explainability(
    question: str,
    request: QueryStructuredRequest,
    result: QueryResult,
    frame: pd.DataFrame,
) -> Explainability:
    metric = get_metric(request.metric)
    window = result.resolved_time_range
    return Explainability(
        question=question,
        structured_request={"operation": "query", **request.model_dump(mode="json")},
        metric_definition=metric.describe(frame),
        metric_basis=MetricBasis(
            row_count=metric.basis_count(frame), inclusion_rule=metric.inclusion_rule
        ),
        resolved_filters=ResolvedFilters(
            time_range=(
                ExplainedTimeRange(
                    start=window.start, end=window.end, means="reported_period"
                )
                if window is not None
                else None
            ),
            filters=request.filters,
        ),
        query_plan=query_plan(request),
        result_preview=result,
        forecast_details=None,
    )


def forecast_explainability(
    question: str, request: ForecastStructuredRequest, result: ForecastResult
) -> Explainability:
    return Explainability(
        question=question,
        structured_request={
            "operation": "forecast",
            **request.model_dump(mode="json"),
        },
        metric_definition=(
            "orders per complete ISO week "
            f"(n={result.history_window.observations} weeks)"
        ),
        metric_basis=MetricBasis(
            row_count=result.history_window.observations,
            inclusion_rule=(
                "complete ISO weeks only; part-weeks at either end of the data "
                "are excluded because they measure a shorter period"
            ),
        ),
        resolved_filters=ResolvedFilters(
            time_range=ExplainedTimeRange(
                start=result.history_window.start,
                end=result.history_window.end,
                means="history_window",
            ),
            filters=request.filters,
        ),
        query_plan=(
            "aggregate orders per complete ISO week -> fit a 12-week trend -> "
            f"project {result.horizon_weeks} week(s) -> compare with the trailing "
            "baseline"
        ),
        result_preview=forecast_preview(result),
        forecast_details=build_forecast_details(result),
    )
