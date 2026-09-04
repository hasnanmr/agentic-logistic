"""Frozen API contracts shared by the backend and frontend.

Keep business calculations out of this module. It validates transport shapes
and the allow-listed analytical grammar only.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import (
    computed_field,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictInt,
    field_validator,
    model_validator,
)


MetricName = Literal[
    "total_orders",
    "delivered_orders",
    "delayed_orders",
    "on_time_rate",
    "delay_rate",
    "avg_delivery_time",
    "order_demand",
]
DimensionName = Literal[
    "order_date",
    "week",
    "month",
    "carrier",
    "origin_city",
    "destination_city",
    "status",
    "region",
    "product_category",
]
FilterField = Literal[
    "order_date",
    "delivery_date",
    "carrier",
    "origin_city",
    "destination_city",
    "status",
    "region",
    "product_category",
]
FilterOperator = Literal[
    "eq",
    "neq",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
]
Scalar = str | int | float | bool | date | None

#: Conversational filler the application answers from templates instead of the
#: agent - see :mod:`backend.core.smalltalk`.
SmalltalkIntent = Literal[
    "morning",
    "noon",
    "afternoon",
    "evening",
    "hello",
    "thanks",
    "farewell",
]
SmalltalkLanguage = Literal["id", "en", "zh"]


class ContractModel(BaseModel):
    """Base behavior for every frozen contract model."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PresetTimeRange(ContractModel):
    """A named time window resolved by the Query Tool."""

    preset: str = Field(
        description=(
            "previous_week, previous_month, last_N_weeks, or last_N_months"
        )
    )

    @field_validator("preset")
    @classmethod
    def validate_preset(cls, value: str) -> str:
        import re

        if value in {"previous_week", "previous_month"}:
            return value
        if re.fullmatch(r"last_[1-9][0-9]*_(weeks|months)", value):
            return value
        raise ValueError(
            "unsupported time preset; use previous_week, previous_month, "
            "last_N_weeks, or last_N_months"
        )


class ExplicitTimeRange(ContractModel):
    """Inclusive explicit time window."""

    start: date
    end: date

    @model_validator(mode="after")
    def validate_order(self) -> ExplicitTimeRange:
        if self.end < self.start:
            raise ValueError("time range end must be on or after start")
        return self


TimeRange = Union[PresetTimeRange, ExplicitTimeRange]


class RequestFilter(ContractModel):
    field: FilterField
    op: FilterOperator
    value: Scalar | list[Scalar]

    @model_validator(mode="after")
    def validate_value_shape(self) -> RequestFilter:
        is_collection_operator = self.op in {"in", "not_in"}
        if is_collection_operator and not isinstance(self.value, list):
            raise ValueError(f"operator '{self.op}' requires a list value")
        if not is_collection_operator and isinstance(self.value, list):
            raise ValueError(f"operator '{self.op}' requires a scalar value")
        if isinstance(self.value, list) and not self.value:
            raise ValueError("filter list value must not be empty")
        return self


class SortSpec(ContractModel):
    by: MetricName | DimensionName
    direction: Literal["asc", "desc"] = "asc"


class QueryStructuredRequest(ContractModel):
    operation: Literal["query"]
    metric: MetricName
    dimensions: list[DimensionName] = Field(default_factory=list)
    filters: list[RequestFilter] = Field(default_factory=list)
    time_range: TimeRange | None = None
    sort: SortSpec | None = None
    limit: Annotated[StrictInt, Field(ge=1, le=1000)] = 100
    visualization: Literal["auto"] = "auto"


class ForecastStructuredRequest(ContractModel):
    operation: Literal["forecast"]
    metric: Literal["order_demand"]
    grain: Literal["week"]
    horizon_weeks: Annotated[StrictInt, Field(ge=1, le=8)]
    filters: list[RequestFilter] = Field(default_factory=list)
    time_range: TimeRange | None = None
    visualization: Literal["auto"] = "auto"


StructuredRequestValue = Annotated[
    Union[QueryStructuredRequest, ForecastStructuredRequest],
    Field(discriminator="operation"),
]


class StructuredRequest(RootModel[StructuredRequestValue]):
    """Validated request envelope discriminated by ``operation``."""

    model_config = ConfigDict(populate_by_name=True)

    @property
    def operation(self) -> Literal["query", "forecast"]:
        return self.root.operation


