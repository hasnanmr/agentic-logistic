"""Deterministic chart selection (FR-08).

Three rules in application code, not a rules engine and never the model's
choice: ``visualization: "auto"`` on a request means "apply these rules", not
"let the model decide" (NFR-03). The dashboard's own fixed charts do not consult
this at all - it exists for Ask Operations, where the result shape is not known
until the tool has run.
"""

from __future__ import annotations

from typing import Final

from backend.schemas import ChartSpec, ForecastResult, QueryResult


#: Dimensions that place a result on a time axis.
TIME_DIMENSIONS: Final[frozenset[str]] = frozenset({"order_date", "week", "month"})

FORECAST_SERIES_KEY: Final = "series"


def select_chart(result: QueryResult, dimensions: list[str]) -> ChartSpec | None:
    """Pick a chart for a query result, or None when a table serves better.

    1. a time series -> line
    2. a single category -> bar
    3. anything else (a bare scalar, or multi-dimension detail rows) -> table
    """

    if not dimensions or not result.rows:
        return None

    if len(dimensions) > 1:
        # Detail rows: a chart would have to pick one dimension to plot and
        # silently drop the rest.
        return None

    dimension = dimensions[0]
    chart_type = "line" if dimension in TIME_DIMENSIONS else "bar"
    return ChartSpec(
        type=chart_type,
        x=dimension,
        y=result.metric,
        data=[dict(zip(result.columns, row)) for row in result.rows],
    )


def forecast_chart(result: ForecastResult) -> ChartSpec | None:
    """History and projection on one line chart, each point labelled.

    The ``series`` field distinguishes the two segments so the renderer can
    style the projection differently without re-deriving where it starts.
    """

    if result.insufficient_data and not result.history:
        return None

    data = [
        {"period": point.period, "value": point.value, FORECAST_SERIES_KEY: "actual"}
        for point in result.history
    ]
    data += [
        {"period": point.period, "value": point.value, FORECAST_SERIES_KEY: "forecast"}
        for point in result.forecast
    ]
    if not data:
        return None

    return ChartSpec(type="line", x="period", y="value", data=data)
