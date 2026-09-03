"""Frozen API contracts shared by the backend and frontend.

Keep business calculations out of this module. It validates transport shapes
and the allow-listed analytical grammar only.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import (
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
    metric: MetricName
    resolved_time_range: ResolvedTimeRange | None
    truncated: bool = False

    @model_validator(mode="after")
    def validate_tabular_shape(self) -> QueryResult:
        expected_width = len(self.columns)
        if len(self.rows) > self.row_count:
            raise ValueError("returned rows cannot exceed row_count")
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
    method: Literal["moving_average_4w"]
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
    method: Literal["moving_average_4w"]
    history_window: HistoryWindow
    baseline_weekly_orders: float | None
    forecast_level: float | None
    recommendation_rule: str
    insufficient_data: bool


class Explainability(ContractModel):
    question: str
    structured_request: StructuredRequest
    metric_definition: str
    metric_basis: MetricBasis
    resolved_filters: ResolvedFilters
    query_plan: str
    result_preview: QueryResult
    forecast_details: ForecastDetails | None = None

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


class AskResponse(ContractModel):
    answer: str
    chart: ChartSpec | None
    table: QueryResult | None
    explainability: Explainability | None
    unsupported: bool = False
    unsupported_reason: str | None = None

    @model_validator(mode="after")
    def validate_supported_shape(self) -> AskResponse:
        if self.unsupported:
            if not self.unsupported_reason:
                raise ValueError("unsupported responses require unsupported_reason")
        else:
            if self.explainability is None:
                raise ValueError("supported responses require explainability")
            if self.unsupported_reason is not None:
                raise ValueError("supported responses cannot include unsupported_reason")
        return self
