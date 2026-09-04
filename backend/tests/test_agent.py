"""The agent loop: what the deepagents refactor made possible.

The previous design was a single tool choice, so none of this could happen -
one question could not produce two figures, a rejected argument could not be
corrected, and there was no plan to show. Each test drives a scripted model
through the real graph, so it asserts on the loop that ships.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.agents.agent import (
    MAX_MODEL_CALLS,
    SYSTEM_PROMPT,
    build_agent,
    run_agent,
)
from backend.tools.agent import DECLINE_TOOL, FORECAST_TOOL, QUERY_TOOL
from backend.core.ingestion import load_dataset
from backend.agents.orchestrator import answer_question
from backend.tests.scripted_model import (
    ScriptedChatModel,
    ToolCall,
    asks_for,
    says,
    script_for,
)


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


RANKING = ToolCall(
    QUERY_TOOL,
    {
        "metric": "delay_rate",
        "dimensions": ["carrier"],
        "sort": {"by": "delay_rate", "direction": "desc"},
        "limit": 1,
    },
)
FORECAST = ToolCall(
    FORECAST_TOOL, {"metric": "order_demand", "grain": "week", "horizon_weeks": 6}
)


def ask(question: str, script: list, frame: pd.DataFrame):
    return answer_question(question, build_agent(ScriptedChatModel(script=script)), frame)


# --- more than one figure per question --------------------------------------


def test_a_compound_question_produces_one_result_block_per_tool_call(
    dataset: pd.DataFrame,
) -> None:
    response = ask(
        "Which carrier is worst on delays, and what is demand for six weeks?",
        script_for(RANKING, FORECAST),
        dataset,
    )

    assert response.unsupported is False
    assert len(response.results) == 2
    assert [
        result.explainability.structured_request.operation
        for result in response.results
    ] == ["query", "forecast"]


def test_a_compound_answer_concatenates_the_composed_prose(
    dataset: pd.DataFrame,
) -> None:
    """Every sentence is still written by application code, block by block."""

    response = ask(
        "Worst carrier, and demand for six weeks?", script_for(RANKING, FORECAST), dataset
    )

    assert response.narration == "composed"
    assert response.answer == " ".join(
        result.answer for result in response.results
    )
    assert "highest delay rate" in response.answer
    assert "next 6 weeks" in response.answer


def test_legacy_fields_view_the_first_result(dataset: pd.DataFrame) -> None:
    """Single-result clients keep working while `results` carries both."""

    response = ask(
        "Worst carrier, and demand for six weeks?", script_for(RANKING, FORECAST), dataset
    )

    assert response.chart is response.results[0].chart
    assert response.table is response.results[0].table
    assert response.explainability is response.results[0].explainability


def test_both_blocks_share_the_runs_timing(dataset: pd.DataFrame) -> None:
    response = ask(
        "Worst carrier, and demand for six weeks?", script_for(RANKING, FORECAST), dataset
    )

    runtimes = [result.explainability.runtime for result in response.results]
    assert runtimes[0] == runtimes[1]
    assert runtimes[0].total_ms > 0


# --- correcting itself ------------------------------------------------------


def test_a_rejected_argument_can_be_corrected_within_one_run(
    dataset: pd.DataFrame,
) -> None:
    """The loop's real gain: a bad call is explained and retried, not fatal.

    Breaking the delay rate down by status is refused by the query grammar. The
    agent is told why, calls again correctly, and the user still gets an
    answer.
    """

    response = ask(
        "Break the delay rate down",
        [
            asks_for(ToolCall(QUERY_TOOL, {"metric": "delay_rate", "dimensions": ["status"]})),
            asks_for(ToolCall(QUERY_TOOL, {"metric": "delay_rate", "dimensions": ["carrier"]})),
            says("Broke the delay rate down by carrier."),
        ],
        dataset,
    )

    assert response.unsupported is False
    assert len(response.results) == 1
    assert response.results[0].explainability.structured_request.root.dimensions == [
        "carrier"
    ]


def test_the_rejection_reason_is_handed_to_the_model(dataset: pd.DataFrame) -> None:
    model = ScriptedChatModel(
        script=[
            asks_for(ToolCall(QUERY_TOOL, {"metric": "delay_rate", "dimensions": ["status"]})),
            says("I could not break that down."),
        ]
    )

    run = run_agent("Break the delay rate down by status", dataset, agent=build_agent(model))

    assert run.collector.failures
    assert "not approved" in run.collector.failures[-1].reason
    # The model saw the reason on its second turn, which is what lets it retry.
    replayed = "\n".join(message.text for message in model.seen[-1])
    assert "not approved" in replayed


# --- the model still never sees a figure ------------------------------------


def test_tool_receipts_carry_no_computed_figures(dataset: pd.DataFrame) -> None:
    """The receipt names the stored result and its shape, never its values."""

    model = ScriptedChatModel(script=script_for(RANKING))
    run = run_agent("Which carrier is worst?", dataset, agent=build_agent(model))

    leader_value = str(run.collector.results[0].table.rows[0][-1])
    receipts = [
        message.text
        for message in model.seen[-1]
        if type(message).__name__ == "ToolMessage"
    ]

    assert receipts
    assert all(leader_value not in receipt for receipt in receipts)
    assert any("Stored result 1" in receipt for receipt in receipts)


def test_unrequested_filter_is_rejected(dataset: pd.DataFrame) -> None:
    model = ScriptedChatModel(
        script=script_for(
            ToolCall(
                QUERY_TOOL,
                {
                    "metric": "delay_rate",
                    "dimensions": ["carrier"],
                    "filters": [
                        {
                            "field": "region",
                            "op": "in",
                            "value": ["US-E", "US-W"],
                        }
                    ],
                },
            )
        )
    )

    run = run_agent(
        "Which carrier has the highest delay rate?",
        dataset,
        agent=build_agent(model),
    )

    assert not run.collector.results
    assert run.collector.failures
    assert "was not stated by the user" in run.collector.failures[-1].reason


def test_explicit_filter_is_allowed(dataset: pd.DataFrame) -> None:
    response = ask(
        "Which carrier has the highest delay rate in US-E and US-W?",
        script_for(
            ToolCall(
                QUERY_TOOL,
                {
                    "metric": "delay_rate",
                    "dimensions": ["carrier"],
                    "filters": [
                        {
                            "field": "region",
                            "op": "in",
                            "value": ["US-E", "US-W"],
                        }
                    ],
                },
            )
        ),
        dataset,
    )

    assert response.unsupported is False
    assert response.results[0].explainability.resolved_filters.filters


def test_the_dataset_never_enters_the_conversation(dataset: pd.DataFrame) -> None:
    model = ScriptedChatModel(script=script_for(RANKING))
    run_agent("Which carrier is worst?", dataset, agent=build_agent(model))

    transcript = "\n".join(
        message.text for turn in model.seen for message in turn
    )
    # An order id is the most distinctive thing a leaked row would carry.
    assert dataset["order_id"].iloc[0] not in transcript


# --- planning ---------------------------------------------------------------


def test_a_written_plan_is_surfaced_for_the_trace_panel(
    dataset: pd.DataFrame,
) -> None:
    response = ask(
        "Worst carrier, and demand for six weeks?",
        [
            asks_for(
                ToolCall(
                    "write_todos",
                    {
                        "todos": [
                            {"content": "rank carriers by delay rate", "status": "in_progress"},
                            {"content": "forecast six weeks of demand", "status": "pending"},
                        ]
                    },
                )
            ),
            asks_for(RANKING),
            asks_for(FORECAST),
            says("Ranked the carriers and projected demand."),
        ],
        dataset,
    )

    assert [step.content for step in response.plan] == [
        "rank carriers by delay rate",
        "forecast six weeks of demand",
    ]
    assert response.plan[0].status == "in_progress"


def test_a_direct_answer_carries_no_plan(dataset: pd.DataFrame) -> None:
    response = ask("Which carrier is worst?", script_for(RANKING), dataset)

    assert response.plan == []


# --- configuration the endpoint depends on ----------------------------------


def test_the_agent_is_offered_the_delegation_and_planning_tools(
    dataset: pd.DataFrame,
) -> None:
    model = ScriptedChatModel(script=script_for(RANKING))
    run_agent("Which carrier is worst?", dataset, agent=build_agent(model))

    assert {QUERY_TOOL, FORECAST_TOOL, DECLINE_TOOL} <= set(model.offered_tools)
    assert "write_todos" in model.offered_tools
    assert "task" in model.offered_tools  # subagent delegation


def test_the_filesystem_suite_is_cut_to_the_required_minimum(
    dataset: pd.DataFrame,
) -> None:
    """There is no document workspace here, so those tools would only fail."""

    model = ScriptedChatModel(script=script_for(RANKING))
    run_agent("Which carrier is worst?", dataset, agent=build_agent(model))

    assert "write_file" not in model.offered_tools
    assert "glob" not in model.offered_tools
    assert "execute" not in model.offered_tools


def test_a_runaway_loop_is_capped(dataset: pd.DataFrame) -> None:
    """A model that never stops calling tools must not bill for ever."""

    model = ScriptedChatModel(script=[asks_for(RANKING)] * 50)

    run_agent("Which carrier is worst?", dataset, agent=build_agent(model))

    assert model.calls <= MAX_MODEL_CALLS


def test_the_prompt_forbids_stating_a_figure() -> None:
    """The instruction the whole grounding design rests on."""

    assert "never state a number" in SYSTEM_PROMPT
    assert "decline_tool" in SYSTEM_PROMPT
