"""The agent's tools: the only path from a question to a number.

Each tool validates the model's arguments against the frozen query grammar,
runs the real computation, and files a fully composed :class:`AskResult` with
the run's collector. What goes *back* to the model is a receipt - which result
was stored and what shape it has - never the figures themselves. The agent can
therefore plan, retry and chain tool calls without a single data value entering
its context (PRD 9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from time import perf_counter
from typing import Any, Final

import pandas as pd
from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, create_model

from backend.core import answers, chart_rules
from backend.observe import langfuse as observability
from backend.tools.forecast import run_forecast
from backend.tools.query import QueryToolError, prepare, run_query
from backend.core.schemas import (
    AskResult,
    ForecastStructuredRequest,
    QueryStructuredRequest,
    RequestFilter,
    SmalltalkLanguage,
)


QUERY_TOOL: Final = "query_tool"
FORECAST_TOOL: Final = "forecast_tool"
DECLINE_TOOL: Final = "decline_tool"

_RECEIPT_GUARD: Final = (
    " The figures are computed and stored for the user; you have not been shown "
    "them, so never state a number of your own."
)

_REGION_ALIASES: Final[dict[str, frozenset[str]]] = {
    "US-E": frozenset({"us east", "east us", "eastern us", "eastern united states"}),
    "US-W": frozenset({"us west", "west us", "western us", "western united states"}),
    "US-C": frozenset({"us central", "central us", "central united states"}),
}


def _normalise_filter_text(value: object) -> str:
    """Make user phrases comparable without changing their meaning."""

    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _filter_value_was_requested(question: str, value: object) -> bool:
    text = _normalise_filter_text(question)
    candidates = {_normalise_filter_text(value)}
    candidates.update(_REGION_ALIASES.get(str(value), ()))
    return any(
        candidate
        and re.search(
            rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])", text
        )
        for candidate in candidates
    )


def validate_filters_follow_user(
    question: str, filters: list[RequestFilter]
) -> None:
    """Reject model-added filters that have no evidence in the user text.

    The schema only proves that a filter is well-formed. This second check
    proves provenance: every scalar in a filter must appear in the user's
    question. It prevents an otherwise valid but invented restriction such as
    US-E/US-W from silently changing an overall question into a regional one.
    """

    for request_filter in filters:
        values = (
            request_filter.value
            if isinstance(request_filter.value, list)
            else [request_filter.value]
        )
        missing = [
            str(value)
            for value in values
            if not _filter_value_was_requested(question, value)
        ]
        if missing:
            raise QueryToolError(
                f"filter on '{request_filter.field}' with value(s) "
                f"{', '.join(missing)} was not stated by the user; remove it "
                "unless the user explicitly requested that restriction"
            )


@dataclass
class ToolFailure:
    """A tool call that reached our code and was refused, with the reason."""

    tool: str
    reason: str


@dataclass
class RunCollector:
    """Per-request sink for everything the tools computed.

    Lives outside the graph state: it holds pandas frames and composed
    contracts that have no business being serialised into checkpoints, and one
    instance is handed to a single agent run through the runtime context.
    """

    question: str
    frame: pd.DataFrame
    results: list[AskResult] = field(default_factory=list)
    failures: list[ToolFailure] = field(default_factory=list)
    #: Set when the agent declared the dataset cannot answer the question, so
    #: a refusal can quote its reason instead of a generic one.
    decline: str | None = None
    compute_ms: float = 0.0
    #: The language the model judged the question to be written in, from the
    #: ``language`` argument every tool call carries (see ``_language_field``
    #: below). The model interprets the question either way (PRD 9), so
    #: asking it to also name the language is free - and far more reliable
    #: than a hand-built word list, which breaks on ordinary code-switched
    #: questions like "tampilkan total orders per carrier" (English field
    #: names inside an Indonesian sentence). Recorded on every call attempt,
    #: successful or rejected, so a refusal after a failed call still knows.
    language: SmalltalkLanguage = "en"

    def record(self, result: AskResult, compute_ms: float) -> int:
        """Store a computed block and return its 1-based index."""

        self.results.append(result)
        self.compute_ms += compute_ms
        return len(self.results)

    def fail(self, tool_name: str, reason: str) -> None:
        self.failures.append(ToolFailure(tool=tool_name, reason=reason))

    def declare_undecidable(self, reason: str) -> None:
        self.decline = reason.strip()

    def note_language(self, language: SmalltalkLanguage) -> None:
        self.language = language


@dataclass
class AgentContext:
    """Runtime context injected into every tool call of one agent run."""

    collector: RunCollector


#: Asked on every tool call so the composed answer can speak back in the
#: question's language. This rides in the *tool call*, not the frozen
#: StructuredRequest contract - it never reaches tools/query.py's grammar, and
#: it carries no figure, so it cannot introduce a hallucinated number; it is
#: the model doing the one thing it is already trusted to do (interpret the
#: question) instead of a hand-built classifier guessing from word lists.
def _language_field() -> Any:
    """A fresh ``Field(...)`` each call - a ``FieldInfo`` is bound to the
    model it is declared on, so the same instance cannot be reused across
    ``QueryToolArgs``, ``ForecastToolArgs`` and ``DeclineToolArgs``.

    Defaults to English rather than being required: an argument the model is
    instructed to fill in but occasionally omits should degrade to the
    existing safe default, not turn a valid, computable call into a rejected
    one over a hint field that carries no figure and changes only prose.
    """

    return Field(
        default="en",
        description=(
            "The natural language the user's own question was written in: "
            "'id' for Indonesian, 'en' for English, 'zh' for Chinese. Judge "
            "this from the user's actual wording and grammar - an English "
            "field, metric, or carrier name inside an otherwise Indonesian "
            "or Chinese sentence does not make the sentence English."
        ),
    )


def _tool_args_model(source: type[BaseModel], name: str) -> type[BaseModel]:
    """Expose a request contract as tool arguments, minus the discriminator.

    ``operation`` is injected from the tool that was called rather than asked
    for, so the model cannot pick a tool and then contradict itself in the
    arguments. ``language`` is added on top of the contract's own fields (see
    ``_language_field``).
    """

    fields: dict[str, Any] = {
        field_name: (info.annotation, info)
        for field_name, info in source.model_fields.items()
        if field_name != "operation"
    }
    fields["language"] = (SmalltalkLanguage, _language_field())
    # Extras are *not* forbidden here: the graph injects `runtime` into the
    # argument dict before this schema validates it, and a forbidding schema
    # rejects the injection itself. An unknown field is therefore dropped
    # rather than reported - harmless, because every field that reaches the
    # computation is one of these, and each is fully typed.
    return create_model(name, **fields)


QueryToolArgs = _tool_args_model(QueryStructuredRequest, "QueryToolArgs")
ForecastToolArgs = _tool_args_model(ForecastStructuredRequest, "ForecastToolArgs")


@tool(
    QUERY_TOOL,
    description=(
        "Compute a delivery metric over the order dataset, optionally broken "
        "down by a dimension, filtered, sorted, and limited. Call it once per "
        "distinct figure the question needs."
    ),
    args_schema=QueryToolArgs,
)
def query_tool(runtime: ToolRuntime, **arguments: Any) -> str:
    """Run one governed query and file the result with the run collector."""

    collector: RunCollector = runtime.context.collector
    started = perf_counter()

    language: SmalltalkLanguage = arguments.pop("language", "en")
    collector.note_language(language)

    request = QueryStructuredRequest.model_validate(
        {**arguments, "operation": "query"}
    )
    try:
        validate_filters_follow_user(collector.question, request.filters)
        result = run_query(request, collector.frame)
        resolved = prepare(request, collector.frame)
    except (QueryToolError, KeyError) as error:
        reason = str(error).strip("'")
        collector.fail(QUERY_TOOL, reason)
        # Surfaced as a tool error so the agent can correct itself; the reason
        # is also kept for the refusal the user sees if it cannot.
        raise QueryToolError(reason) from error

    # The callback handler already creates the query_tool observation, but the
    # default LangChain tool output is only the receipt below. Record the
    # governed request and the computed result on that same observation so a
    # reviewer can compare the model's call with the ground truth shown to the
    # user. Raw source rows are opt-in because they may contain sensitive
    # shipment data; the aggregate result is always recorded.
    observation_input: dict[str, Any] = {
        "request": request.model_dump(mode="json"),
        "population": {
            "row_count": int(len(resolved.frame)),
            "columns": list(resolved.frame.columns),
        },
    }
    if observability.include_query_source_rows():
        observation_input["population"]["rows"] = _json_rows(resolved.frame)
    observability.annotate_current_observation(
        input=observation_input,
        output=result.model_dump(mode="json"),
        metadata={
            "result_row_count": result.row_count,
            "result_total_groups": result.total_groups,
            "result_truncated": result.truncated,
        },
    )

    index = collector.record(
        AskResult(
            answer=answers.compose_query_answer(request, result, language),
            chart=chart_rules.select_chart(result, request.dimensions),
            table=result,
            explainability=answers.query_explainability(
                collector.question, request, result, resolved.frame
            ),
        ),
        compute_ms=(perf_counter() - started) * 1000,
    )

    breakdown = (
        f" by {', '.join(request.dimensions)}, {result.total_groups} group(s)"
        if request.dimensions
        else " as a single figure"
    )
    return f"Stored result {index}: {request.metric}{breakdown}.{_RECEIPT_GUARD}"


def _json_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Serialize filtered source rows for opt-in observability export."""

    import json

    return json.loads(frame.to_json(orient="records", date_format="iso"))


