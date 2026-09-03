"""Weekly order-demand forecasting with a rule-based capacity recommendation.

One basic method, honestly evaluated, is the bar the source spec sets - so this
is a least-squares trend line, not a model comparison (PRD 12, task D.2).

Three details matter more than the method choice:

* **Partial weeks are excluded.** The dataset starts mid-week (Wed 2025-01-01)
  and ends mid-week (Tue 2025-12-30), so its first and last ISO weeks hold 5 and
  2 days of orders. Leaving them in drags the trailing four-week mean from 5.50
  to 4.75 - a ~14% understatement that would look entirely plausible.
* **The projection must be able to disagree with the baseline.** The rule asks
  whether projected demand runs above or below the trailing four-week norm
  (task D.3). A flat four-week moving average answers that question with
  itself: F and B average the same four weeks, the ratio is 1.0 by
  construction, and no data can ever cross the +/-10% threshold, so
  ``increase_capacity`` and ``no_increase`` are unreachable. A trend line can
  disagree, which is the whole point of comparing.
* **The trend is fitted over twelve weeks, not four.** Weekly counts here have
  a standard deviation of about 4 on a mean of 7.5, so a slope drawn through
  four points is mostly noise - the shipped data's trailing four weeks slope
  upward at +0.6 orders/week (r=+0.60) while the trailing twelve are flat
  (-0.03, r=-0.07). Fitting the shorter window would manufacture a capacity
  recommendation out of a wobble.
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

#: Weeks the trend line is fitted over. Deliberately wider than
#: BASELINE_WINDOW_WEEKS - see the module docstring.
TREND_WINDOW_WEEKS: Final = 12

#: Weeks averaged to produce the comparison baseline (task D.3).
BASELINE_WINDOW_WEEKS: Final = 4

#: Relative gap from baseline before a capacity change is recommended.
THRESHOLD: Final = 0.10

#: Minimum complete weeks required to forecast at all (PRD 12).
MIN_HISTORY_WEEKS: Final = 8

METHOD: Final = "linear_trend_12w"


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
    # ``end_time`` is the last instant of the week (Sunday 23:59:59.999...),
    # while order dates are day-resolution. Comparing the two directly would
    # demand an order stamped at that instant, so a week whose Sunday is the
    # dataset's final day - genuinely complete - would be dropped. Compare on
    # calendar days instead; the intent is "does the data span this week", not
    # "does an order land on its final microsecond".
    complete = [
        period
        for period in span
        if period.start_time >= first_order and period.end_time.normalize() <= last_order
    ]
    if not complete:
        return pd.Series(dtype="int64")

    return counts.reindex(complete, fill_value=0).astype("int64")


def _project(series: pd.Series, horizon: int) -> list[float]:
    """Fit a least-squares line over the trailing window and extend it.

    Ordinary least squares, written out rather than pulled from a library, so
    the arithmetic behind a capacity recommendation stays readable. A perfectly
    flat window gives a zero slope and therefore a flat projection, which is
    the right answer rather than a degenerate one.

    Negative demand does not exist, so a steep decline flattens at zero instead
    of projecting orders that can never be placed.
    """

    window = min(TREND_WINDOW_WEEKS, len(series))
    values = [float(value) for value in series.tail(window)]
    mean_x = (window - 1) / 2
    mean_y = sum(values) / window

    variance = sum((x - mean_x) ** 2 for x in range(window))
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values))
    slope = covariance / variance if variance else 0.0
    intercept = mean_y - slope * mean_x

    return [
        max(0.0, round(intercept + slope * (window - 1 + step), 2))
        for step in range(1, horizon + 1)
    ]


def _build_recommendation(
    series: pd.Series, forecast_level: float
) -> ForecastRecommendation:
    baseline_window = min(BASELINE_WINDOW_WEEKS, len(series))
    baseline = float(series.tail(baseline_window).mean())

    rule = (
        f"F = mean of the projected values across the horizon; "
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
            "No forecast produced: a trend fit needs a longer, stable history "
            "than the filtered data provides."
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

    projected = _project(series, request.horizon_weeks)
    # F is the mean of the projected values (task D.3), not a separate estimate,
    # so the number the recommendation argues from is the one the chart draws.
    forecast_level = sum(projected) / len(projected)
    last_period = series.index[-1]
    forecast_points = [
        ForecastPoint(period=_iso_label(last_period + step), value=value)
        for step, value in enumerate(projected, start=1)
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
            f"Least-squares trend fitted over the trailing "
            f"{min(TREND_WINDOW_WEEKS, len(series))} of {len(series)} complete "
            f"weeks of order history, extended across {request.horizon_weeks} "
            f"week(s) and floored at zero." + excluded_note
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
