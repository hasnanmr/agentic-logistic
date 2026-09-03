"""Wave 0 contract and application smoke tests."""

import pytest
from pydantic import ValidationError

from backend.fixtures import ALL_FIXTURES
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
            "method": "moving_average_4w",
            "methodology_note": "4-week moving average over 53 weeks of order history.",
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
