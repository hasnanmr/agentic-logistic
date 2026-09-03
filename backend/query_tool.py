"""Compile a validated StructuredRequest into pandas operations.

There is no SQL anywhere in this module, which is the point: the model emits a
structured request, never a query string, so "no raw AI-generated SQL" holds by
construction rather than by sanitisation (PRD 9.2).

Every value that reaches pandas has already passed the frozen contract in
``backend.schemas`` plus the semantic checks below, so an unknown metric,
dimension, or operator is rejected before any computation runs (FR-12).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

import pandas as pd

from backend.ingestion import get_dataset
from backend.metrics import MetricDefinition, get_metric
from backend.schemas import (
    ExplicitTimeRange,
    PresetTimeRange,
    QueryResult,
    QueryStructuredRequest,
    RequestFilter,
    ResolvedTimeRange,
)


class QueryToolError(ValueError):
    """A request that is well-formed but not semantically allowed."""


DATE_FIELDS: Final[frozenset[str]] = frozenset({"order_date", "delivery_date"})

#: Dimensions derived from ``order_date`` rather than read from a column.
TIME_BUCKETS: Final[frozenset[str]] = frozenset({"week", "month"})

_LAST_N_PRESET: Final = re.compile(r"last_(?P<count>[1-9][0-9]*)_(?P<unit>weeks|months)")


@dataclass(frozen=True)
class ResolvedQuery:
    """A query after validation and time resolution, before computation."""

    metric: MetricDefinition
    frame: pd.DataFrame
    resolved_time_range: ResolvedTimeRange | None


def dataset_anchor(frame: pd.DataFrame) -> date:
    """The 'today' that relative time presets are measured from.

    Deliberately the dataset's most recent order date, not the wall clock. The
    supplied data ends 2025-12-30, so anchoring "previous_month" to the real
    current date would resolve every relative preset to an empty window and
    make correct code look broken. The resolved dates travel back in the
    response, so the choice is visible to the caller rather than implied.
    """

    return frame["order_date"].max().date()


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _previous_month_window(anchor: date) -> tuple[date, date]:
    first_of_this_month = _month_start(anchor)
    end = first_of_this_month - timedelta(days=1)
    return _month_start(end), end


def _previous_week_window(anchor: date) -> tuple[date, date]:
    # ISO weeks start on Monday; step back into the preceding one.
    start_of_this_week = anchor - timedelta(days=anchor.weekday())
    end = start_of_this_week - timedelta(days=1)
    return end - timedelta(days=6), end


def resolve_time_range(
    time_range: PresetTimeRange | ExplicitTimeRange | None, anchor: date
) -> ResolvedTimeRange | None:
    """Turn a preset or explicit range into concrete inclusive dates."""

    if time_range is None:
        return None

    if isinstance(time_range, ExplicitTimeRange):
        return ResolvedTimeRange(start=time_range.start, end=time_range.end)

    preset = time_range.preset
    if preset == "previous_month":
        start, end = _previous_month_window(anchor)
    elif preset == "previous_week":
        start, end = _previous_week_window(anchor)
    else:
        match = _LAST_N_PRESET.fullmatch(preset)
        if match is None:  # pragma: no cover - contract validation covers this
            raise QueryToolError(f"unsupported time preset '{preset}'")
        count = int(match.group("count"))
        end = anchor
        if match.group("unit") == "weeks":
            start = end - timedelta(weeks=count) + timedelta(days=1)
        else:
            # N months *including* the anchor's own month, so last_3_months at
            # 2025-12-30 spans October-December, not September-December.
            year, month = end.year, end.month - (count - 1)
            while month <= 0:
                month += 12
                year -= 1
            start = date(year, month, 1)
    return ResolvedTimeRange(start=start, end=end)


def _apply_time_range(frame: pd.DataFrame, window: ResolvedTimeRange | None) -> pd.DataFrame:
    if window is None:
        return frame
    order_date = frame["order_date"]
    return frame[
        order_date.between(pd.Timestamp(window.start), pd.Timestamp(window.end))
    ]


def _coerce(field: str, value: object) -> object:
    if field in DATE_FIELDS:
        if isinstance(value, list):
            return [pd.Timestamp(item) for item in value]
        return pd.Timestamp(value)
    return value


def apply_filters(frame: pd.DataFrame, filters: list[RequestFilter]) -> pd.DataFrame:
    """Apply every allow-listed filter in order. Shared with the Forecast Tool."""

    for request_filter in filters:
        frame = _apply_filter(frame, request_filter)
    return frame


def _apply_filter(frame: pd.DataFrame, request_filter: RequestFilter) -> pd.DataFrame:
    series = frame[request_filter.field]
    value = _coerce(request_filter.field, request_filter.value)

    match request_filter.op:
        case "eq":
            mask = series == value
        case "neq":
            mask = series != value
        case "in":
            mask = series.isin(value)
        case "not_in":
            mask = ~series.isin(value)
        case "gt":
            mask = series > value
        case "gte":
            mask = series >= value
        case "lt":
            mask = series < value
        case "lte":
            mask = series <= value
        case _:  # pragma: no cover - contract validation covers this
            raise QueryToolError(f"unsupported operator '{request_filter.op}'")
    return frame[mask]


def _with_dimension_columns(frame: pd.DataFrame, dimensions: list[str]) -> pd.DataFrame:
    """Materialise derived time buckets so groupby can address them."""

    if not TIME_BUCKETS & set(dimensions):
        return frame

    working = frame.copy()
    if "week" in dimensions:
        iso = working["order_date"].dt.isocalendar()
        working["week"] = (
            iso["year"].astype(str) + "-W" + iso["week"].astype(int).map("{:02d}".format)
        )
    if "month" in dimensions:
        working["month"] = working["order_date"].dt.strftime("%Y-%m")
    return working


#: Operators that impose an ordering. The filter allow-list exposes no numeric
#: column, so ordering only means something on the two date fields - applying it
#: to a label like carrier would silently do a lexicographic comparison and
#: return a table that looks like data but answers nothing.
ORDERING_OPERATORS: Final[frozenset[str]] = frozenset({"gt", "gte", "lt", "lte"})


def validate_filters(filters: list[RequestFilter]) -> None:
    """Reject filters that parse but cannot mean anything (FR-12)."""

    for request_filter in filters:
        if (
            request_filter.op in ORDERING_OPERATORS
            and request_filter.field not in DATE_FIELDS
        ):
            raise QueryToolError(
                f"operator '{request_filter.op}' is only supported on date fields "
                f"({', '.join(sorted(DATE_FIELDS))}), not on '{request_filter.field}'"
            )


def _validate(request: QueryStructuredRequest, metric: MetricDefinition) -> None:
    validate_filters(request.filters)

    unapproved = [
        dimension
        for dimension in request.dimensions
        if dimension not in metric.allowed_dimensions
    ]
    if unapproved:
        raise QueryToolError(
            f"dimension(s) {', '.join(unapproved)} are not approved for metric "
            f"'{metric.name}'; approved: {', '.join(sorted(metric.allowed_dimensions))}"
        )

    if len(set(request.dimensions)) != len(request.dimensions):
        raise QueryToolError("dimensions must not repeat")

    if request.sort is not None:
        sort_key = request.sort.by
        if sort_key != metric.name and sort_key not in request.dimensions:
            raise QueryToolError(
                f"cannot sort by '{sort_key}': sort by the requested metric "
                f"('{metric.name}') or one of its dimensions"
            )


def prepare(
    request: QueryStructuredRequest, frame: pd.DataFrame | None = None
) -> ResolvedQuery:
    """Validate a request and apply its time range and filters."""

    source = get_dataset() if frame is None else frame
    metric = get_metric(request.metric)
    _validate(request, metric)

    window = resolve_time_range(request.time_range, dataset_anchor(source))
    working = apply_filters(_apply_time_range(source, window), request.filters)
    return ResolvedQuery(metric=metric, frame=working, resolved_time_range=window)


def run_query(
    request: QueryStructuredRequest, frame: pd.DataFrame | None = None
) -> QueryResult:
    """Execute a validated structured request and return tabular output."""

    resolved = prepare(request, frame)
    metric, working = resolved.metric, resolved.frame

    if not request.dimensions:
        return QueryResult(
            columns=[metric.name],
            rows=[[metric.compute(working)]],
            row_count=1,
            metric=metric.name,
            resolved_time_range=resolved.resolved_time_range,
            truncated=False,
        )

    grouped = _with_dimension_columns(working, request.dimensions)
    if grouped.empty:
        return QueryResult(
            columns=[*request.dimensions, metric.name],
            rows=[],
            row_count=0,
            metric=metric.name,
            resolved_time_range=resolved.resolved_time_range,
            truncated=False,
        )

    series = grouped.groupby(request.dimensions, sort=False, dropna=False).apply(
        metric.compute, include_groups=False
    )
    table = series.reset_index()
    table.columns = [*request.dimensions, metric.name]

    if request.sort is not None:
        table = table.sort_values(
            by=request.sort.by,
            ascending=request.sort.direction == "asc",
            na_position="last",
            kind="stable",
        )
    else:
        table = table.sort_values(by=request.dimensions, kind="stable")

    total_groups = len(table)
    truncated = total_groups > request.limit
    table = table.head(request.limit)

    return QueryResult(
        columns=list(table.columns),
        rows=[
            [_to_scalar(value) for value in row]
            for row in table.itertuples(index=False, name=None)
        ],
        row_count=total_groups,
        metric=metric.name,
        resolved_time_range=resolved.resolved_time_range,
        truncated=truncated,
    )


def _to_scalar(value: object) -> object:
    """Convert numpy/pandas values into JSON-serialisable Python scalars."""

    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, float) and pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
