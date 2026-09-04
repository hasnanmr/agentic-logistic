"""Is the number right, not just unchanged?

The rest of the suite pins each KPI to a hard-coded expectation. That catches a
regression, but it cannot catch a definition that was wrong from the start: the
expectation was read off the same implementation it now guards, so a mistake in
``metrics.py`` and the value it produces agree with each other for ever.

So this module checks the numbers three ways, and the three have to meet:

1. an **oracle** that recomputes every KPI straight from the CSV with the
   standard library only - no pandas, no application code - transcribed from
   the definitions in PRD 8 rather than from ``metrics.py``;
2. the **metric registry** the whole application computes through;
3. the **pinned values** in ``test_metrics.py`` and in the frontend fixtures.

A disagreement between (1) and (2) means the spec and the code have parted
company, which is the failure the golden values are blind to.

The second half sweeps NFR-01 - dashboard and agent must return identical
numbers - across every metric and every dimension either path will accept,
rather than the three hand-picked cases in ``test_reconciliation.py``.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.agents.agent import build_agent
from backend.tools.agent import QUERY_TOOL
from backend.core.ingestion import load_dataset
from backend.main import app
from backend.core.metrics import METRICS, get_metric
from backend.agents.orchestrator import answer_question
from backend.tests.scripted_model import ScriptedChatModel, ToolCall, script_for


CSV_PATH: Final = Path("mock_logistics_data.csv")
CREDENTIALS: Final = {"APP_USERNAME": "reviewer", "APP_PASSWORD": "s3cret"}

# Transcribed from PRD 7/8 and the status profile in `status_rules`, on purpose
# *not* imported from it: an oracle that reuses the definitions it audits
# proves nothing.
ORACLE_DELIVERED: Final = frozenset({"delivered", "delayed"})
ORACLE_DELIVERY_DATED: Final = frozenset({"delivered", "delayed", "exception"})
ORACLE_ON_TIME: Final = "delivered"


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset(CSV_PATH)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key, value in CREDENTIALS.items():
        monkeypatch.setenv(key, value)
    return TestClient(app)


@pytest.fixture()
def auth() -> tuple[str, str]:
    return (CREDENTIALS["APP_USERNAME"], CREDENTIALS["APP_PASSWORD"])


# --- the oracle -------------------------------------------------------------


def _parse_day(value: str) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def _percent(numerator: int, denominator: int) -> float | None:
    """Per PRD 8: a percentage to two decimals, undefined on an empty base."""

    return round(numerator / denominator * 100, 2) if denominator else None


def oracle_metrics(csv_path: Path = CSV_PATH) -> dict[str, float | int | None]:
    """Every KPI, recomputed from the raw file with the standard library.

    Deliberately plain: a dict reader, a few loops and integer arithmetic. If
    this and the registry ever disagree, one of them has drifted from the
    documented definition and the pinned values cannot tell you which.
    """

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    statuses = [row["status"] for row in rows]
    delivered = sum(1 for status in statuses if status in ORACLE_DELIVERED)
    delayed = sum(1 for status in statuses if status == "delayed")
    on_time = sum(1 for status in statuses if status == ORACLE_ON_TIME)

    elapsed_days = [
        (_parse_day(row["delivery_date"]) - _parse_day(row["order_date"])).days
        for row in rows
        if row["status"] in ORACLE_DELIVERY_DATED and row["delivery_date"]
    ]

    return {
        "total_orders": len({row["order_id"] for row in rows}),
        "delivered_orders": delivered,
        "delayed_orders": delayed,
        "on_time_rate": _percent(on_time, delivered),
        "delay_rate": _percent(delayed, delivered),
        "avg_delivery_time": (
            round(sum(elapsed_days) / len(elapsed_days), 2) if elapsed_days else None
        ),
        "order_demand": len(rows),
    }


def oracle_basis_counts(csv_path: Path = CSV_PATH) -> dict[str, int]:
    """The population each formula operates on, counted the same plain way."""

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    return {
        "all": len(rows),
        "delivered": sum(1 for row in rows if row["status"] in ORACLE_DELIVERED),
        "delivery_dated": sum(
            1
            for row in rows
            if row["status"] in ORACLE_DELIVERY_DATED and row["delivery_date"]
        ),
    }


@pytest.mark.parametrize("metric_name", sorted(METRICS))
def test_the_registry_agrees_with_an_independent_recomputation(
    dataset: pd.DataFrame, metric_name: str
) -> None:
    """The check the golden values cannot make: is the definition right?"""

    assert get_metric(metric_name).compute(dataset) == oracle_metrics()[metric_name]


def test_the_oracle_covers_every_frozen_metric() -> None:
    """A metric added without an oracle entry would slip past the test above."""

    assert set(oracle_metrics()) == set(METRICS)


def test_the_deliberate_denominator_gap_is_real_not_a_typo(
    dataset: pd.DataFrame,
) -> None:
    """Average Delivery Time counts 11 more rows than Delivered Orders.

    PRD 8 wants exactly that - an `exception` order that arrived has a real
    elapsed time but no meaningful on-time verdict - so the gap is confirmed
    against the raw file rather than assumed.
    """

    counted = oracle_basis_counts()

    assert get_metric("delivered_orders").basis_count(dataset) == counted["delivered"]
    assert (
        get_metric("avg_delivery_time").basis_count(dataset)
        == counted["delivery_dated"]
    )
    assert counted["delivery_dated"] - counted["delivered"] == 11


def test_rates_share_the_delivered_denominator(dataset: pd.DataFrame) -> None:
    """On-time and delay are complements, so they must sum to 100%."""

    counted = oracle_metrics()

    assert counted["on_time_rate"] + counted["delay_rate"] == pytest.approx(100.0)
    assert counted["delivered_orders"] == counted["delayed_orders"] + round(
        counted["on_time_rate"] / 100 * counted["delivered_orders"]
    )


# --- the pinned values, and their copy in the frontend ----------------------


FRONTEND_FIXTURES: Final = Path("frontend/lib/fixtures.ts")


def frontend_ground_truth() -> dict[str, float]:
    """The KPI values the frontend ships for its no-backend fixtures mode."""

    source = FRONTEND_FIXTURES.read_text(encoding="utf-8")
    block = re.search(
        r"GROUND_TRUTH:\s*Record<MetricName,\s*number>\s*=\s*\{(.*?)\}",
        source,
        re.DOTALL,
    )
    assert block is not None, "GROUND_TRUTH not found in frontend/lib/fixtures.ts"
    return {
        name: float(value)
        for name, value in re.findall(r"(\w+):\s*([\d.]+)", block.group(1))
    }


@pytest.mark.skipif(
    not FRONTEND_FIXTURES.exists(), reason="frontend not present in this checkout"
)
def test_the_frontends_fixture_values_match_the_backend(
    dataset: pd.DataFrame,
) -> None:
    """A second copy of the numbers is a second thing that can go stale.

    Fixtures mode renders the dashboard with no backend, so these values are
    what a reviewer sees. Nothing else in either suite notices when a metric
    definition moves and this copy does not.
    """

    shipped = frontend_ground_truth()

    assert set(shipped) == set(METRICS), "frontend fixtures cover a different metric set"
    for metric_name, value in sorted(shipped.items()):
        assert value == get_metric(metric_name).compute(dataset), metric_name


# --- NFR-01 across the whole grammar ----------------------------------------


def sweep_cases() -> list[tuple[str, list[str]]]:
    """Every metric, on its own and by each dimension it approves."""

    cases: list[tuple[str, list[str]]] = []
    for metric_name, metric in sorted(METRICS.items()):
        cases.append((metric_name, []))
        cases.extend(
            (metric_name, [dimension])
            for dimension in sorted(metric.allowed_dimensions)
        )
    return cases


def agent_calling(request: dict[str, Any]):
    """An agent whose model makes exactly the tool call under test."""

    return build_agent(ScriptedChatModel(script=script_for(ToolCall(QUERY_TOOL, request))))


def dashboard_rows(client: TestClient, auth: tuple[str, str], request: dict[str, Any]):
    response = client.post("/api/query", json=request, auth=auth)
    assert response.status_code == 200, response.text
    return response.json()["rows"]


def agent_rows(dataset: pd.DataFrame, request: dict[str, Any]):
    """The agent's table, serialised the way the wire would serialise it.

    In process a date cell is a ``datetime.date``; over HTTP the same cell is
    an ISO string. Comparing the JSON form of both keeps the assertion about
    the numbers rather than about pydantic.
    """

    filter_values = [
        str(value)
        for request_filter in request.get("filters", [])
        for value in (
            request_filter["value"]
            if isinstance(request_filter["value"], list)
            else [request_filter["value"]]
        )
    ]
    response = answer_question(
        "sweep " + " ".join(filter_values), agent_calling(request), dataset
    )
    assert response.unsupported is False, response.unsupported_reason
    assert response.table is not None
    return response.table.model_dump(mode="json")["rows"]


@pytest.mark.parametrize(
    ("metric_name", "dimensions"),
    sweep_cases(),
    ids=lambda value: value if isinstance(value, str) else "-".join(value) or "scalar",
)
def test_dashboard_and_agent_return_identical_rows(
    client: TestClient,
    auth: tuple[str, str],
    dataset: pd.DataFrame,
    metric_name: str,
    dimensions: list[str],
) -> None:
    """NFR-01, swept rather than sampled.

    The two paths share `metrics.py`, so this cannot drift while that holds -
    which is the point: the test fails the moment someone gives either path a
    computation of its own.
    """

    request: dict[str, Any] = {
        "operation": "query",
        "metric": metric_name,
        "dimensions": dimensions,
        # Above every group count in this dataset, so neither side truncates.
        "limit": 1000,
    }

    assert agent_rows(dataset, request) == dashboard_rows(client, auth, request)


@pytest.mark.parametrize(
    "extra",
    [
        {"filters": [{"field": "carrier", "op": "eq", "value": "FedEx"}]},
        {"filters": [{"field": "region", "op": "in", "value": ["UK", "EU"]}]},
        {"time_range": {"preset": "previous_month"}},
        {"time_range": {"preset": "last_3_months"}},
        {"time_range": {"start": "2025-03-01", "end": "2025-05-31"}},
        {"sort": {"by": "delay_rate", "direction": "desc"}, "limit": 3},
    ],
    ids=["carrier-eq", "region-in", "previous-month", "last-3-months", "explicit", "ranked"],
)
def test_dashboard_and_agent_agree_once_narrowed(
    client: TestClient,
    auth: tuple[str, str],
    dataset: pd.DataFrame,
    extra: dict[str, Any],
) -> None:
    """Filters, presets and ranking are resolved once, not once per path."""

    request: dict[str, Any] = {
        "operation": "query",
        "metric": "delay_rate",
        "dimensions": ["carrier"],
        "limit": 1000,
        **extra,
    }

    assert agent_rows(dataset, request) == dashboard_rows(client, auth, request)


def test_the_explained_preview_is_the_table_the_user_was_shown(
    dataset: pd.DataFrame,
) -> None:
    """The trace panel must quote the answer's own numbers, not recompute them."""

    request = {
        "operation": "query",
        "metric": "delay_rate",
        "dimensions": ["carrier"],
        "limit": 1000,
    }

    response = answer_question("sweep", agent_calling(request), dataset)
    result = response.results[0]

    assert result.explainability.result_preview.rows == result.table.rows


def test_the_chart_plots_the_table_it_was_built_from(dataset: pd.DataFrame) -> None:
    """A chart that disagreed with its table would be the worst kind of wrong."""

    request = {
        "operation": "query",
        "metric": "delay_rate",
        "dimensions": ["carrier"],
        "limit": 1000,
    }

    response = answer_question("sweep", agent_calling(request), dataset)
    result = response.results[0]

    plotted = [
        [point[column] for column in result.table.columns] for point in result.chart.data
    ]
    assert plotted == [list(row) for row in result.table.rows]
