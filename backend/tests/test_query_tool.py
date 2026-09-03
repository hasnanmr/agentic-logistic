"""Stream B2: query compilation, validation, and time-preset tests."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.ingestion import load_dataset
from backend.main import app
from backend.query_tool import (
    QueryToolError,
    dataset_anchor,
    resolve_time_range,
    run_query,
)
from backend.schemas import ExplicitTimeRange, PresetTimeRange, QueryStructuredRequest


AUTH = ("reviewer", "s3cret")


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


def build(**overrides: object) -> QueryStructuredRequest:
    payload: dict[str, object] = {"operation": "query", "metric": "total_orders"}
    payload.update(overrides)
    return QueryStructuredRequest.model_validate(payload)


def test_scalar_query_matches_ground_truth(dataset: pd.DataFrame) -> None:
    result = run_query(build(metric="delay_rate"), dataset)

    assert result.columns == ["delay_rate"]
    assert result.rows == [[15.32]]
    assert result.row_count == 1
    assert result.resolved_time_range is None


def test_breakdown_covers_every_group_and_reconciles(dataset: pd.DataFrame) -> None:
    result = run_query(build(metric="total_orders", dimensions=["carrier"]), dataset)

    assert result.row_count == dataset["carrier"].nunique()
    assert sum(row[1] for row in result.rows) == 400


def test_ranking_query_sorts_and_limits(dataset: pd.DataFrame) -> None:
    result = run_query(
        build(
            metric="delay_rate",
            dimensions=["carrier"],
            sort={"by": "delay_rate", "direction": "desc"},
            limit=1,
        ),
        dataset,
    )

    assert len(result.rows) == 1
    assert result.truncated is True
    assert result.row_count == 9  # nine carriers considered, one returned


def test_weekly_trend_buckets_are_iso_weeks(dataset: pd.DataFrame) -> None:
    result = run_query(build(metric="order_demand", dimensions=["week"], limit=1000), dataset)

    assert result.row_count == 53
    assert all(row[0].startswith("2025-W") or row[0].startswith("2026-W") for row in result.rows)
    assert sum(row[1] for row in result.rows) == 400


def test_filters_narrow_the_population(dataset: pd.DataFrame) -> None:
    result = run_query(
        build(
            metric="total_orders",
            filters=[{"field": "region", "op": "in", "value": ["UK"]}],
        ),
        dataset,
    )

    assert result.rows == [[54]]


def test_unapproved_dimension_is_rejected_before_computation(
    dataset: pd.DataFrame,
) -> None:
    """delay_rate grouped by status would be trivially 100%/0% per group."""

    with pytest.raises(QueryToolError, match="not approved"):
        run_query(build(metric="delay_rate", dimensions=["status"]), dataset)


def test_sorting_by_an_uncomputed_key_is_rejected(dataset: pd.DataFrame) -> None:
    with pytest.raises(QueryToolError, match="cannot sort by"):
        run_query(
            build(
                metric="total_orders",
                dimensions=["carrier"],
                sort={"by": "region", "direction": "asc"},
            ),
            dataset,
        )


def test_repeated_dimensions_are_rejected(dataset: pd.DataFrame) -> None:
    with pytest.raises(QueryToolError, match="dimensions must not repeat"):
        run_query(
            build(metric="total_orders", dimensions=["carrier", "carrier"]),
            dataset,
        )


def test_empty_result_is_a_clean_zero_row_table(dataset: pd.DataFrame) -> None:
    """A valid query with no matches must not look like a computed zero."""

    result = run_query(
        build(
            metric="total_orders",
            dimensions=["carrier"],
            filters=[{"field": "region", "op": "eq", "value": "ANTARCTICA"}],
        ),
        dataset,
    )

    assert result.rows == []
    assert result.row_count == 0


def test_time_presets_anchor_to_the_dataset_not_the_wall_clock(
    dataset: pd.DataFrame,
) -> None:
    """The data ends 2025-12-30; anchoring to today would empty every preset."""

    anchor = dataset_anchor(dataset)
    assert anchor == date(2025, 12, 30)

    window = resolve_time_range(PresetTimeRange(preset="previous_month"), anchor)
    assert (window.start, window.end) == (date(2025, 11, 1), date(2025, 11, 30))

    result = run_query(
        build(metric="total_orders", time_range={"preset": "previous_month"}), dataset
    )
    assert result.rows[0][0] > 0
    assert result.resolved_time_range.start == date(2025, 11, 1)


def test_last_n_months_preset_resolves_to_concrete_dates(dataset: pd.DataFrame) -> None:
    window = resolve_time_range(
        PresetTimeRange(preset="last_3_months"), dataset_anchor(dataset)
    )

    assert (window.start, window.end) == (date(2025, 10, 1), date(2025, 12, 30))


def test_explicit_time_range_is_passed_through(dataset: pd.DataFrame) -> None:
    window = resolve_time_range(
        ExplicitTimeRange(start=date(2025, 3, 1), end=date(2025, 3, 31)),
        dataset_anchor(dataset),
    )

    assert (window.start, window.end) == (date(2025, 3, 1), date(2025, 3, 31))


class TestQueryEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("APP_USERNAME", AUTH[0])
        monkeypatch.setenv("APP_PASSWORD", AUTH[1])
        monkeypatch.setenv("DATA_CSV_PATH", "mock_logistics_data.csv")
        return TestClient(app)

    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.post(
            "/api/query", json={"operation": "query", "metric": "total_orders"}
        )

        assert response.status_code == 401

    def test_returns_ground_truth_over_http(self, client: TestClient) -> None:
        response = client.post(
            "/api/query",
            json={"operation": "query", "metric": "on_time_rate"},
            auth=AUTH,
        )

        assert response.status_code == 200
        assert response.json()["rows"] == [[84.68]]

    def test_unknown_metric_is_rejected_by_the_contract(self, client: TestClient) -> None:
        response = client.post(
            "/api/query",
            json={"operation": "query", "metric": "profit_margin"},
            auth=AUTH,
        )

        assert response.status_code == 422

    def test_unapproved_dimension_returns_a_readable_400(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/query",
            json={
                "operation": "query",
                "metric": "delay_rate",
                "dimensions": ["status"],
            },
            auth=AUTH,
        )

        assert response.status_code == 400
        assert "not approved" in response.json()["detail"]

    def test_uncomputed_sort_key_returns_a_readable_400(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/query",
            json={
                "operation": "query",
                "metric": "total_orders",
                "dimensions": ["carrier"],
                "sort": {"by": "region", "direction": "asc"},
            },
            auth=AUTH,
        )

        assert response.status_code == 400
        assert "cannot sort by" in response.json()["detail"]

    def test_repeated_dimensions_return_a_readable_400(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/query",
            json={
                "operation": "query",
                "metric": "total_orders",
                "dimensions": ["carrier", "carrier"],
            },
            auth=AUTH,
        )

        assert response.status_code == 400
        assert "must not repeat" in response.json()["detail"]
