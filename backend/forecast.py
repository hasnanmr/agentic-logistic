"""Weekly order-demand forecasting with a rule-based capacity recommendation.

One basic method, honestly evaluated, is the bar the source spec sets - so this
is a four-week moving average, not a model comparison (PRD 12).

Two details matter more than the method choice:

* **Partial weeks are excluded.** The dataset starts mid-week (Wed 2025-01-01)
  and ends mid-week (Tue 2025-12-30), so its first and last ISO weeks hold 5 and
  2 days of orders. Leaving them in drags the trailing four-week mean from 5.50
  to 4.75 - a ~14% understatement that would look entirely plausible.
* **The recommendation baseline uses the trailing four complete weeks.** This
  is the fixed comparison window required by the product spec. With the current
  flat moving-average method, the baseline and forecast level are intentionally
  the same; the recommendation rule remains explicit and ready for methods that
  produce a varying forecast across the horizon.
"""

from __future__ import annotations

import math
from typing import Final

import pandas as pd

from backend.ingestion import get_dataset
from backend.query_tool import apply_filters, resolve_time_range, validate_filters
from backend.schemas import (
    ForecastDetails,
    ForecastPoint,
    ForecastRecommendation,
    ForecastResult,
    ForecastStructuredRequest,
    HistoryWindow,
)


WEEK_FREQ: Final = "W-SUN"

#: Weeks averaged to produce the forecast level.
MODEL_WINDOW_WEEKS: Final = 4

#: Weeks averaged to produce the comparison baseline.
BASELINE_WINDOW_WEEKS: Final = 4

#: Relative gap from baseline before a capacity change is recommended.
THRESHOLD: Final = 0.10

#: Minimum complete weeks required to forecast at all (PRD 12).
MIN_HISTORY_WEEKS: Final = 8

METHOD: Final = "moving_average_4w"


def _iso_label(period: pd.Period) -> str:
    """Render a week period as an ISO ``YYYY-Www`` label."""

    iso = period.start_time.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def weekly_demand_series(frame: pd.DataFrame) -> pd.Series:
    """Orders per complete ISO week, gap-filled with zero.

    A week with no orders is real demand information (zero), so gaps are filled
    rather than skipped. Weeks not fully covered by the dataset's date range are
    dropped - they measure a shorter period and are not comparable.
    """

    if frame.empty:
        return pd.Series(dtype="int64")

    first_order = frame["order_date"].min()
    last_order = frame["order_date"].max()

    periods = frame["order_date"].dt.to_period(WEEK_FREQ)
    counts = periods.value_counts().sort_index()

    span = pd.period_range(counts.index.min(), counts.index.max(), freq=WEEK_FREQ)
    complete = [
        period
        for period in span
        if period.start_time >= first_order and period.end_time <= last_order
    ]
    if not complete:
        return pd.Series(dtype="int64")

    return counts.reindex(complete, fill_value=0).astype("int64")


def _build_recommendation(
    series: pd.Series, forecast_level: float
) -> ForecastRecommendation:
    baseline_window = min(BASELINE_WINDOW_WEEKS, len(series))
    baseline = float(series.tail(baseline_window).mean())

    rule = (
        f"F = mean of the {MODEL_WINDOW_WEEKS}-week moving-average forecast; "
        f"B = mean weekly orders over the trailing {baseline_window} weeks. "
        f"F > B x {1 + THRESHOLD:.2f} -> increase capacity by ceil(F - B); "
        f"F < B x {1 - THRESHOLD:.2f} -> no increase; otherwise hold."
    )

    if baseline == 0:
        # No demand to compare against; recommending a change would be noise.
        return ForecastRecommendation(
            rule=rule,
            baseline_weekly_orders=0.0,
            forecast_level=round(forecast_level, 2),
            delta_orders_per_week=0,
            action="hold",
            text="The trailing baseline is zero orders per week, so there is no "
            "meaningful capacity signal to act on.",
        )

    change = (forecast_level - baseline) / baseline
    if forecast_level > baseline * (1 + THRESHOLD):
        action = "increase_capacity"
        delta = max(0, math.ceil(forecast_level - baseline))
        text = (
            f"Forecast averages {forecast_level:.2f} orders/week against a trailing "
            f"{baseline_window}-week baseline of {baseline:.2f} ({change:+.1%}), above "
            f"the {THRESHOLD:.0%} threshold - consider capacity for about {delta} more "
            "order(s) per week."
        )
    elif forecast_level < baseline * (1 - THRESHOLD):
        action = "no_increase"
        delta = 0
        text = (
            f"Forecast averages {forecast_level:.2f} orders/week against a trailing "
            f"{baseline_window}-week baseline of {baseline:.2f} ({change:+.1%}), below "
            f"the {THRESHOLD:.0%} threshold - demand is softening, no capacity increase "
            "is indicated."
        )
    else:
        action = "hold"
        delta = 0
        text = (
            f"Forecast averages {forecast_level:.2f} orders/week against a trailing "
            f"{baseline_window}-week baseline of {baseline:.2f} ({change:+.1%}), within "
            f"the {THRESHOLD:.0%} threshold - hold current capacity."
        )

    return ForecastRecommendation(
        rule=rule,
        baseline_weekly_orders=round(baseline, 2),
        forecast_level=round(forecast_level, 2),
        delta_orders_per_week=delta,
        action=action,
        text=text,
    )


