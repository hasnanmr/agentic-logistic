"""CSV ingestion into an in-memory, read-only pandas DataFrame.

400 rows over a single CSV is not an analytical-database workload, so there is
no query engine here (PRD 13). The DataFrame is loaded once and never mutated,
which is the whole of the read-only guarantee in NFR-02 - there is no write
path to disable.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Final

import pandas as pd

from backend.status_rules import KNOWN_STATUSES


DEFAULT_CSV_PATH: Final = "mock_logistics_data.csv"

DATE_COLUMNS: Final[tuple[str, ...]] = ("order_date", "delivery_date")

DATE_FORMAT: Final = "%Y-%m-%d"

#: Columns the application actually reads. The source file carries more
#: (sku, unit_price_usd, is_promo, ...); those are ignored rather than required.
REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "order_id",
    "order_date",
    "delivery_date",
    "status",
    "carrier",
    "origin_city",
    "destination_city",
    "region",
    "product_category",
    "quantity",
)


class DatasetError(RuntimeError):
    """Raised when the source CSV cannot be trusted for analysis."""


def _resolve_path(path: str | os.PathLike[str] | None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get("DATA_CSV_PATH", DEFAULT_CSV_PATH))


def load_dataset(path: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    """Read and validate the logistics CSV.

    Raises:
        DatasetError: if the file is missing, is missing required columns,
            carries a delivery date before its order date, or contains
            duplicate order identifiers.
    """

    csv_path = _resolve_path(path)
    if not csv_path.is_file():
        raise DatasetError(f"dataset not found at {csv_path}")

    frame = pd.read_csv(csv_path)

    # Validate columns before parsing dates: letting read_csv(parse_dates=...)
    # fail first would surface a pandas KeyError instead of this message.
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DatasetError(f"dataset is missing required columns: {', '.join(missing)}")

    # Explicit format rather than inference (PRD 7.1); empty cells become NaT,
    # which is how undelivered orders are represented.
    for column in DATE_COLUMNS:
        try:
            frame[column] = pd.to_datetime(frame[column], format=DATE_FORMAT)
        except (ValueError, TypeError) as error:
            raise DatasetError(
                f"column '{column}' contains values that are not {DATE_FORMAT} dates"
            ) from error

    # An order cannot be delivered before it was placed. Without this guard a
    # reversed pair parses fine and produces a *negative* elapsed time, which
    # silently drags Average Delivery Time down instead of failing. NaT
    # compares False, so the 30 undelivered rows are unaffected.
    reversed_dates = int((frame["delivery_date"] < frame["order_date"]).sum())
    if reversed_dates:
        raise DatasetError(
            f"dataset contains {reversed_dates} rows whose delivery_date "
            "precedes their order_date"
        )

    duplicates = int(frame["order_id"].duplicated().sum())
    if duplicates:
        # The supplied file has 400/400 unique ids; this guard exists so a
        # different file cannot silently double-count orders.
        raise DatasetError(f"dataset contains {duplicates} duplicate order_id values")

    unknown_statuses = sorted(set(frame["status"].unique()) - KNOWN_STATUSES)
    if unknown_statuses:
        raise DatasetError(
            "dataset contains unmapped status values: " + ", ".join(unknown_statuses)
        )

    return frame


@lru_cache(maxsize=1)
def get_dataset() -> pd.DataFrame:
    """Return the process-wide dataset, loading it on first use."""

    return load_dataset()


def describe_dataset(frame: pd.DataFrame) -> dict[str, object]:
    """Small ingestion summary, useful for the README and for smoke checks."""

    delivery_dated = frame["delivery_date"].notna()
    return {
        "row_count": int(len(frame)),
        "order_date_min": frame["order_date"].min().date().isoformat(),
        "order_date_max": frame["order_date"].max().date().isoformat(),
        "rows_with_delivery_date": int(delivery_dated.sum()),
        "rows_without_delivery_date": int((~delivery_dated).sum()),
        "status_counts": {
            str(status): int(count)
            for status, count in frame["status"].value_counts().items()
        },
    }
