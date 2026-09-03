"""Stream E: routing, answer composition, explainability, and chart rules.

Every test drives a scripted model through the real deepagents graph, so the
suite needs no API key and still exercises the loop that ships - tool calls,
rejections, retries and all. What the real model does is choose tools and their
arguments; these tests fix that choice and check everything downstream of it.
"""

from __future__ import annotations

from time import sleep
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.chart_rules import forecast_chart, select_chart
from backend.forecast import run_forecast
from backend.ingestion import load_dataset
from backend.agent import build_agent
from backend.main import app
from backend.agent_tools import DECLINE_TOOL
from backend.orchestrator import (
    FORECAST_TOOL,
    QUERY_TOOL,
    answer_question,
    tool_definitions,
)
from backend.query_tool import run_query
from backend.schemas import ForecastStructuredRequest, QueryStructuredRequest
from backend.tests.scripted_model import (
    ScriptedChatModel,
    ToolCall,
    says,
    script_for,
)


AUTH = ("reviewer", "s3cret")


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


def agent_for(*calls: ToolCall | None) -> tuple[Any, ScriptedChatModel]:
    """A real agent graph driven by a model scripted to make ``calls``."""

    model = ScriptedChatModel(script=script_for(*calls))
    return build_agent(model), model


def ask(question: str, call: ToolCall | None, frame: pd.DataFrame):
    agent, _ = agent_for(call)
    return answer_question(question, agent, frame)


# --- tool surface -----------------------------------------------------------


def test_two_tools_are_exposed_and_hide_the_discriminator() -> None:
    """The model picks a tool; it never restates the operation in arguments."""

    tools = tool_definitions()
    names = [tool["function"]["name"] for tool in tools]

    assert names == [QUERY_TOOL, FORECAST_TOOL]
    for tool in tools:
        assert "operation" not in tool["function"]["parameters"]["properties"]
        assert "operation" not in tool["function"]["parameters"].get("required", [])


def test_forecast_tool_advertises_the_horizon_bounds() -> None:
    horizon = tool_definitions()[1]["function"]["parameters"]["properties"][
        "horizon_weeks"
    ]

    assert horizon["minimum"] == 1
    assert horizon["maximum"] == 8


# --- routing and the three spec example questions ---------------------------


def test_ranking_question_answers_with_the_leader(dataset: pd.DataFrame) -> None:
    response = ask(
        "Which carrier has the highest delay rate?",
        ToolCall(
            QUERY_TOOL,
            {
                "metric": "delay_rate",
                "dimensions": ["carrier"],
                "sort": {"by": "delay_rate", "direction": "desc"},
                "limit": 1,
            },
        ),
        dataset,
    )

    assert response.unsupported is False
    assert "highest delay rate" in response.answer
    assert response.answer.endswith("%.")
    assert response.chart.type == "bar"


def test_weekly_trend_question_returns_a_line_chart(dataset: pd.DataFrame) -> None:
    response = ask(
        "Show delayed orders by week for the last 3 months.",
        ToolCall(
            QUERY_TOOL,
            {
                "metric": "delayed_orders",
                "dimensions": ["week"],
                "time_range": {"preset": "last_3_months"},
                "limit": 100,
            },
        ),
        dataset,
    )

    assert response.chart.type == "line"
    assert response.explainability.resolved_filters.time_range.means == "reported_period"


def test_scalar_question_reports_a_single_figure(dataset: pd.DataFrame) -> None:
    response = ask(
        "How many orders were delivered late last month?",
        ToolCall(
            QUERY_TOOL,
            {"metric": "delayed_orders", "time_range": {"preset": "previous_month"}},
        ),
        dataset,
    )

    assert response.chart is None  # a single number is not a chart
    assert response.table.row_count == 1
    assert "Delayed Orders is" in response.answer


def test_forecast_question_routes_to_the_forecast_tool(dataset: pd.DataFrame) -> None:
    response = ask(
        "Forecast order demand for the next 4 weeks.",
        ToolCall(
            FORECAST_TOOL,
            {"metric": "order_demand", "grain": "week", "horizon_weeks": 4},
        ),
        dataset,
    )

    assert response.unsupported is False
    assert "next 4 weeks" in response.answer
    assert response.explainability.forecast_details.horizon_weeks == 4
    assert response.explainability.resolved_filters.time_range.means == "history_window"


# --- the answer never contains a number the tools did not produce ------------