def _insufficient(
    request: ForecastStructuredRequest, series: pd.Series, window: HistoryWindow
) -> ForecastResult:
    reason = (
        f"only {len(series)} complete week(s) of history are available; "
        f"at least {MIN_HISTORY_WEEKS} are required for a weekly forecast"
    )
    return ForecastResult(
        target="order_demand",
        grain="week",
        horizon_weeks=request.horizon_weeks,
        history=[
            ForecastPoint(period=_iso_label(period), value=float(value))
            for period, value in series.items()
        ],
        history_window=window,
        forecast=[],
        method=METHOD,
        methodology_note=(
            "No forecast produced: a 4-week moving average needs a longer, "
            "stable history than the filtered data provides."
        ),
        recommendation=None,
        insufficient_data=True,
        insufficient_data_reason=reason,
    )


def run_forecast(
    request: ForecastStructuredRequest, frame: pd.DataFrame | None = None
) -> ForecastResult:
    """Produce a weekly demand forecast for the requested horizon."""

    source = get_dataset() if frame is None else frame

    # For a forecast, time_range narrows the history learned from - it is not a
    # reporting period. Explainability labels it as such.
    window = resolve_time_range(
        request.time_range, source["order_date"].max().date()
    ) if request.time_range is not None else None
    working = source
    if window is not None:
        working = working[
            working["order_date"].between(
                pd.Timestamp(window.start), pd.Timestamp(window.end)
            )
        ]
    validate_filters(request.filters)
    working = apply_filters(working, request.filters)

    series = weekly_demand_series(working)
    history_window = (
        HistoryWindow(
            start=series.index[0].start_time.date(),
            end=series.index[-1].end_time.date(),
            observations=len(series),
        )
        if len(series)
        else HistoryWindow(
            start=source["order_date"].min().date(),
            end=source["order_date"].max().date(),
            observations=0,
        )
    )

    if len(series) < MIN_HISTORY_WEEKS:
        return _insufficient(request, series, history_window)

    forecast_level = float(series.tail(MODEL_WINDOW_WEEKS).mean())
    last_period = series.index[-1]
    forecast_points = [
        ForecastPoint(
            period=_iso_label(last_period + step), value=round(forecast_level, 2)
        )
        for step in range(1, request.horizon_weeks + 1)
    ]

    excluded_note = (
        " Weeks not fully covered by the dataset are excluded, so a part-week at "
        "either end cannot drag the average down."
    )
    return ForecastResult(
        target="order_demand",
        grain="week",
        horizon_weeks=request.horizon_weeks,
        history=[
            ForecastPoint(period=_iso_label(period), value=float(value))
            for period, value in series.items()
        ],
        history_window=history_window,
        forecast=forecast_points,
        method=METHOD,
        methodology_note=(
            f"{MODEL_WINDOW_WEEKS}-week moving average over {len(series)} complete "
            f"weeks of order history, projected flat across {request.horizon_weeks} "
            f"week(s)." + excluded_note
        ),
        recommendation=_build_recommendation(series, forecast_level),
        insufficient_data=False,
        insufficient_data_reason=None,
    )


def build_forecast_details(result: ForecastResult) -> ForecastDetails:
    """Explainability block for a forecast answer (Stream E consumes this)."""

    return ForecastDetails(
        horizon_weeks=result.horizon_weeks,
        method=result.method,
        history_window=result.history_window,
        baseline_weekly_orders=(
            result.recommendation.baseline_weekly_orders if result.recommendation else None
        ),
        forecast_level=(
            result.recommendation.forecast_level if result.recommendation else None
        ),
        recommendation_rule=(
            result.recommendation.rule
            if result.recommendation
            else "no recommendation: insufficient history"
        ),
        insufficient_data=result.insufficient_data,
    )
