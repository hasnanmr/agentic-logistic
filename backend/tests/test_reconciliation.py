"""Wave 2, I.5: reconciliation between the dashboard path and Ask Operations.

NFR-01 requires that the same metric with the same filters returns identical
numbers whether it reaches the metric registry through ``POST /api/query``
(what the dashboard calls) or through the orchestrator (what Ask Operations
calls). These tests fail if the two paths ever drift apart.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.llm import ToolCall
from backend.main import app
from backend.orchestrator import answer_question


CREDENTIALS = {"APP_USERNAME": "reviewer", "APP_PASSWORD": "s3cret"}


class StubLLMClient:
    """Deterministic stand-in that always selects one tool with fixed arguments."""

    def __init__(self, name: str, arguments: dict[str, Any]) -> None:
        self._name = name
        self._arguments = arguments
        self.received_history: list[dict[str, str]] | None = None

    def choose_tool(
        self,
        question: str,
        tools: list[dict[str, Any]],
        system_prompt: str,
        history: list[dict[str, str]] | None = None,
    ) -> ToolCall | None:
        self.received_history = history
        return ToolCall(name=self._name, arguments=self._arguments)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key, value in CREDENTIALS.items():
        monkeypatch.setenv(key, value)
    return TestClient(app)


@pytest.fixture()
def auth() -> tuple[str, str]:
    return (CREDENTIALS["APP_USERNAME"], CREDENTIALS["APP_PASSWORD"])


DELAY_RATE_BY_CARRIER: dict[str, Any] = {
    "operation": "query",
    "metric": "delay_rate",
    "dimensions": ["carrier"],
    "filters": [{"field": "region", "op": "in", "value": ["US-E", "US-W"]}],
    "sort": {"by": "delay_rate", "direction": "desc"},
    "limit": 5,
}


def test_ranking_numbers_reconcile_between_dashboard_and_ask(
    client: TestClient, auth: tuple[str, str]
) -> None:
    api_result = client.post("/api/query", json=DELAY_RATE_BY_CARRIER, auth=auth)
    assert api_result.status_code == 200
    api_rows = api_result.json()["rows"]

    ask_response = answer_question(
        "Which carrier has the highest delay rate?",
        StubLLMClient("query_tool", DELAY_RATE_BY_CARRIER),
    )

    assert ask_response.unsupported is False
    assert ask_response.table is not None
    assert ask_response.table.rows == api_rows
    assert ask_response.explainability is not None
    assert ask_response.explainability.result_preview.rows == api_rows


def test_scalar_kpi_reconciles_between_dashboard_and_ask(
    client: TestClient, auth: tuple[str, str]
) -> None:
    scalar_request = {
        "operation": "query",
        "metric": "on_time_rate",
        "filters": [{"field": "carrier", "op": "eq", "value": "UPS"}],
    }

    api_result = client.post("/api/query", json=scalar_request, auth=auth)
    assert api_result.status_code == 200
    api_rows = api_result.json()["rows"]

    ask_response = answer_question(
        "What is the on-time rate for UPS?",
        StubLLMClient("query_tool", scalar_request),
    )

    assert ask_response.table is not None
    assert ask_response.table.rows == api_rows
    assert ask_response.answer is not None


def test_grouped_counts_sum_to_the_global_kpi(client: TestClient, auth: tuple[str, str]) -> None:
    """The carrier breakdown the dashboard charts must add up to its KPI card."""

    global_result = client.post(
        "/api/query", json={"operation": "query", "metric": "delivered_orders"}, auth=auth
    )
    grouped_result = client.post(
        "/api/query",
        json={"operation": "query", "metric": "delivered_orders", "dimensions": ["carrier"]},
        auth=auth,
    )
    assert global_result.status_code == grouped_result.status_code == 200

    global_total = global_result.json()["rows"][0][0]
    grouped_total = sum(row[1] for row in grouped_result.json()["rows"])

    assert global_total == grouped_total
