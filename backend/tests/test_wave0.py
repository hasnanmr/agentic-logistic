"""Wave 0 contract and application smoke tests."""

import datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from backend.answers import forecast_explainability
from backend.fixtures import (
    ALL_FIXTURES,
    FORECAST_REQUEST_FIXTURE,
    QUERY_REQUEST_FIXTURE,
)
from backend.forecast import run_forecast
from backend.query_tool import run_query
from backend.main import app
from backend.schemas import StructuredRequest
from backend.schemas import ForecastResult, QueryResult


def test_all_fixtures_are_constructed_pydantic_models() -> None:
    assert set(ALL_FIXTURES) == {
        "query_request",
        "forecast_request",
        "query_result",
        "forecast_result",
        "explainability",
        "forecast_explainability",
        "ask_response",
    }
    assert all(fixture.model_dump(mode="json") for fixture in ALL_FIXTURES.values())


def _frame_from_history(result: ForecastResult) -> "pd.DataFrame":
    """Rebuild the order-level data that would produce this history."""

    rows: list[datetime.date] = []
    for point in result.history:
        year, week = point.period.split("-W")
        monday = datetime.date.fromisocalendar(int(year), int(week), 1)
        rows += [monday + datetime.timedelta(days=i % 7) for i in range(int(point.value))]
    return pd.DataFrame({"order_date": pd.to_datetime(sorted(rows))})


def test_forecast_fixture_is_what_the_engine_actually_returns() -> None:
    """Replaying the fixture's own history must reproduce the fixture.

    A fixture is a promise about the response shape. Hand-editing one half of
    it - a longer history, a sloping forecast line, a recommendation the rule
    cannot reach - makes it describe output the API never sends, and anything
    built against it is built against fiction.
    """

    fixture = ALL_FIXTURES["forecast_result"]
    replayed = run_forecast(FORECAST_REQUEST_FIXTURE.root, _frame_from_history(fixture))

    assert replayed.model_dump(mode="json") == fixture.model_dump(mode="json")


def test_forecast_explainability_fixture_is_derived_from_the_result() -> None:
    """answers.py assembles this from the result; the fixture must agree."""

    fixture = ALL_FIXTURES["forecast_explainability"]
    rebuilt = forecast_explainability(
        fixture.question,
        FORECAST_REQUEST_FIXTURE.root,
        ALL_FIXTURES["forecast_result"],
    )

    assert rebuilt.model_dump(mode="json") == fixture.model_dump(mode="json")


def test_forecast_fixture_history_and_horizon_do_not_overlap() -> None:
    """Stated separately from the round-trip so a failure names the cause.

    The horizon starts the week after the last complete one, so a period in
    both series means a chart would draw the same week twice - once as fact
    and once as projection.
    """

    result = ALL_FIXTURES["forecast_result"]
    history = [point.period for point in result.history]
    forecast = [point.period for point in result.forecast]

    assert not set(history) & set(forecast)
    assert len(history) == result.history_window.observations
    spanned = (result.history_window.end - result.history_window.start).days // 7 + 1
    assert spanned == result.history_window.observations


def test_query_fixture_time_range_matches_its_own_preset() -> None:
    """The resolved window has to be what the request's preset resolves to.

    ``previous_month`` is anchored to the dataset's last order date, not to
    today, so a fixture naming any other month silently contradicts the
    request it ships beside.
    """

    resolved = run_query(QUERY_REQUEST_FIXTURE.root).resolved_time_range
    for fixture_range in (
        ALL_FIXTURES["query_result"].resolved_time_range,
        ALL_FIXTURES["explainability"].resolved_filters.time_range,
    ):
        assert fixture_range is not None
        assert (fixture_range.start, fixture_range.end) == (resolved.start, resolved.end)


def test_all_router_stubs_are_registered() -> None:
    assert app.title == "AI Logistics Analytics API"
    assert {route.path for route in app.routes if hasattr(route, "path")} >= {"/health"}


@pytest.mark.parametrize("horizon", [0, 9, 4.0, "4"])
def test_invalid_forecast_horizon_is_rejected(horizon: object) -> None:
    with pytest.raises(ValidationError):
        StructuredRequest.model_validate(
            {
                "operation": "forecast",
                "metric": "order_demand",
                "grain": "week",
                "horizon_weeks": horizon,
                "filters": [],
                "time_range": None,
                "visualization": "auto",
            }
        )


def test_filter_collection_operators_require_a_list() -> None:
    with pytest.raises(ValidationError):
        StructuredRequest.model_validate(
            {
                "operation": "query",
                "metric": "delay_rate",
                "dimensions": ["carrier"],
                "filters": [{"field": "region", "op": "in", "value": "US-E"}],
                "limit": 10,
            }
        )


def test_contract_examples_allow_response_previews() -> None:
    query_result = QueryResult.model_validate(
        {
            "columns": ["carrier", "delay_rate"],
            "rows": [["FedEx", 18.2], ["UPS", 12.4]],
            "row_count": 9,
            "metric": "delay_rate",
            "resolved_time_range": {"start": "2025-08-01", "end": "2025-08-31"},
            "truncated": False,
        }
    )
    forecast_result = ForecastResult.model_validate(
        {
            "target": "order_demand",
            "grain": "week",
            "horizon_weeks": 4,
            "history": [{"period": "2025-W01", "value": 8}],
            "history_window": {
                "start": "2025-01-01",
                "end": "2025-12-30",
                "observations": 53,
            },
            "forecast": [{"period": "2026-W01", "value": 9.2}],
            "method": "linear_trend_12w",
            "methodology_note": "12-week trend over 53 weeks of order history.",
            "recommendation": {
                "rule": "F > B x 1.10 -> increase capacity by ceil(F - B); F < B x 0.90 -> no increase; else hold",
                "baseline_weekly_orders": 7.5,
                "forecast_level": 8.9,
                "delta_orders_per_week": 2,
                "action": "increase_capacity",
                "text": "Increase capacity by about 2 orders/week.",
            },
            "insufficient_data": False,
            "insufficient_data_reason": None,
        }
    )

    assert query_result.row_count == 9
    assert forecast_result.horizon_weeks == 4
