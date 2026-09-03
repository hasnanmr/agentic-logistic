"""Stream D: weekly demand forecasting and recommendation tests."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.forecast import (
    BASELINE_WINDOW_WEEKS,
    MIN_HISTORY_WEEKS,
    TREND_WINDOW_WEEKS,
    build_forecast_details,
    run_forecast,
    weekly_demand_series,
)
from backend.ingestion import load_dataset
from backend.main import app
from backend.schemas import ForecastStructuredRequest


AUTH = ("reviewer", "s3cret")


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


def build(**overrides: object) -> ForecastStructuredRequest:
    payload: dict[str, object] = {
        "operation": "forecast",
        "metric": "order_demand",
        "grain": "week",
        "horizon_weeks": 4,
    }
    payload.update(overrides)
    return ForecastStructuredRequest.model_validate(payload)


def test_partial_weeks_are_excluded_from_the_series(dataset: pd.DataFrame) -> None:
    """Data runs Wed-to-Tue, so the first and last ISO weeks are part-weeks.

    Leaving them in drags the trailing 4-week mean from 5.50 to 4.75.
    """

    series = weekly_demand_series(dataset)

    assert len(series) == 51  # 53 ISO weeks touched, 2 of them incomplete
    assert series.tail(BASELINE_WINDOW_WEEKS).mean() == 5.5
    assert series.index[0].start_time.date() >= date(2025, 1, 1)
    assert series.index[-1].end_time.date() <= date(2025, 12, 30)


def test_zero_demand_weeks_are_filled_not_skipped() -> None:
    """A week with no orders is demand information, not missing data."""

    frame = pd.DataFrame(
        {
            "order_date": pd.to_datetime(
                ["2025-01-06", "2025-01-07", "2025-01-27"]  # weeks of Jan 13/20 empty
            )
        }
    )

    series = weekly_demand_series(frame)

    # Jan 6-12 has two orders, the next two weeks are filled with zero, and the
    # week holding Jan 27 is dropped as incomplete - the data stops mid-week.
    assert list(series.values) == [2, 0, 0]


def test_forecast_projects_the_requested_horizon(dataset: pd.DataFrame) -> None:
    result = run_forecast(build(horizon_weeks=4), dataset)

    assert result.insufficient_data is False
    assert len(result.forecast) == 4
    assert result.method == "linear_trend_12w"
    # A trend line, not a repeated constant: the shipped year drifts gently
    # downward, so each projected week sits just below the one before it.
    assert [point.value for point in result.forecast] == [5.38, 5.35, 5.32, 5.28]
    assert result.history_window.observations == 51


def test_forecast_periods_continue_after_the_last_complete_week(
    dataset: pd.DataFrame,
) -> None:
    result = run_forecast(build(horizon_weeks=3), dataset)

    # The last complete week is Dec 22-28 (2025-W52); the part-week holding
    # Dec 29-30 is excluded, so projection resumes at the week after W52.
    assert [point.period for point in result.forecast] == [
        "2026-W01",
        "2026-W02",
        "2026-W03",
    ]


@pytest.mark.parametrize("horizon", [1, 8])
def test_horizon_bounds_are_honoured(dataset: pd.DataFrame, horizon: int) -> None:
    result = run_forecast(build(horizon_weeks=horizon), dataset)

    assert len(result.forecast) == horizon


def test_baseline_window_matches_the_spec() -> None:
    """The recommendation baseline is the trailing four complete weeks."""

    assert BASELINE_WINDOW_WEEKS == 4


def test_the_projection_is_fitted_wider_than_the_baseline() -> None:
    """Equal windows would make the rule compare a number with itself.

    If the projection were the mean of the same four weeks the baseline
    averages, F would equal B for every possible dataset, the ratio would be
    1.0 by construction, and neither threshold could ever be crossed.
    """

    assert TREND_WINDOW_WEEKS > BASELINE_WINDOW_WEEKS


def test_recommendation_reports_baseline_forecast_and_rule(
    dataset: pd.DataFrame,
) -> None:
    recommendation = run_forecast(build(), dataset).recommendation

    assert recommendation is not None
    assert recommendation.forecast_level == 5.33
    assert recommendation.baseline_weekly_orders == 5.5
    assert "trailing 4 weeks" in recommendation.rule
    # Demand over the shipped year is flat to slightly declining, so "hold" is
    # the right answer here - it just is no longer the only possible one.
    assert recommendation.action == "hold"


def test_rising_demand_uses_only_the_trailing_four_week_baseline() -> None:
    """The baseline must not include older, lower-demand weeks."""

    days: list[str] = []
    start = pd.Timestamp("2025-01-06")  # a Monday, so every week is complete
    for week in range(17):
        # 2 orders/week for the first 12 weeks, then 12/week for the last 5.
        # The final calendar week is excluded as a part-week, leaving four
        # complete high-demand weeks in the trailing baseline.
        per_week = 2 if week < 12 else 12
        for order in range(per_week):
            days.append((start + timedelta(weeks=week, days=order % 7)).date().isoformat())
    frame = pd.DataFrame({"order_date": pd.to_datetime(days)})

    result = run_forecast(build(horizon_weeks=4), frame)

    assert result.recommendation.baseline_weekly_orders == 12
    assert result.recommendation.action == "increase_capacity"
    assert result.recommendation.delta_orders_per_week == 4


def test_falling_demand_uses_only_the_trailing_four_week_baseline() -> None:
    days: list[str] = []
    start = pd.Timestamp("2025-01-06")
    for week in range(17):
        # The final calendar week is excluded as a part-week, leaving four
        # complete low-demand weeks in the trailing baseline.
        per_week = 12 if week < 12 else 2
        for order in range(per_week):
            days.append((start + timedelta(weeks=week, days=order % 7)).date().isoformat())
    frame = pd.DataFrame({"order_date": pd.to_datetime(days)})

    result = run_forecast(build(), frame)

    assert result.recommendation.baseline_weekly_orders == 2
    assert result.recommendation.action == "no_increase"
    assert result.recommendation.delta_orders_per_week == 0


def test_short_history_refuses_instead_of_fabricating() -> None:
    days = [
        (pd.Timestamp("2025-01-06") + timedelta(weeks=week)).date().isoformat()
        for week in range(MIN_HISTORY_WEEKS - 2)
    ]
    frame = pd.DataFrame({"order_date": pd.to_datetime(days)})

    result = run_forecast(build(), frame)

    assert result.insufficient_data is True
    assert result.forecast == []
    assert result.recommendation is None
    assert "at least 8" in result.insufficient_data_reason


def test_filters_narrow_the_forecast_population(dataset: pd.DataFrame) -> None:
    result = run_forecast(
        build(filters=[{"field": "region", "op": "eq", "value": "UK"}]), dataset
    )

    unfiltered = run_forecast(build(), dataset)
    assert result.recommendation.forecast_level < unfiltered.recommendation.forecast_level


def test_forecast_details_carry_reproducibility_fields(dataset: pd.DataFrame) -> None:
    details = build_forecast_details(run_forecast(build(horizon_weeks=6), dataset))

    assert details.horizon_weeks == 6
    assert details.method == "linear_trend_12w"
    assert details.history_window.observations == 51
    assert details.baseline_weekly_orders is not None
    assert details.insufficient_data is False


class TestForecastEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("APP_USERNAME", AUTH[0])
        monkeypatch.setenv("APP_PASSWORD", AUTH[1])
        monkeypatch.setenv("DATA_CSV_PATH", "mock_logistics_data.csv")
        return TestClient(app)

    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.post("/api/forecast", json=build().model_dump(mode="json"))

        assert response.status_code == 401

    def test_returns_forecast_with_recommendation(self, client: TestClient) -> None:
        response = client.post(
            "/api/forecast", json=build().model_dump(mode="json"), auth=AUTH
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["forecast"]) == 4
        assert body["recommendation"]["action"] in {
            "increase_capacity",
            "no_increase",
            "hold",
        }

    @pytest.mark.parametrize("horizon", [0, 9])
    def test_out_of_range_horizon_is_rejected(
        self, client: TestClient, horizon: int
    ) -> None:
        response = client.post(
            "/api/forecast",
            json={
                "operation": "forecast",
                "metric": "order_demand",
                "grain": "week",
                "horizon_weeks": horizon,
            },
            auth=AUTH,
        )

        assert response.status_code == 422


def test_a_week_whose_sunday_ends_the_data_is_still_complete() -> None:
    """The trailing week is complete when the data covers all seven days.

    ``end_time`` is Sunday 23:59:59.999..., while order dates land at midnight,
    so comparing the two directly demands an order at an instant day-resolution
    data can never hold - and silently drops a full week of real history.
    """

    whole_weeks = pd.date_range("2025-01-06", "2025-03-30", freq="D")  # 12 ISO weeks
    series = weekly_demand_series(pd.DataFrame({"order_date": whole_weeks}))

    assert len(series) == 12
    assert series.index[-1].end_time.date() == date(2025, 3, 30)


def test_a_part_week_at_the_end_is_still_excluded() -> None:
    """The guard above must not swallow the exclusion it sits next to."""

    part_week = pd.date_range("2025-01-06", "2025-03-26", freq="D")  # ends mid-week
    series = weekly_demand_series(pd.DataFrame({"order_date": part_week}))

    assert len(series) == 11
    assert series.index[-1].end_time.date() == date(2025, 3, 23)


def test_every_recommendation_branch_is_reachable() -> None:
    """The rule must be able to return each of its three answers.

    This is the guard the suite was missing: with the projection and the
    baseline drawn from the same four weeks, F equalled B for every possible
    input and two of these three branches were dead code that no dataset could
    execute. Asserting one action at a time cannot notice that - only asking
    for all three can.
    """

    def frame_for(weekly: list[int]) -> pd.DataFrame:
        days: list[str] = []
        start = pd.Timestamp("2025-01-06")  # a Monday, so weeks are complete
        for week, count in enumerate(weekly):
            for order in range(count):
                days.append(
                    (start + timedelta(weeks=week, days=order % 7)).date().isoformat()
                )
        # One order in the following week, so the last listed week is complete.
        days.append((start + timedelta(weeks=len(weekly))).date().isoformat())
        return pd.DataFrame({"order_date": pd.to_datetime(days)})

    actions = {
        run_forecast(build(), frame_for(weekly)).recommendation.action
        for weekly in (
            list(range(4, 20)),          # steadily rising
            [20 - week for week in range(16)],  # steadily falling
            [8] * 16,                    # flat
        )
    }

    assert actions == {"increase_capacity", "no_increase", "hold"}


def test_a_wobble_in_the_trailing_weeks_is_not_a_trend() -> None:
    """Noise must not be promoted into a capacity recommendation.

    Weekly counts here scatter by about 4 orders around a mean of 7.5, so a
    slope drawn through the last four points is mostly noise - the shipped
    data's trailing four weeks rise at +0.6 orders/week while its trailing
    twelve are flat. Fitting the wider window is what keeps that wobble from
    becoming advice.
    """

    steady_then_wobble = [8, 7, 9, 8, 7, 8, 9, 8, 3, 5, 4, 7]
    days: list[str] = []
    start = pd.Timestamp("2025-01-06")
    for week, count in enumerate(steady_then_wobble):
        for order in range(count):
            days.append((start + timedelta(weeks=week, days=order % 7)).date().isoformat())
    days.append((start + timedelta(weeks=len(steady_then_wobble))).date().isoformat())

    result = run_forecast(build(), pd.DataFrame({"order_date": pd.to_datetime(days)}))

    assert result.recommendation.action == "hold"


def test_a_steep_decline_never_projects_negative_demand() -> None:
    """Orders cannot be negative, so the line floors at zero."""

    days: list[str] = []
    start = pd.Timestamp("2025-01-06")
    for week, count in enumerate([40 - week * 3 for week in range(13)]):
        for order in range(max(count, 0)):
            days.append((start + timedelta(weeks=week, days=order % 7)).date().isoformat())
    days.append((start + timedelta(weeks=13)).date().isoformat())

    result = run_forecast(build(horizon_weeks=8), pd.DataFrame({"order_date": pd.to_datetime(days)}))

    assert all(point.value >= 0 for point in result.forecast)
    assert result.forecast[-1].value == 0
