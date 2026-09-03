"""Validated Wave 0 fixtures for parallel frontend/orchestrator work."""

from backend.schemas import (
    AskResponse,
    Explainability,
    ForecastResult,
    QueryResult,
    StructuredRequest,
)


QUERY_REQUEST_FIXTURE = StructuredRequest.model_validate(
    {
        "operation": "query",
        "metric": "delay_rate",
        "dimensions": ["carrier"],
        "filters": [{"field": "region", "op": "in", "value": ["US-E", "US-W"]}],
        "time_range": {"preset": "previous_month"},
        "sort": {"by": "delay_rate", "direction": "desc"},
        "limit": 10,
        "visualization": "auto",
    }
)

FORECAST_REQUEST_FIXTURE = StructuredRequest.model_validate(
    {
        "operation": "forecast",
        "metric": "order_demand",
        "grain": "week",
        "horizon_weeks": 4,
        "filters": [],
        "time_range": None,
        "visualization": "auto",
    }
)

QUERY_RESULT_FIXTURE = QueryResult.model_validate(
    {
        "columns": ["carrier", "delay_rate"],
        "rows": [["FedEx", 18.2], ["UPS", 12.4]],
        "row_count": 2,
        "metric": "delay_rate",
        "resolved_time_range": {"start": "2025-08-01", "end": "2025-08-31"},
        "truncated": False,
    }
)

FORECAST_RESULT_FIXTURE = ForecastResult.model_validate(
    {
        "target": "order_demand",
        "grain": "week",
        "horizon_weeks": 4,
        "history": [
            {"period": "2025-W51", "value": 7},
            {"period": "2025-W52", "value": 8},
            {"period": "2026-W01", "value": 7},
            {"period": "2026-W02", "value": 8},
        ],
        "history_window": {
            "start": "2025-01-01",
            "end": "2025-12-30",
            "observations": 53,
        },
        "forecast": [
            {"period": "2026-W01", "value": 8.4},
            {"period": "2026-W02", "value": 8.8},
            {"period": "2026-W03", "value": 9.1},
            {"period": "2026-W04", "value": 9.3},
        ],
        "method": "moving_average_4w",
        "methodology_note": "4-week moving average over 53 weeks of order history.",
        "recommendation": {
            "rule": "F > B x 1.10 -> increase capacity by ceil(F - B); F < B x 0.90 -> no increase; else hold",
            "baseline_weekly_orders": 7.5,
            "forecast_level": 8.9,
            "delta_orders_per_week": 2,
            "action": "increase_capacity",
            "text": "Forecast averages 8.9 orders/week vs a trailing-4-week baseline of 7.5 (+18.7%), above the 10% threshold - consider capacity for ~2 more orders/week.",
        },
        "insufficient_data": False,
        "insufficient_data_reason": None,
    }
)

EXPLAINABILITY_FIXTURE = Explainability.model_validate(
    {
        "question": "Which carrier has the highest delay rate?",
        "structured_request": QUERY_REQUEST_FIXTURE.model_dump(mode="json"),
        "metric_definition": "delayed orders / delivered orders x 100",
        "metric_basis": {
            "row_count": 359,
            "inclusion_rule": "status in (delivered, delayed); exception excluded",
        },
        "resolved_filters": {
            "time_range": {
                "start": "2025-08-01",
                "end": "2025-08-31",
                "means": "reported_period",
            },
            "filters": [{"field": "region", "op": "in", "value": ["US-E", "US-W"]}],
        },
        "query_plan": "group by carrier -> compute delay_rate -> sort desc -> limit 10",
        "result_preview": QUERY_RESULT_FIXTURE.model_dump(mode="json"),
        "forecast_details": None,
    }
)

FORECAST_EXPLAINABILITY_FIXTURE = Explainability.model_validate(
    {
        "question": "Forecast demand for the next 4 weeks.",
        "structured_request": FORECAST_REQUEST_FIXTURE.model_dump(mode="json"),
        "metric_definition": "count of orders grouped by ISO week",
        "metric_basis": {
            "row_count": 400,
            "inclusion_rule": "all orders, grouped by order_date week",
        },
        "resolved_filters": {
            "time_range": {
                "start": "2025-01-01",
                "end": "2025-12-30",
                "means": "history_window",
            },
            "filters": [],
        },
        "query_plan": "aggregate weekly order demand -> apply moving_average_4w -> project 4 weeks",
        "result_preview": {
            "columns": ["period", "order_demand"],
            "rows": [
                ["2026-W01", 8.4],
                ["2026-W02", 8.8],
                ["2026-W03", 9.1],
                ["2026-W04", 9.3],
            ],
            "row_count": 4,
            "metric": "order_demand",
            "resolved_time_range": None,
            "truncated": False,
        },
        "forecast_details": {
            "horizon_weeks": 4,
            "method": "moving_average_4w",
            "history_window": {
                "start": "2025-01-01",
                "end": "2025-12-30",
                "observations": 53,
            },
            "baseline_weekly_orders": 7.5,
            "forecast_level": 8.9,
            "recommendation_rule": "F > B x 1.10 -> increase capacity by ceil(F - B)",
            "insufficient_data": False,
        },
    }
)

ASK_RESPONSE_FIXTURE = AskResponse.model_validate(
    {
        "answer": "FedEx has the highest delay rate at 18.2%.",
        # One block per tool call. `chart`, `table` and `explainability` are
        # read-only views of the first block, so they are not supplied here.
        "results": [
            {
                "answer": "FedEx has the highest delay rate at 18.2%.",
                "chart": {
                    "type": "bar",
                    "x": "carrier",
                    "y": "delay_rate",
                    "data": [
                        {"carrier": "FedEx", "delay_rate": 18.2},
                        {"carrier": "UPS", "delay_rate": 12.4},
                    ],
                },
                "table": QUERY_RESULT_FIXTURE.model_dump(mode="json"),
                "explainability": EXPLAINABILITY_FIXTURE.model_dump(mode="json"),
            }
        ],
        "plan": [],
        "narration": "composed",
        "thread_id": "ask-fixture",
        "unsupported": False,
        "unsupported_reason": None,
    }
)


ALL_FIXTURES = {
    "query_request": QUERY_REQUEST_FIXTURE,
    "forecast_request": FORECAST_REQUEST_FIXTURE,
    "query_result": QUERY_RESULT_FIXTURE,
    "forecast_result": FORECAST_RESULT_FIXTURE,
    "explainability": EXPLAINABILITY_FIXTURE,
    "forecast_explainability": FORECAST_EXPLAINABILITY_FIXTURE,
    "ask_response": ASK_RESPONSE_FIXTURE,
}