@tool(
    FORECAST_TOOL,
    description=(
        "Forecast weekly order demand between 1 and 8 weeks ahead, with a "
        "capacity recommendation."
    ),
    args_schema=ForecastToolArgs,
)
def forecast_tool(runtime: ToolRuntime, **arguments: Any) -> str:
    """Run one demand forecast and file the result with the run collector."""

    collector: RunCollector = runtime.context.collector
    started = perf_counter()

    language: SmalltalkLanguage = arguments.pop("language", "en")
    collector.note_language(language)

    request = ForecastStructuredRequest.model_validate(
        {**arguments, "operation": "forecast"}
    )
    try:
        validate_filters_follow_user(collector.question, request.filters)
        result = run_forecast(request, collector.frame)
    except (QueryToolError, KeyError) as error:
        reason = str(error).strip("'")
        collector.fail(FORECAST_TOOL, reason)
        raise QueryToolError(reason) from error

    index = collector.record(
        AskResult(
            answer=answers.compose_forecast_answer(result, language),
            chart=chart_rules.forecast_chart(result),
            table=answers.forecast_preview(result),
            explainability=answers.forecast_explainability(
                collector.question, request, result
            ),
        ),
        compute_ms=(perf_counter() - started) * 1000,
    )

    horizon = (
        "insufficient history"
        if result.insufficient_data
        else f"horizon {result.horizon_weeks} week(s)"
    )
    return f"Stored result {index}: order_demand forecast, {horizon}.{_RECEIPT_GUARD}"