def test_answer_numbers_come_from_the_tool_not_the_model(
    dataset: pd.DataFrame,
) -> None:
    request = QueryStructuredRequest.model_validate(
        {"operation": "query", "metric": "on_time_rate"}
    )
    expected = run_query(request, dataset).rows[0][0]

    response = ask(
        "What is the on-time rate?", ToolCall(QUERY_TOOL, {"metric": "on_time_rate"}), dataset
    )

    assert str(expected) in response.answer
    assert response.table.rows == [[expected]]


# --- unsupported paths ------------------------------------------------------


def test_a_declared_decline_becomes_an_explained_refusal(
    dataset: pd.DataFrame,
) -> None:
    """A data question the dataset cannot serve is refused with its reason.

    The agent says so through decline_tool rather than by staying silent, so
    the refusal can quote why and still list what is available (FR-15).
    """

    response = ask(
        "Which carrier is most profitable?",
        ToolCall(DECLINE_TOOL, {"reason": "profit per carrier is not in this dataset"}),
        dataset,
    )

    assert response.unsupported is True
    assert response.explainability is None
    assert "profit per carrier is not in this dataset" in response.unsupported_reason
    assert "Supported metrics" in response.unsupported_reason


def test_a_message_needing_no_tool_is_answered_in_the_agents_own_words(
    dataset: pd.DataFrame,
) -> None:
    """A question about the agent itself is a reply, not a refusal."""

    model = ScriptedChatModel(
        script=[says("I read this delivery dataset. Ask me about delays or demand.")]
    )

    response = answer_question("are you a logistics expert?", build_agent(model), dataset)

    assert response.unsupported is False
    assert response.narrated is True
    assert response.narration == "model"
    assert response.answer.startswith("I read this delivery dataset")


def test_a_figure_the_agent_invented_is_never_printed(dataset: pd.DataFrame) -> None:
    """Prose with an ungrounded number falls back to the explained refusal."""

    model = ScriptedChatModel(script=[says("Yes - we shipped 4210 orders last year.")])

    response = answer_question("are you a logistics expert?", build_agent(model), dataset)

    assert response.unsupported is True
    assert response.narrated is False
    assert "4210" not in (response.unsupported_reason or "")


def test_every_non_greeting_turn_reaches_the_agent_with_every_tool(
    dataset: pd.DataFrame,
) -> None:
    """Anything that is not a template greeting is answered with tools in hand.

    The greeting short-circuit is the only path that skips the agent, so a
    real question must always arrive with the full tool surface bound - the
    two governed analytics tools plus the explicit decline.
    """

    agent, model = agent_for(ToolCall(QUERY_TOOL, {"metric": "total_orders"}))

    answer_question("how many orders are there?", agent, dataset)

    assert set(model.offered_tools) >= {QUERY_TOOL, FORECAST_TOOL, DECLINE_TOOL}


def test_arguments_outside_the_grammar_are_refused(dataset: pd.DataFrame) -> None:
    response = ask(
        "Show me profit by carrier",
        ToolCall(QUERY_TOOL, {"metric": "profit", "dimensions": ["carrier"]}),
        dataset,
    )

    assert response.unsupported is True
    assert "approved query grammar" in response.unsupported_reason


def test_disallowed_dimension_is_refused_with_the_reason(
    dataset: pd.DataFrame,
) -> None:
    response = ask(
        "Break the delay rate down by status",
        ToolCall(QUERY_TOOL, {"metric": "delay_rate", "dimensions": ["status"]}),
        dataset,
    )

    assert response.unsupported is True
    assert "not approved" in response.unsupported_reason


def test_unknown_tool_name_is_refused(dataset: pd.DataFrame) -> None:
    response = ask("do something", ToolCall("sql_tool", {}), dataset)

    assert response.unsupported is True


def test_blank_question_is_refused_without_calling_the_model(
    dataset: pd.DataFrame,
) -> None:
    agent, model = agent_for(ToolCall(QUERY_TOOL, {"metric": "total_orders"}))

    response = answer_question("   ", agent, dataset)

    assert response.unsupported is True
    assert model.calls == 0


# --- explainability ---------------------------------------------------------


def test_every_supported_answer_carries_full_explainability(
    dataset: pd.DataFrame,
) -> None:
    response = ask(
        "Delay rate by carrier",
        ToolCall(QUERY_TOOL, {"metric": "delay_rate", "dimensions": ["carrier"]}),
        dataset,
    )
    explain = response.explainability

    assert explain.question == "Delay rate by carrier"
    assert explain.structured_request.operation == "query"
    assert explain.metric_basis.row_count == 359
    assert "exception" in explain.metric_basis.inclusion_rule
    assert "group by carrier" in explain.query_plan
    assert explain.result_preview.row_count == 9


