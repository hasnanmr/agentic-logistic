"""Order-status semantics, defined once for the whole application.

Every metric reads its status buckets from here so the rules in PRD 7/8 exist
in exactly one place. Profiling of ``mock_logistics_data.csv`` established:

* ``delivered`` (304) and ``delayed`` (55) always carry a delivery date, and
  ``delayed`` means "delivered, but slow" - not "not yet delivered".
* ``exception`` (11) also carries a delivery date, but its business meaning is
  unspecified, so it is reported as its own bucket instead of being folded into
  an on-time/late rate that would misrepresent it either way.
* ``in_transit`` (27) and ``canceled`` (3) never carry a delivery date.
"""

from __future__ import annotations

from typing import Final

import pandas as pd


ON_TIME_STATUS: Final = "delivered"
DELAYED_STATUS: Final = "delayed"
EXCEPTION_STATUS: Final = "exception"
IN_TRANSIT_STATUS: Final = "in_transit"
CANCELED_STATUS: Final = "canceled"

KNOWN_STATUSES: Final[frozenset[str]] = frozenset(
    {
        ON_TIME_STATUS,
        DELAYED_STATUS,
        EXCEPTION_STATUS,
        IN_TRANSIT_STATUS,
        CANCELED_STATUS,
    }
)

#: Orders that completed a delivery, on time or late. This is the denominator
#: for on-time rate and delay rate, and excludes ``exception`` deliberately.
DELIVERED_STATUSES: Final[frozenset[str]] = frozenset({ON_TIME_STATUS, DELAYED_STATUS})

#: Orders that carry a usable delivery date. Wider than DELIVERED_STATUSES
#: because an ``exception`` order that did arrive still has a real elapsed
#: delivery time; see AVG_DELIVERY_TIME_INCLUSION below.
DELIVERY_DATED_STATUSES: Final[frozenset[str]] = DELIVERED_STATUSES | {EXCEPTION_STATUS}

DELIVERED_INCLUSION: Final = (
    "status in (delivered, delayed); exception, in_transit and canceled excluded"
)
AVG_DELIVERY_TIME_INCLUSION: Final = (
    "rows with a delivery date: status in (delivered, delayed, exception). "
    "Wider than Delivered Orders on purpose - elapsed delivery time is a real "
    "measurement for an exception order that arrived, whereas an on-time/late "
    "rate would not be"
)
ALL_ORDERS_INCLUSION: Final = "every order matching the active filters"


def delivered_mask(frame: pd.DataFrame) -> pd.Series:
    """Rows counted as Delivered Orders (on-time or late)."""

    return frame["status"].isin(DELIVERED_STATUSES)


def delivery_dated_mask(frame: pd.DataFrame) -> pd.Series:
    """Rows with a usable delivery date, including ``exception``."""

    return frame["status"].isin(DELIVERY_DATED_STATUSES) & frame["delivery_date"].notna()


def on_time_mask(frame: pd.DataFrame) -> pd.Series:
    return frame["status"].eq(ON_TIME_STATUS)


def delayed_mask(frame: pd.DataFrame) -> pd.Series:
    return frame["status"].eq(DELAYED_STATUS)
