"""Turn a natural-language question into a validated tool call and an answer.

The division of labour is the point of the whole design: the model interprets
the question and picks a tool, application code computes every number. The model
never sees a row of data and never writes the figures in the answer, so a
hallucinated number has nowhere to enter (PRD 9).

Routing is the model's tool choice - ``query_tool`` versus ``forecast_tool`` -
rather than a separate classification step. ``operation`` is injected from the
chosen tool name instead of being asked for, so the model cannot pick a tool and
then contradict itself in the arguments.
"""

from __future__ import annotations

from typing import Any, Final

import pandas as pd
from pydantic import ValidationError

from backend import chart_rules
from backend.forecast import build_forecast_details, run_forecast
from backend.ingestion import get_dataset
from backend.llm import LLMClient, ToolCall
from backend.metrics import METRICS, get_metric
from backend.query_tool import QueryToolError, prepare, run_query
from backend.schemas import (
    AskResponse,
    Explainability,
    ExplainedTimeRange,
    ForecastResult,
    ForecastStructuredRequest,
    MetricBasis,
    QueryResult,
    QueryStructuredRequest,
    ResolvedFilters,
)


QUERY_TOOL: Final = "query_tool"
FORECAST_TOOL: Final = "forecast_tool"

SYSTEM_PROMPT: Final = """You convert logistics questions into one tool call.

Call query_tool for questions about what happened: counts, rates, delivery time,
trends over time, breakdowns, comparisons, and rankings.
Call forecast_tool for questions about future order demand.

Never answer from your own knowledge and never invent metrics, dimensions, or
filters outside the tool schemas. If the question cannot be expressed with the
available metrics and dimensions - for example it asks about cost, profit,
customer satisfaction, or the cause of something - do not call a tool at all.

Extract the horizon for forecasts ("the next 4 weeks" -> horizon_weeks 4); if a
forecast question gives no horizon, use 4.

When prior conversation turns are supplied, resolve follow-ups against them: a
question like "what about the second highest?" or "and last month?" refers to
the subject of the previous turn, so restate the full question to yourself as a
complete tool call. Every tool call must still be fully specified - the history
provides context for interpretation only, never defaults that override the
user's words."""

#: Follow-up context is bounded so a long chat cannot silently balloon the
#: prompt; the API layer enforces the same bound on the request shape.
MAX_HISTORY_TURNS: Final = 10

#: Reported back to the user whenever a question falls outside the grammar.
SUPPORTED_CAPABILITIES: Final = (
    "Supported metrics: "
    + ", ".join(sorted(METRICS))
    + ". Supported breakdowns: carrier, region, origin_city, destination_city, "
    "product_category, status, and time buckets (day, week, month). "
    "Demand can be forecast 1-8 weeks ahead."
)

_PERCENT_METRICS: Final[frozenset[str]] = frozenset({"on_time_rate", "delay_rate"})


def _tool_schema(model: type, name: str, description: str) -> dict[str, Any]:
    """Expose a request model as a tool, minus the redundant discriminator."""

    schema = model.model_json_schema()
    schema["properties"].pop("operation", None)
    schema["required"] = [
        field for field in schema.get("required", []) if field != "operation"
    ]
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": schema},
    }


def tool_definitions() -> list[dict[str, Any]]:
    return [
        _tool_schema(
            QueryStructuredRequest,
            QUERY_TOOL,
            "Compute a delivery metric over the order dataset, optionally broken "
            "down by a dimension, filtered, sorted, and limited.",
        ),
        _tool_schema(
            ForecastStructuredRequest,
            FORECAST_TOOL,
            "Forecast weekly order demand between 1 and 8 weeks ahead.",
        ),
    ]


def _format(metric_name: str, value: object) -> str:
    if value is None:
        return "not available"
    if metric_name in _PERCENT_METRICS:
        return f"{value}%"
    if metric_name == "avg_delivery_time":
        return f"{value} days"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _unsupported(reason: str) -> AskResponse:
    return AskResponse(
        answer="",
        chart=None,
        table=None,
        explainability=None,
        unsupported=True,
        unsupported_reason=f"{reason} {SUPPORTED_CAPABILITIES}",
    )


def _query_plan(request: QueryStructuredRequest) -> str:
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


