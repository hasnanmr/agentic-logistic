"""Coverage for every filter operator and the remaining failure branches.

The operator dispatch is LLM-facing: the model chooses the operator, and a
swapped ``gt``/``lt`` or an inverted ``not_in`` would return a wrong table with
no error at all. Each operator is therefore pinned to an independently counted
expectation from the real dataset.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.forecast import run_forecast, weekly_demand_series
from backend.ingestion import DatasetError, load_dataset
from backend.query_tool import (
    PresetTimeRange,
    QueryToolError,
    resolve_time_range,
    run_query,
)
from backend.schemas import ForecastStructuredRequest, QueryStructuredRequest


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


def count_with(dataset: pd.DataFrame, **filter_spec: object) -> int:
    request = QueryStructuredRequest.model_validate(
        {"operation": "query", "metric": "total_orders", "filters": [filter_spec]}
    )
    return run_query(request, dataset).rows[0][0]


@pytest.mark.parametrize(
    ("filter_spec", "expected"),
    [
        ({"field": "carrier", "op": "eq", "value": "FedEx"}, 89),
        ({"field": "carrier", "op": "neq", "value": "FedEx"}, 311),
        ({"field": "region", "op": "in", "value": ["UK", "EU"]}, 135),
        ({"field": "region", "op": "not_in", "value": ["UK", "EU"]}, 265),
        ({"field": "order_date", "op": "gt", "value": "2025-06-30"}, 168),
        ({"field": "order_date", "op": "gte", "value": "2025-07-01"}, 168),
        ({"field": "order_date", "op": "lt", "value": "2025-07-01"}, 232),
        ({"field": "order_date", "op": "lte", "value": "2025-06-30"}, 232),
        ({"field": "delivery_date", "op": "gt", "value": "2025-12-01"}, 26),
    ],
    ids=["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "date-null-safe"],
)
def test_every_operator_matches_an_independent_count(
    dataset: pd.DataFrame, filter_spec: dict[str, object], expected: int
) -> None:
    assert count_with(dataset, **filter_spec) == expected


def test_complementary_operators_partition_the_dataset(dataset: pd.DataFrame) -> None:
    """eq/neq and in/not_in must sum to the whole, catching an inverted mask."""

    assert (
        count_with(dataset, field="carrier", op="eq", value="FedEx")
        + count_with(dataset, field="carrier", op="neq", value="FedEx")
        == 400
    )
    assert (
        count_with(dataset, field="region", op="in", value=["UK", "EU"])
        + count_with(dataset, field="region", op="not_in", value=["UK", "EU"])
        == 400
    )


def test_null_delivery_dates_are_excluded_by_comparison(dataset: pd.DataFrame) -> None:
    """30 orders have no delivery date; a comparison must not count them."""

    above = count_with(dataset, field="delivery_date", op="gt", value="2000-01-01")

    assert above == 370  # every dated row, none of the 30 NaT rows


@pytest.mark.parametrize("operator", ["gt", "gte", "lt", "lte"])
def test_ordering_operators_are_rejected_on_label_fields(
    dataset: pd.DataFrame, operator: str
) -> None:
    """`carrier > 'DHL'` would silently do a lexicographic comparison."""

    with pytest.raises(QueryToolError, match="only supported on date fields"):
        count_with(dataset, field="carrier", op=operator, value="DHL")


def test_ordering_operators_are_rejected_on_forecast_filters(
    dataset: pd.DataFrame,
) -> None:
    request = ForecastStructuredRequest.model_validate(
        {
            "operation": "forecast",
            "metric": "order_demand",
            "grain": "week",
            "horizon_weeks": 4,
            "filters": [{"field": "region", "op": "gt", "value": "EU"}],
        }
    )

    with pytest.raises(QueryToolError, match="only supported on date fields"):
        run_forecast(request, dataset)


def test_previous_week_preset_resolves_to_the_preceding_full_week(
    dataset: pd.DataFrame,
) -> None:
    window = resolve_time_range(
        PresetTimeRange(preset="previous_week"), date(2025, 12, 30)
    )

    assert (window.start, window.end) == (date(2025, 12, 22), date(2025, 12, 28))

    request = QueryStructuredRequest.model_validate(
        {
            "operation": "query",
            "metric": "total_orders",
            "time_range": {"preset": "previous_week"},
        }
    )
    assert run_query(request, dataset).rows[0][0] == 6


def test_last_n_weeks_preset_spans_whole_weeks(dataset: pd.DataFrame) -> None:
    window = resolve_time_range(
        PresetTimeRange(preset="last_2_weeks"), date(2025, 12, 30)
    )

    assert (window.end - window.start).days == 13  # 14 inclusive days


def test_empty_frame_yields_an_empty_demand_series() -> None:
    empty = pd.DataFrame({"order_date": pd.to_datetime([])})

    assert weekly_demand_series(empty).empty


def test_a_span_of_only_partial_weeks_yields_no_series() -> None:
    """Three mid-week days cover no complete Monday-Sunday week."""

    frame = pd.DataFrame(
        {"order_date": pd.to_datetime(["2025-03-05", "2025-03-06", "2025-03-07"])}
    )

    assert weekly_demand_series(frame).empty


def test_missing_dataset_file_is_reported_clearly(tmp_path) -> None:
    with pytest.raises(DatasetError, match="dataset not found"):
        load_dataset(tmp_path / "absent.csv")


def test_malformed_dates_are_reported_against_their_column(
    dataset: pd.DataFrame, tmp_path
) -> None:
    tampered = dataset.head(3).copy()
    tampered["order_date"] = ["2025-01-01", "31/01/2025", "2025-01-03"]
    path = tmp_path / "bad_dates.csv"
    tampered.to_csv(path, index=False)

    with pytest.raises(DatasetError, match="order_date.*not %Y-%m-%d dates"):
        load_dataset(path)
