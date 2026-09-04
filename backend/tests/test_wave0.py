"""Wave 0 contract and application smoke tests."""

import datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from backend.core.answers import forecast_explainability, query_explainability
from backend.core.fixtures import (
    ALL_FIXTURES,
    FORECAST_REQUEST_FIXTURE,
    QUERY_REQUEST_FIXTURE,
)
from backend.tools.forecast import run_forecast
from backend.core.ingestion import get_dataset
from backend.tools.query import run_query
from backend.main import app
from backend.core.schemas import StructuredRequest
from backend.core.schemas import ForecastResult, QueryResult


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


def test_query_fixture_is_what_the_engine_actually_returns() -> None:
    """Running the fixture's own request must reproduce the fixture.

    ``previous_month`` is anchored to the dataset's last order date, not to
    today, so a fixture naming any other month silently contradicts the
    request it ships beside - and rows from some other window contradict it
    twice over.
    """

    replayed = run_query(QUERY_REQUEST_FIXTURE.root)

    assert replayed.model_dump(mode="json") == ALL_FIXTURES["query_result"].model_dump(
        mode="json"
    )


def test_query_explainability_fixture_is_derived_from_the_result() -> None:
    """answers.py assembles this from the result; the fixture must agree."""

    fixture = ALL_FIXTURES["explainability"]
    rebuilt = query_explainability(
        fixture.question,
        QUERY_REQUEST_FIXTURE.root,
        ALL_FIXTURES["query_result"],
        get_dataset(),
    )

    assert rebuilt.model_dump(mode="json") == fixture.model_dump(mode="json")


def test_the_ask_response_fixture_agrees_with_the_blocks_it_embeds() -> None:
    """The headline answer must name the row the table actually puts first."""

    response = ALL_FIXTURES["ask_response"]
    block = response.results[0]
    top_carrier, top_rate = ALL_FIXTURES["query_result"].rows[0]

    assert response.answer == block.answer
    assert str(top_carrier) in block.answer
    assert f"{top_rate}%" in block.answer
    assert block.chart is not None
    assert [point[block.chart.x] for point in block.chart.data] == [
        row[0] for row in ALL_FIXTURES["query_result"].rows
    ]


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
            "rows": [["UPS", 50.0], ["USPS", 25.0]],
            "row_count": 2,
            "total_groups": 9,
            "metric": "delay_rate",
            "resolved_time_range": {"start": "2025-11-01", "end": "2025-11-30"},
            "truncated": True,
        }
    )
    forecast_result = ForecastResult.model_validate(
        {
            "target": "order_demand",
            "grain": "week",
            "horizon_weeks": 4,
            # One history point out of 51 - the preview this test is about.
            # The point is still the real last complete week, and the horizon
            # still starts the week after it: truncating a series must not be
            # an excuse to invent one.
            "history": [{"period": "2025-W52", "value": 8}],
            "history_window": {
                "start": "2025-01-06",
                "end": "2025-12-28",
                "observations": 51,
            },
            "forecast": [{"period": "2026-W01", "value": 9.2}],
            "method": "linear_trend_12w",
            "methodology_note": "12-week trend over 51 complete weeks of order history.",
            "recommendation": {
                "rule": (
                    "F = mean of the projected values across the horizon; B = mean "
                    "weekly orders over the trailing 4 weeks. F > B x 1.10 -> "
                    "increase capacity by ceil(F - B); F < B x 0.90 -> no increase; "
                    "otherwise hold."
                ),
                "baseline_weekly_orders": 7.5,
                # F is the mean of the projection, and the projection is one
                # value here; 9.2 > 7.5 x 1.10, so the action follows the rule.
                "forecast_level": 9.2,
                "delta_orders_per_week": 2,
                "action": "increase_capacity",
                "text": (
                    "Forecast averages 9.20 orders/week against a trailing 4-week "
                    "baseline of 7.50 (+22.7%), above the 10% threshold - consider "
                    "capacity for about 2 more order(s) per week."
                ),
            },
            "insufficient_data": False,
            "insufficient_data_reason": None,
        }
    )

    # The preview's row count describes its payload, while total_groups keeps
    # the size of the complete grouped result explicit.
    assert query_result.row_count == len(query_result.rows) == 2
    assert query_result.total_groups == 9
    assert forecast_result.horizon_weeks == 4
    assert len(forecast_result.history) < forecast_result.history_window.observations