class ResolvedTimeRange(ContractModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_order(self) -> ResolvedTimeRange:
        if self.end < self.start:
            raise ValueError("resolved time range end must be on or after start")
        return self


class QueryResult(ContractModel):
    columns: list[str]
    rows: list[list[Scalar]]
    row_count: Annotated[int, Field(ge=0)]
    total_groups: Annotated[int, Field(ge=0)]
    metric: MetricName
    resolved_time_range: ResolvedTimeRange | None
    truncated: bool = False

    @model_validator(mode="after")
    def validate_tabular_shape(self) -> QueryResult:
        expected_width = len(self.columns)
        if len(self.rows) != self.row_count:
            raise ValueError("row_count must equal the number of returned rows")
        if self.total_groups < self.row_count:
            raise ValueError("total_groups cannot be less than row_count")
        if self.truncated != (self.total_groups > self.row_count):
            raise ValueError(
                "truncated must indicate whether total_groups exceeds row_count"
            )
        if any(len(row) != expected_width for row in self.rows):
            raise ValueError("every row must have the same width as columns")
        return self


class ForecastPoint(ContractModel):
    period: str
    value: float


class HistoryWindow(ResolvedTimeRange):
    observations: Annotated[int, Field(ge=0)]


class ForecastRecommendation(ContractModel):
    rule: str
    baseline_weekly_orders: float
    forecast_level: float
    delta_orders_per_week: Annotated[int, Field(ge=0)]
    action: Literal["increase_capacity", "no_increase", "hold"]
    text: str


class ForecastResult(ContractModel):
    target: Literal["order_demand"]
    grain: Literal["week"]
    horizon_weeks: Annotated[StrictInt, Field(ge=1, le=8)]
    history: list[ForecastPoint]
    history_window: HistoryWindow
    forecast: list[ForecastPoint]
    method: Literal["linear_trend_12w"]
    methodology_note: str
    recommendation: ForecastRecommendation | None
    insufficient_data: bool = False
    insufficient_data_reason: str | None = None

    @model_validator(mode="after")
    def validate_sufficiency_shape(self) -> ForecastResult:
        if self.insufficient_data:
            if self.forecast or self.recommendation is not None:
                raise ValueError(
                    "insufficient-data results cannot contain forecast values or a recommendation"
                )
            if not self.insufficient_data_reason:
                raise ValueError("insufficient-data results require a reason")
        else:
            if self.recommendation is None:
                raise ValueError("sufficient-data results require a recommendation")
            if self.insufficient_data_reason is not None:
                raise ValueError("sufficient-data results cannot include an insufficiency reason")
        return self


class MetricBasis(ContractModel):
    row_count: Annotated[int, Field(ge=0)]
    inclusion_rule: str


class ExplainedTimeRange(ResolvedTimeRange):
    means: Literal["reported_period", "history_window"]


class ResolvedFilters(ContractModel):
    time_range: ExplainedTimeRange | None
    filters: list[RequestFilter] = Field(default_factory=list)


class ForecastDetails(ContractModel):
    horizon_weeks: Annotated[StrictInt, Field(ge=1, le=8)]
    method: Literal["linear_trend_12w"]
    history_window: HistoryWindow
    baseline_weekly_orders: float | None
    forecast_level: float | None
    recommendation_rule: str
    insufficient_data: bool


class Runtime(ContractModel):
    """How long the agent took to turn the question into this answer.

    Wall-clock milliseconds, split so a slow answer can be attributed: the
    model call is network-bound, the computation is our own pandas work.
    """

    total_ms: Annotated[float, Field(ge=0)]
    model_ms: Annotated[float, Field(ge=0)]
    compute_ms: Annotated[float, Field(ge=0)]


class Explainability(ContractModel):
    question: str
    structured_request: StructuredRequest
    metric_definition: str
    metric_basis: MetricBasis
    resolved_filters: ResolvedFilters
    query_plan: str
    result_preview: QueryResult
    forecast_details: ForecastDetails | None = None
    #: Absent only when a response is assembled outside the orchestrator
    #: (fixtures, older clients); the live API always fills it in.
    runtime: Runtime | None = None

    @model_validator(mode="after")
    def validate_operation_details(self) -> Explainability:
        if self.structured_request.operation == "forecast" and self.forecast_details is None:
            raise ValueError("forecast explainability requires forecast_details")
        if self.structured_request.operation == "query" and self.forecast_details is not None:
            raise ValueError("query explainability cannot include forecast_details")
        time_range = self.resolved_filters.time_range
        if time_range is not None:
            expected = (
                "history_window"
                if self.structured_request.operation == "forecast"
                else "reported_period"
            )
            if time_range.means != expected:
                raise ValueError(f"time_range.means must be '{expected}' for this operation")
        return self


class ChartSpec(ContractModel):
    type: Literal["bar", "line", "column"]
    x: str
    y: str | list[str]
    data: list[dict[str, Any]]


class AskResult(ContractModel):
    """One computed block: the figures behind a single tool call.

    A deep-agent run may call the tools more than once for a compound
    question, so an answer is a list of these rather than a single result.
    Every field is produced by application code from the dataset; ``answer``
    is composed prose about *this* block, never model output.
    """

    answer: str
    chart: ChartSpec | None
    table: QueryResult | None
    explainability: Explainability


class CarrierKnowledgeItem(ContractModel):
    """One source-backed carrier glossary entry."""

    name: str
    expanded_name: str
    description: str
    source_url: str


class CarrierKnowledge(ContractModel):
    items: list[CarrierKnowledgeItem] = Field(min_length=1)


class SmalltalkReply(ContractModel):
    """Marks an answer written from a greeting template, not computed.

    The recognised intent and language travel with it so a client can react to
    a greeting - a language-matched prompt, say - without parsing the prose.
    """

    intent: SmalltalkIntent
    language: SmalltalkLanguage


class PlanStep(ContractModel):
    """One entry of the agent's own to-do list, surfaced for the trace panel."""

    content: str
    status: Literal["pending", "in_progress", "completed"]


class AskResponse(ContractModel):
    """The Ask Operations payload.

    ``results`` is the source of truth. ``chart``, ``table`` and
    ``explainability`` are read-only views of the first result, kept so
    single-result clients need no change; new clients should read ``results``.

    Four shapes are valid, exactly one payload each: an answer backed by
    ``results``, a ``carrier_knowledge`` glossary answer, a templated
    ``smalltalk`` reply, and a ``narrated`` reply the agent wrote itself when
    no tool applied. A refusal carries a reason and no payload.
    """

    answer: str
    results: list[AskResult] = Field(default_factory=list)
    #: The agent's plan when it chose to write one; empty for direct answers.
    plan: list[PlanStep] = Field(default_factory=list)
    #: How ``answer`` was produced. "composed" means application code wrote
    #: every word; "model" means the agent's own prose passed the check that
    #: every number in it came from a tool result.
    narration: Literal["composed", "model"] = "composed"
    #: Conversation thread the run belongs to, so the next question can
    #: continue it server-side instead of replaying history.
    thread_id: str | None = None
    #: Static, source-backed answer for carrier glossary questions. These do
    #: not require an analytical result or an LLM call.
    carrier_knowledge: CarrierKnowledge | None = None
    #: Present when the question was a greeting answered from a template, so
    #: the response carries prose and nothing to explain.
    smalltalk: SmalltalkReply | None = None
    #: True when the agent answered in its own prose because the message
    #: needed no tool - a capability question the templates do not cover. The
    #: prose is printed only after passing the numeric grounding check.
    narrated: bool = False
    unsupported: bool = False
    unsupported_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def chart(self) -> ChartSpec | None:
        return self.results[0].chart if self.results else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def table(self) -> QueryResult | None:
        return self.results[0].table if self.results else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def explainability(self) -> Explainability | None:
        return self.results[0].explainability if self.results else None

    @model_validator(mode="after")
    def validate_supported_shape(self) -> AskResponse:
        if self.unsupported:
            if not self.unsupported_reason:
                raise ValueError("unsupported responses require unsupported_reason")
            if (
                self.results
                or self.carrier_knowledge is not None
                or self.smalltalk is not None
                or self.narrated
            ):
                raise ValueError(
                    "unsupported responses cannot carry results, carrier "
                    "knowledge, a smalltalk reply, or narrated prose"
                )
        else:
            payloads = (
                bool(self.results),
                self.carrier_knowledge is not None,
                self.smalltalk is not None,
                self.narrated,
            )
            if sum(payloads) != 1:
                raise ValueError(
                    "supported responses require exactly one of results, "
                    "carrier knowledge, a smalltalk reply, or narrated prose"
                )
            if self.narrated and not self.answer.strip():
                raise ValueError("a narrated reply requires an answer")
            if self.unsupported_reason is not None:
                raise ValueError("supported responses cannot include unsupported_reason")
        return self