class DeclineToolArgs(BaseModel):
    """Why the governed dataset cannot answer the question."""

    reason: str = Field(
        min_length=1,
        max_length=300,
        description=(
            "One sentence, in the user's own language, naming what the "
            "question asks for that this dataset does not contain, e.g. "
            "'cost per shipment is not in the data'."
        ),
    )
    language: SmalltalkLanguage = _language_field()


@tool(
    DECLINE_TOOL,
    description=(
        "Declare that the question asks for data this dataset does not hold - "
        "cost, profit, customer satisfaction, the cause of something. Call it "
        "instead of guessing, and only for questions that genuinely want data; "
        "greetings and questions about your own capabilities need no tool."
    ),
    args_schema=DeclineToolArgs,
)
def decline_tool(runtime: ToolRuntime, reason: str, language: SmalltalkLanguage = "en") -> str:
    """Record that the question is outside the dataset, with the reason.

    Made an explicit tool call rather than inferred from silence, because a
    refusal and a conversational reply are different outcomes and the model is
    the only party that knows which one it means. Recording it keeps the
    explained refusal FR-15 requires.
    """

    runtime.context.collector.note_language(language)
    runtime.context.collector.declare_undecidable(reason)
    return "Recorded that the dataset cannot answer this. Now say so to the user."


#: The governed analytical grammar: the only path from a question to a figure.
ANALYTICS_TOOLS: Final[list[BaseTool]] = [query_tool, forecast_tool]

#: Everything the agent is offered, analytics plus the explicit refusal.
AGENT_TOOLS: Final[list[BaseTool]] = [*ANALYTICS_TOOLS, decline_tool]


def tool_definitions() -> list[dict[str, Any]]:
    """The analytics tool surface in OpenAI function form.

    Covers the two governed tools only - ``decline_tool`` carries no query
    grammar, so it is not part of the surface this describes.
    """

    return [convert_to_openai_tool(analytics_tool) for analytics_tool in ANALYTICS_TOOLS]
