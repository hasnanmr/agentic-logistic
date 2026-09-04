"""Follow-up questions: replayed history and server-side conversation threads.

There are two ways to continue a conversation. A stateless client replays prior
turns with each request, bounded at 10 turns, and the server keeps nothing. A
client that sends back the ``thread_id`` from the previous response lets the
agent's checkpointer hold the conversation instead, and can drop history
entirely. Both are asserted here, against the real graph.
"""

from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from backend.agents.agent import MAX_HISTORY_TURNS, build_agent
from backend.core.ingestion import load_dataset
from backend.main import app
from backend.agents.orchestrator import QUERY_TOOL, answer_question
from backend.tests.scripted_model import ScriptedChatModel, ToolCall, script_for


CREDENTIALS = {"APP_USERNAME": "reviewer", "APP_PASSWORD": "s3cret"}


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key, value in CREDENTIALS.items():
        monkeypatch.setenv(key, value)
    return TestClient(app)


@pytest.fixture()
def auth() -> tuple[str, str]:
    return (CREDENTIALS["APP_USERNAME"], CREDENTIALS["APP_PASSWORD"])


def declining_agent() -> tuple[Any, ScriptedChatModel]:
    """An agent whose model calls no tool, so only the prompt matters."""

    model = ScriptedChatModel(script=script_for(None))
    return build_agent(model), model


def _messages(index: int) -> list[dict[str, str]]:
    """One exchange in the role/content shape the orchestrator consumes."""

    return [
        {"role": "user", "content": f"question {index}?"},
        {"role": "assistant", "content": f"answer {index}."},
    ]


def conversation_seen(model: ScriptedChatModel) -> list[tuple[str, str]]:
    """The user/assistant turns the model was shown, in order.

    The system prompt and the agent's own scaffolding messages are dropped, so
    the assertion is about the conversation rather than the harness.
    """

    return [
        ("user" if isinstance(message, HumanMessage) else "assistant", message.text)
        for message in model.seen[0]
        if isinstance(message, (HumanMessage, AIMessage))
    ]


def test_history_reaches_the_model_in_order(dataset: pd.DataFrame) -> None:
    agent, model = declining_agent()

    answer_question(
        "follow up?", agent, dataset, history=[*_messages(1), *_messages(2)]
    )

    seen = conversation_seen(model)
    assert [role for role, _ in seen] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert seen[0][1] == "question 1?"
    assert seen[-2][1] == "answer 2."
    assert seen[-1][1] == "follow up?"


def test_history_is_bounded_to_the_last_ten_turns(dataset: pd.DataFrame) -> None:
    agent, model = declining_agent()
    history = [message for index in range(1, 15) for message in _messages(index)]

    answer_question("follow up?", agent, dataset, history=history)

    seen = conversation_seen(model)
    # Ten prior turns of two messages each, plus the new question.
    assert len(seen) == 2 * MAX_HISTORY_TURNS + 1
    contents = [text for _, text in seen]
    assert "question 5?" in contents
    assert "question 4?" not in contents
    assert seen[0][0] == "user"


def test_empty_history_defaults_to_just_the_question(dataset: pd.DataFrame) -> None:
    agent, model = declining_agent()

    answer_question("which carrier is slowest?", agent, dataset)

    assert conversation_seen(model) == [("user", "which carrier is slowest?")]


def test_request_rejects_more_than_ten_turns(
    client: TestClient, auth: tuple[str, str]
) -> None:
    payload = {
        "question": "follow up?",
        "history": [
            {"question": f"question {index}?", "answer": f"answer {index}."}
            for index in range(MAX_HISTORY_TURNS + 1)
        ],
    }

    response = client.post("/api/ask", json=payload, auth=auth)

    assert response.status_code == 422


def test_request_accepts_exactly_ten_turns(
    client: TestClient,
    auth: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep this contract test independent of provider credentials and network.
    agent, _ = declining_agent()
    monkeypatch.setattr("backend.api.ask.get_agent", lambda: agent)

    payload = {
        "question": "follow up?",
        "history": [
            {"question": f"question {index}?", "answer": f"answer {index}."}
            for index in range(MAX_HISTORY_TURNS)
        ],
    }

    response = client.post("/api/ask", json=payload, auth=auth)

    # A malformed request would be 422 before the stub is reached.
    assert response.status_code == 200


# --- server-side threads ----------------------------------------------------


def test_a_thread_id_is_returned_so_the_client_can_continue(
    dataset: pd.DataFrame,
) -> None:
    agent, _ = declining_agent()

    response = answer_question("which carrier is slowest?", agent, dataset)

    assert response.thread_id
    assert response.thread_id.startswith("ask-")


def test_a_thread_carries_the_conversation_without_replayed_history(
    dataset: pd.DataFrame,
) -> None:
    """The second question sees the first one without the client resending it."""

    model = ScriptedChatModel(
        script=[
            *script_for(ToolCall(QUERY_TOOL, {"metric": "total_orders"})),
            *script_for(ToolCall(QUERY_TOOL, {"metric": "delayed_orders"})),
        ]
    )
    agent = build_agent(model)

    first = answer_question("how many orders?", agent, dataset)
    answer_question(
        "and how many were late?", agent, dataset, thread_id=first.thread_id
    )

    # The model's second run opens on the whole thread, not just the new turn.
    follow_up = [
        message.text
        for message in model.seen[-1]
        if isinstance(message, HumanMessage)
    ]
    assert follow_up == ["how many orders?", "and how many were late?"]


def test_a_thread_id_is_echoed_back_unchanged(dataset: pd.DataFrame) -> None:
    agent, _ = declining_agent()

    response = answer_question(
        "follow up?", agent, dataset, thread_id="ask-fixed-thread"
    )

    assert response.thread_id == "ask-fixed-thread"