def _compose_query_answer(
    request: QueryStructuredRequest, result: QueryResult
) -> str:
    metric = get_metric(request.metric)

    if not request.dimensions:
        return f"{metric.label} is {_format(metric.name, result.rows[0][0])}."

    if result.row_count == 0:
        return "No orders match those filters, so there is nothing to report."

    dimension = request.dimensions[0]
    leader = result.rows[0]
    if request.sort is not None and request.limit == 1:
        superlative = "highest" if request.sort.direction == "desc" else "lowest"
        return (
            f"{leader[0]} has the {superlative} {metric.label.lower()} at "
            f"{_format(metric.name, leader[-1])}."
        )

    summary = (
        f"{metric.label} by {dimension} across {result.row_count} "
        f"{'group' if result.row_count == 1 else 'groups'}."
    )
    if request.sort is not None:
        summary += (
            f" Leading: {leader[0]} at {_format(metric.name, leader[-1])}."
        )
    if result.truncated:
        summary += f" Showing the first {len(result.rows)}."
    return summary


def _compose_forecast_answer(result: ForecastResult) -> str:
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


def _forecast_preview(result: ForecastResult) -> QueryResult:
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


def _query_explainability(
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
        query_plan=_query_plan(request),
        result_preview=result,
        forecast_details=None,
    )


def _forecast_explainability(
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
            "aggregate orders per complete ISO week -> 4-week moving average -> "
            f"project {result.horizon_weeks} week(s) -> compare with the trailing "
            "baseline"
        ),
        result_preview=_forecast_preview(result),
        forecast_details=build_forecast_details(result),
    )


def _handle_query(
    question: str, arguments: dict[str, Any], frame: pd.DataFrame | None
) -> AskResponse:
    request = QueryStructuredRequest.model_validate(
        {**arguments, "operation": "query"}
    )
    result = run_query(request, frame)
    resolved = prepare(request, frame)

    return AskResponse(
        answer=_compose_query_answer(request, result),
        chart=chart_rules.select_chart(result, request.dimensions),
        table=result,
        explainability=_query_explainability(question, request, result, resolved.frame),
        unsupported=False,
        unsupported_reason=None,
    )


def _handle_forecast(
    question: str, arguments: dict[str, Any], frame: pd.DataFrame | None
) -> AskResponse:
    request = ForecastStructuredRequest.model_validate(
        {**arguments, "operation": "forecast"}
    )
    result = run_forecast(request, frame)

    return AskResponse(
        answer=_compose_forecast_answer(result),
        chart=chart_rules.forecast_chart(result),
        table=_forecast_preview(result),
        explainability=_forecast_explainability(question, request, result),
        unsupported=False,
        unsupported_reason=None,
    )


def answer_question(
    question: str,
    client: LLMClient,
    frame: pd.DataFrame | None = None,
    history: list[dict[str, str]] | None = None,
) -> AskResponse:
    """Interpret a question, run the chosen tool, and compose a grounded answer.

    Every failure mode - the model declining, arguments that break the contract,
    a request that parses but is not allowed - resolves to an explained
    unsupported response rather than a guess (FR-15).

    ``history`` is prior conversation as role/content messages (oldest first),
    used only so the model can resolve follow-up questions; it never carries
    numbers into the answer.
    """

    if not question.strip():
        return _unsupported("Ask a question about the delivery data.")

    source = get_dataset() if frame is None else frame

    # Keep only the most recent turns, oldest first. A turn is a user message
    # plus its assistant reply; drop from the front in whole turns so the model
    # never sees a reply whose question was cut.
    recent_history = (history or [])[-2 * MAX_HISTORY_TURNS:]
    if len(recent_history) % 2:
        recent_history = recent_history[1:]

    call: ToolCall | None = client.choose_tool(
        question, tool_definitions(), SYSTEM_PROMPT, history=recent_history
    )
    if call is None:
        return _unsupported(
            "That question cannot be answered from this dataset."
        )

    try:
        if call.name == QUERY_TOOL:
            return _handle_query(question, call.arguments, source)
        if call.name == FORECAST_TOOL:
            return _handle_forecast(question, call.arguments, source)
    except ValidationError as error:
        return _unsupported(
            f"The request did not match the approved query grammar "
            f"({error.error_count()} field problem(s))."
        )
    except (QueryToolError, KeyError) as error:
        return _unsupported(str(error).strip("'") + ".")

    return _unsupported(f"'{call.name}' is not an available tool.")