def test_runtime_is_measured_and_attributed_to_the_model(
    dataset: pd.DataFrame,
) -> None:
    """The panel reports how long the run took, split model vs computation."""

    class SlowModel(ScriptedChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
            sleep(0.05)
            return super()._generate(messages, stop, run_manager, **kwargs)

    model = SlowModel(
        script=script_for(
            ToolCall(QUERY_TOOL, {"metric": "delay_rate", "dimensions": ["carrier"]})
        )
    )

    response = answer_question("Delay rate by carrier", build_agent(model), dataset)
    runtime = response.explainability.runtime

    assert runtime is not None
    assert runtime.model_ms >= 50
    assert runtime.total_ms >= runtime.model_ms
    assert runtime.compute_ms == pytest.approx(
        runtime.total_ms - runtime.model_ms, abs=0.2
    )


def test_unsupported_answers_carry_no_runtime(dataset: pd.DataFrame) -> None:
    """Runtime rides on explainability, which a refusal does not have."""

    response = ask(
        "Why are we losing money?",
        ToolCall(DECLINE_TOOL, {"reason": "profit is not in this dataset"}),
        dataset,
    )

    assert response.unsupported
    assert response.explainability is None


def test_avg_delivery_time_basis_differs_from_delivered_orders(
    dataset: pd.DataFrame,
) -> None:
    """The deliberate denominator gap has to be visible in the payload."""

    response = ask(
        "What is the average delivery time?",
        ToolCall(QUERY_TOOL, {"metric": "avg_delivery_time"}),
        dataset,
    )

    assert response.explainability.metric_basis.row_count == 370
    assert "n=370" in response.explainability.metric_definition


# --- chart rules ------------------------------------------------------------


def test_chart_rules_cover_the_three_cases(dataset: pd.DataFrame) -> None:
    def result_for(**payload: object):
        request = QueryStructuredRequest.model_validate(
            {"operation": "query", **payload}
        )
        return run_query(request, dataset), request.dimensions

    scalar, scalar_dims = result_for(metric="total_orders")
    weekly, weekly_dims = result_for(
        metric="order_demand", dimensions=["week"], limit=1000
    )
    by_carrier, carrier_dims = result_for(metric="delay_rate", dimensions=["carrier"])
    detail, detail_dims = result_for(
        metric="total_orders", dimensions=["carrier", "region"], limit=1000
    )

    assert select_chart(scalar, scalar_dims) is None
    assert select_chart(weekly, weekly_dims).type == "line"
    assert select_chart(by_carrier, carrier_dims).type == "bar"
    assert select_chart(detail, detail_dims) is None


def test_empty_result_gets_no_chart(dataset: pd.DataFrame) -> None:
    request = QueryStructuredRequest.model_validate(
        {
            "operation": "query",
            "metric": "total_orders",
            "dimensions": ["carrier"],
            "filters": [{"field": "region", "op": "eq", "value": "MARS"}],
        }
    )

    assert select_chart(run_query(request, dataset), ["carrier"]) is None


def test_forecast_chart_separates_actual_from_projection(
    dataset: pd.DataFrame,
) -> None:
    request = ForecastStructuredRequest.model_validate(
        {
            "operation": "forecast",
            "metric": "order_demand",
            "grain": "week",
            "horizon_weeks": 4,
        }
    )

    chart = forecast_chart(run_forecast(request, dataset))
    series = {point["series"] for point in chart.data}

    assert chart.type == "line"
    assert series == {"actual", "forecast"}
    assert sum(point["series"] == "forecast" for point in chart.data) == 4


# --- endpoint ---------------------------------------------------------------


class TestAskEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("APP_USERNAME", AUTH[0])
        monkeypatch.setenv("APP_PASSWORD", AUTH[1])
        return TestClient(app)

    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.post("/api/ask", json={"question": "hi"})

        assert response.status_code == 401

    def test_missing_api_key_is_reported_plainly(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        response = client.post(
            "/api/ask", json={"question": "How many orders?"}, auth=AUTH
        )

        assert response.status_code == 503
        assert "LLM_API_KEY" in response.json()["detail"]

    def test_empty_question_is_rejected_by_the_contract(
        self, client: TestClient
    ) -> None:
        response = client.post("/api/ask", json={"question": ""}, auth=AUTH)

        assert response.status_code == 422
