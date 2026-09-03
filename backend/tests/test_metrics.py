"""Stream B1: ingestion and semantic-metric tests.

The headline assertions pin every KPI to an independently computed ground truth
from the real dataset, so a later refactor cannot quietly move a number.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.ingestion import DatasetError, describe_dataset, load_dataset
from backend.metrics import METRICS, get_metric
from backend.schemas import MetricName


GROUND_TRUTH = {
    "total_orders": 400,
    "delivered_orders": 359,
    "delayed_orders": 55,
    "on_time_rate": 84.68,
    "delay_rate": 15.32,
    "avg_delivery_time": 3.83,
}


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


@pytest.mark.parametrize(("metric_name", "expected"), sorted(GROUND_TRUTH.items()))
def test_metric_matches_ground_truth(
    dataset: pd.DataFrame, metric_name: str, expected: float
) -> None:
    assert get_metric(metric_name).compute(dataset) == expected


def test_registry_covers_every_frozen_metric_name() -> None:
    """The registry and the frozen contract literal must not drift apart."""

    assert set(METRICS) == set(MetricName.__args__)


def test_unknown_metric_is_rejected() -> None:
    with pytest.raises(KeyError, match="unknown metric"):
        get_metric("revenue_per_carrier")


def test_delivered_excludes_exception_but_delivery_time_includes_it(
    dataset: pd.DataFrame,
) -> None:
    """The deliberate denominator mismatch from PRD 8, asserted explicitly."""

    delivered = get_metric("delivered_orders")
    delivery_time = get_metric("avg_delivery_time")

    assert delivered.basis_count(dataset) == 359
    assert delivery_time.basis_count(dataset) == 370
    assert "n=370" in delivery_time.describe(dataset)


def test_status_derived_metrics_do_not_approve_status_as_a_dimension() -> None:
    """Grouping a rate by status would be degenerate (always 100% or 0%)."""

    assert "status" not in get_metric("delay_rate").allowed_dimensions
    assert "status" not in get_metric("on_time_rate").allowed_dimensions
    assert "status" in get_metric("total_orders").allowed_dimensions


def test_rates_are_none_on_an_empty_population(dataset: pd.DataFrame) -> None:
    """An empty group must not read as 0% - it has no denominator at all."""

    empty = dataset[dataset["carrier"] == "NoSuchCarrier"]

    assert get_metric("delay_rate").compute(empty) is None
    assert get_metric("avg_delivery_time").compute(empty) is None
    assert get_metric("total_orders").compute(empty) == 0


def test_metrics_compute_per_group(dataset: pd.DataFrame) -> None:
    """Same definition serves a grouped breakdown, no grouping-aware code."""

    delay_rate = get_metric("delay_rate")
    by_carrier = dataset.groupby("carrier", sort=False).apply(
        delay_rate.compute, include_groups=False
    )

    assert len(by_carrier) == dataset["carrier"].nunique()
    assert by_carrier.dropna().between(0, 100).all()


def test_ingestion_rejects_missing_columns(tmp_path) -> None:
    broken = tmp_path / "broken.csv"
    broken.write_text("order_id,order_date\nORD-1,2025-01-01\n")

    with pytest.raises(DatasetError, match="missing required columns"):
        load_dataset(broken)


def test_ingestion_validates_columns_before_parsing_dates(tmp_path) -> None:
    broken = tmp_path / "missing_columns_with_bad_date.csv"
    broken.write_text("order_id,order_date\nORD-1,not-a-date\n")

    with pytest.raises(DatasetError, match="missing required columns"):
        load_dataset(broken)


def test_ingestion_rejects_duplicate_order_ids(
    dataset: pd.DataFrame, tmp_path
) -> None:
    duplicated = tmp_path / "duplicated.csv"
    pd.concat([dataset.head(2), dataset.head(1)]).to_csv(duplicated, index=False)

    with pytest.raises(DatasetError, match="duplicate order_id"):
        load_dataset(duplicated)


def test_ingestion_rejects_unmapped_status(dataset: pd.DataFrame, tmp_path) -> None:
    tampered = dataset.head(3).copy()
    tampered.loc[tampered.index[0], "status"] = "teleported"
    path = tmp_path / "tampered.csv"
    tampered.to_csv(path, index=False)

    with pytest.raises(DatasetError, match="unmapped status"):
        load_dataset(path)


def test_dataset_summary_matches_profile(dataset: pd.DataFrame) -> None:
    summary = describe_dataset(dataset)

    assert summary["row_count"] == 400
    assert summary["order_date_min"] == "2025-01-01"
    assert summary["order_date_max"] == "2025-12-30"
    assert summary["rows_with_delivery_date"] == 370
    assert summary["status_counts"]["delivered"] == 304
