"""The semantic metric registry - the single definition of every KPI.

Both the dashboard and the AI path compute numbers through this module, which
is what keeps NFR-01 (the two must reconcile) true by construction rather than
by discipline. Metric names match the frozen ``MetricName`` literal in
``backend.core.schemas``; PRD 8 is the prose version of what is encoded here.

Each metric is a plain function over an already-filtered DataFrame, so the same
definition serves both a scalar KPI and a grouped breakdown - the Query Tool
applies it per group without any metric needing to know about grouping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Final

import pandas as pd

from backend.core import status_rules
from backend.core.status_rules import (
    ALL_ORDERS_INCLUSION,
    AVG_DELIVERY_TIME_INCLUSION,
    DELIVERED_INCLUSION,
)


MetricValue = float | int | None

ALL_DIMENSIONS: Final[frozenset[str]] = frozenset(
    {
        "order_date",
        "week",
        "month",
        "carrier",
        "origin_city",
        "destination_city",
        "status",
        "region",
        "product_category",
    }
)

# Grouping a status-derived rate *by status* is degenerate: every group then
# holds a single status, so the rate is trivially 100% or 0%. Those metrics
# therefore do not approve ``status`` as a breakdown dimension.
_DIMENSIONS_WITHOUT_STATUS: Final[frozenset[str]] = ALL_DIMENSIONS - {"status"}

_PERCENT_PRECISION: Final = 2
_DAYS_PRECISION: Final = 2


def _ratio_percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, _PERCENT_PRECISION)


def _total_orders(frame: pd.DataFrame) -> MetricValue:
    return int(frame["order_id"].nunique())


def _delivered_orders(frame: pd.DataFrame) -> MetricValue:
    return int(status_rules.delivered_mask(frame).sum())


def _delayed_orders(frame: pd.DataFrame) -> MetricValue:
    return int(status_rules.delayed_mask(frame).sum())


def _on_time_rate(frame: pd.DataFrame) -> MetricValue:
    delivered = int(status_rules.delivered_mask(frame).sum())
    on_time = int(status_rules.on_time_mask(frame).sum())
    return _ratio_percent(on_time, delivered)


def _delay_rate(frame: pd.DataFrame) -> MetricValue:
    delivered = int(status_rules.delivered_mask(frame).sum())
    delayed = int(status_rules.delayed_mask(frame).sum())
    return _ratio_percent(delayed, delivered)


def _avg_delivery_time(frame: pd.DataFrame) -> MetricValue:
    dated = frame[status_rules.delivery_dated_mask(frame)]
    if dated.empty:
        return None
    elapsed_days = (dated["delivery_date"] - dated["order_date"]).dt.days
    return round(float(elapsed_days.mean()), _DAYS_PRECISION)


def _order_demand(frame: pd.DataFrame) -> MetricValue:
    return int(len(frame))


def _count_all(frame: pd.DataFrame) -> int:
    return int(len(frame))


def _count_delivered(frame: pd.DataFrame) -> int:
    return int(status_rules.delivered_mask(frame).sum())


def _count_delivery_dated(frame: pd.DataFrame) -> int:
    return int(status_rules.delivery_dated_mask(frame).sum())


@dataclass(frozen=True)
class MetricDefinition:
    """One approved metric: how to compute it and how to explain it."""

    name: str
    label: str
    compute: Callable[[pd.DataFrame], MetricValue]
    definition_text: str
    inclusion_rule: str
    #: Rows the formula actually operates on - its population, not its value.
    #: This is what makes Average Delivery Time's basis (370, includes
    #: exception) visibly different from Delivered Orders' (359).
    basis_count: Callable[[pd.DataFrame], int]
    allowed_dimensions: frozenset[str]

    def describe(self, frame: pd.DataFrame) -> str:
        """Definition text with the basis inline, for explainability."""

        return f"{self.definition_text} (n={self.basis_count(frame)})"


METRICS: Final[dict[str, MetricDefinition]] = {
    definition.name: definition
    for definition in (
        MetricDefinition(
            name="total_orders",
            label="Total Orders",
            compute=_total_orders,
            definition_text="count of distinct order_id",
            inclusion_rule=ALL_ORDERS_INCLUSION,
            basis_count=_count_all,
            allowed_dimensions=ALL_DIMENSIONS,
        ),
        MetricDefinition(
            name="delivered_orders",
            label="Delivered Orders",
            compute=_delivered_orders,
            definition_text="orders that completed delivery, on time or late",
            inclusion_rule=DELIVERED_INCLUSION,
            basis_count=_count_delivered,
            allowed_dimensions=_DIMENSIONS_WITHOUT_STATUS,
        ),
        MetricDefinition(
            name="delayed_orders",
            label="Delayed Orders",
            compute=_delayed_orders,
            definition_text="orders with status 'delayed'",
            inclusion_rule=DELIVERED_INCLUSION,
            basis_count=_count_delivered,
            allowed_dimensions=_DIMENSIONS_WITHOUT_STATUS,
        ),
        MetricDefinition(
            name="on_time_rate",
            label="On-Time Delivery Rate",
            compute=_on_time_rate,
            definition_text="on-time delivered orders / delivered orders x 100",
            inclusion_rule=DELIVERED_INCLUSION,
            basis_count=_count_delivered,
            allowed_dimensions=_DIMENSIONS_WITHOUT_STATUS,
        ),
        MetricDefinition(
            name="delay_rate",
            label="Delay Rate",
            compute=_delay_rate,
            definition_text="delayed orders / delivered orders x 100",
            inclusion_rule=DELIVERED_INCLUSION,
            basis_count=_count_delivered,
            allowed_dimensions=_DIMENSIONS_WITHOUT_STATUS,
        ),
        MetricDefinition(
            name="avg_delivery_time",
            label="Average Delivery Time",
            compute=_avg_delivery_time,
            definition_text="mean days from order_date to delivery_date",
            inclusion_rule=AVG_DELIVERY_TIME_INCLUSION,
            basis_count=_count_delivery_dated,
            allowed_dimensions=ALL_DIMENSIONS,
        ),
        MetricDefinition(
            name="order_demand",
            label="Order Demand",
            compute=_order_demand,
            definition_text="count of orders per period",
            inclusion_rule=ALL_ORDERS_INCLUSION,
            basis_count=_count_all,
            allowed_dimensions=ALL_DIMENSIONS,
        ),
    )
}


def get_metric(name: str) -> MetricDefinition:
    """Look up an approved metric, rejecting anything outside the registry."""

    try:
        return METRICS[name]
    except KeyError:
        raise KeyError(
            f"unknown metric '{name}'; approved metrics: {', '.join(sorted(METRICS))}"
        ) from None
