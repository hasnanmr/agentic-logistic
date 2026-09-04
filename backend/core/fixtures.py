"""Validated Wave 0 fixtures for parallel frontend/orchestrator work."""

from backend.core.schemas import (
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

# What ``run_query`` returns for QUERY_REQUEST_FIXTURE: delay_rate by carrier,
# US-E/US-W, ``previous_month``. The preset is anchored to the data's last
# order date (2025-12-30) rather than to today, so the window is November, and
# November is a thin month - four of the six carriers deliver nothing late.
# Kept as the engine computes it, zeros included; a tidier set of numbers here
# would only be a nicer-looking lie.
QUERY_RESULT_FIXTURE = QueryResult.model_validate(
    {
        "columns": ["carrier", "delay_rate"],
        "rows": [
            ["UPS", 50.0],
            ["USPS", 25.0],
            ["LaserShip", 0.0],
            ["FedEx", 0.0],
            ["Royal Mail", 0.0],
            ["DPD", 0.0],
        ],
        "row_count": 6,
        "total_groups": 6,
        "metric": "delay_rate",
        "resolved_time_range": {"start": "2025-11-01", "end": "2025-11-30"},
        "truncated": False,
    }
)

# A real ``run_forecast`` output over a 12-week illustrative series, not a
# hand-drawn one. The engine fits a trend and extends it, so the projection
# slopes; ``test_wave0`` replays this history through the engine and asserts
# the whole block comes back unchanged, which is what keeps a hand edit here
# from inventing a response the API cannot send.
FORECAST_RESULT_FIXTURE = ForecastResult.model_validate(
    {
        "target": "order_demand",
        "grain": "week",
        "horizon_weeks": 4,
        "history": [
            {"period": "2025-W41", "value": 6},
            {"period": "2025-W42", "value": 5},
            {"period": "2025-W43", "value": 7},
            {"period": "2025-W44", "value": 6},
            {"period": "2025-W45", "value": 8},
            {"period": "2025-W46", "value": 7},
            {"period": "2025-W47", "value": 9},
            {"period": "2025-W48", "value": 8},
            {"period": "2025-W49", "value": 7},
            {"period": "2025-W50", "value": 8},
            {"period": "2025-W51", "value": 7},
            {"period": "2025-W52", "value": 8},
        ],
        "history_window": {
            "start": "2025-10-06",
            "end": "2025-12-28",
            "observations": 12,
        },
        "forecast": [
            {"period": "2026-W01", "value": 8.39},
            {"period": "2026-W02", "value": 8.58},
            {"period": "2026-W03", "value": 8.77},
            {"period": "2026-W04", "value": 8.96},
        ],
        "method": "linear_trend_12w",
        "methodology_note": (
            "Least-squares trend fitted over the trailing 12 of 12 complete weeks of "
            "order history, extended across 4 week(s) and floored at zero. Weeks not "
            "fully covered by the dataset are excluded, so a part-week at either end "
            "cannot drag the average down."
        ),
        "recommendation": {
            "rule": (
                "F = mean of the projected values across the horizon; B = mean weekly "
                "orders over the trailing 4 weeks. F > B x 1.10 -> increase capacity by "
                "ceil(F - B); F < B x 0.90 -> no increase; otherwise hold."
            ),
            "baseline_weekly_orders": 7.5,
            "forecast_level": 8.68,
            "delta_orders_per_week": 2,
            "action": "increase_capacity",
            "text": (
                "Forecast averages 8.68 orders/week against a trailing 4-week baseline of "
                "7.50 (+15.7%), above the 10% threshold - consider capacity for about 2 "
                "more order(s) per week."
            ),
        },
        "insufficient_data": False,
        "insufficient_data_reason": None,
    }
)

EXPLAINABILITY_FIXTURE = Explainability.model_validate(
    {
        "question": "Which carrier has the highest delay rate?",
        "structured_request": QUERY_REQUEST_FIXTURE.model_dump(mode="json"),
        "metric_definition": "delayed orders / delivered orders x 100 (n=359)",
        "metric_basis": {
            "row_count": 359,
            "inclusion_rule": (
                "status in (delivered, delayed); exception, in_transit and "
                "canceled excluded"
            ),
        },
        "resolved_filters": {
            "time_range": {
                "start": "2025-11-01",
                "end": "2025-11-30",
                "means": "reported_period",
            },
            "filters": [{"field": "region", "op": "in", "value": ["US-E", "US-W"]}],
        },
        "query_plan": (
            "filter orders -> restrict to the resolved time range -> group by "
            "carrier -> compute delay_rate -> sort by delay_rate desc -> limit 10"
        ),
        "result_preview": QUERY_RESULT_FIXTURE.model_dump(mode="json"),
        "forecast_details": None,
    }
)

# Generated by ``forecast_explainability`` over FORECAST_RESULT_FIXTURE. The
# preview carries the history and the horizon in one table, tagged by a
# ``series`` column - a forecast row and an actual row are not interchangeable
# and a reader must be able to tell them apart.
FORECAST_EXPLAINABILITY_FIXTURE = Explainability.model_validate(
    {
        "question": "Forecast demand for the next 4 weeks.",
        "structured_request": FORECAST_REQUEST_FIXTURE.model_dump(mode="json"),
        "metric_definition": 'orders per complete ISO week (n=12 weeks)',
        "metric_basis": {
            "row_count": 12,
            "inclusion_rule": (
                "complete ISO weeks only; part-weeks at either end of the data "
                "are excluded because they measure a shorter period"
            ),
        },
        "resolved_filters": {
            "time_range": {
                "start": '2025-10-06',
                "end": '2025-12-28',
                "means": "history_window",
            },
            "filters": [],
        },
        "query_plan": (
            "aggregate orders per complete ISO week -> fit a 12-week trend -> "
            "project 4 week(s) -> compare with the trailing baseline"
        ),
        "result_preview": {
            "columns": ["period", "order_demand", "series"],
            "rows": [
                    ['2025-W41', 6.0, 'actual'],
                    ['2025-W42', 5.0, 'actual'],
                    ['2025-W43', 7.0, 'actual'],
                    ['2025-W44', 6.0, 'actual'],
                    ['2025-W45', 8.0, 'actual'],
                    ['2025-W46', 7.0, 'actual'],
                    ['2025-W47', 9.0, 'actual'],
                    ['2025-W48', 8.0, 'actual'],
                    ['2025-W49', 7.0, 'actual'],
                    ['2025-W50', 8.0, 'actual'],
                    ['2025-W51', 7.0, 'actual'],
                    ['2025-W52', 8.0, 'actual'],
                    ['2026-W01', 8.39, 'forecast'],
                    ['2026-W02', 8.58, 'forecast'],
                    ['2026-W03', 8.77, 'forecast'],
                    ['2026-W04', 8.96, 'forecast'],
            ],
            "row_count": 16,
            "total_groups": 16,
            "metric": "order_demand",
            "resolved_time_range": None,
            "truncated": False,
        },
        "forecast_details": {
            "horizon_weeks": 4,
            "method": "linear_trend_12w",
            "history_window": {
                "start": '2025-10-06',
                "end": '2025-12-28',
                "observations": 12,
            },
            "baseline_weekly_orders": 7.5,
            "forecast_level": 8.68,
            "recommendation_rule": FORECAST_RESULT_FIXTURE.recommendation.rule,
            "insufficient_data": False,
        },
    }
)


ASK_RESPONSE_FIXTURE = AskResponse.model_validate(
    {
        "answer": "UPS has the highest delay rate at 50.0%.",
        # One block per tool call. `chart`, `table` and `explainability` are
        # read-only views of the first block, so they are not supplied here.
        "results": [
            {
                "answer": "UPS has the highest delay rate at 50.0%.",
                "chart": {
                    "type": "bar",
                    "x": "carrier",
                    "y": "delay_rate",
                    "data": [
                        {"carrier": "UPS", "delay_rate": 50.0},
                        {"carrier": "USPS", "delay_rate": 25.0},
                        {"carrier": "LaserShip", "delay_rate": 0.0},
                        {"carrier": "FedEx", "delay_rate": 0.0},
                        {"carrier": "Royal Mail", "delay_rate": 0.0},
                        {"carrier": "DPD", "delay_rate": 0.0},
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
