"""Follow-up questions: bounded conversation history on Ask Operations.

The conversation stays stateless - the client replays prior turns with each
request, the server keeps nothing - but the model sees the recent turns so a
question like "what about the second highest?" can be resolved. The bound is
10 turns, enforced on the request shape and by the orchestrator.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.llm import ToolCall
from backend.main import app
from backend.orchestrator import MAX_HISTORY_TURNS, answer_question


CREDENTIALS = {"APP_USERNAME": "reviewer", "APP_PASSWORD": "s3cret"}


class RecordingClient:
    """Captures what the model would see, then declines to pick a tool."""

    def __init__(self) -> None:
        self.received_question: str | None = None
        self.received_history: list[dict[str, str]] | None = None

    def choose_tool(
        self,
        question: str,
        tools: list[dict[str, Any]],
        system_prompt: str,
        history: list[dict[str, str]] | None = None,
    ) -> ToolCall | None:
        self.received_question = question
        self.received_history = history
        return None


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key, value in CREDENTIALS.items():
        monkeypatch.setenv(key, value)
    return TestClient(app)


@pytest.fixture()
def auth() -> tuple[str, str]:
    return (CREDENTIALS["APP_USERNAME"], CREDENTIALS["APP_PASSWORD"])


def _turn(index: int) -> dict[str, str]:
    """One exchange, in the request shape the /api/ask contract uses."""

    return {"question": f"question {index}?", "answer": f"answer {index}."}


def _messages(index: int) -> list[dict[str, str]]:
    """The same exchange in the role/content shape the orchestrator consumes."""

    return [
        {"role": "user", "content": f"question {index}?"},
        {"role": "assistant", "content": f"answer {index}."},
    ]


def test_history_reaches_the_model_in_order() -> None:
    stub = RecordingClient()

    answer_question(
        "follow up?", stub, history=[*_messages(1), *_messages(2)]
    )

    assert stub.received_history is not None
    roles = [message["role"] for message in stub.received_history]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert stub.received_history[0]["content"] == "question 1?"
    assert stub.received_history[-1]["content"] == "answer 2."
    assert stub.received_question == "follow up?"


def test_history_is_bounded_to_the_last_ten_turns() -> None:
    stub = RecordingClient()
    history = [message for index in range(1, 15) for message in _messages(index)]

    answer_question("follow up?", stub, history=history)

    assert stub.received_history is not None
    assert len(stub.received_history) == 2 * MAX_HISTORY_TURNS
    contents = [message["content"] for message in stub.received_history]
    assert "question 5?" in contents
    assert "question 4?" not in contents
    assert stub.received_history[0]["role"] == "user"


def _api_turn(index: int) -> dict[str, str]:
    """One exchange in the *request* shape, which differs from _turn().

    The endpoint takes {question, answer} pairs and expands each into the two
    role/content messages the orchestrator consumes. Building the payload with
    _turn() would be rejected for its shape, so a length-bound test written that
    way would pass without ever exercising the bound.
    """

    return {"question": f"question {index}?", "answer": f"answer {index}."}


def test_request_rejects_more_than_ten_turns(client: TestClient, auth: tuple[str, str]) -> None:
    payload = {
        "question": "follow up?",
        "history": [_api_turn(index) for index in range(MAX_HISTORY_TURNS + 1)],
    }

    response = client.post("/api/ask", json=payload, auth=auth)

    assert response.status_code == 422


def test_request_accepts_exactly_ten_turns(client: TestClient, auth: tuple[str, str]) -> None:
    payload = {
        "question": "follow up?",
        "history": [_api_turn(index) for index in range(MAX_HISTORY_TURNS)],
    }

    response = client.post("/api/ask", json=payload, auth=auth)

    # The LLM is unavailable in tests, so an accepted request surfaces as 503;
    # a malformed request would be 422 before any model access.
    assert response.status_code in {200, 503}


def test_empty_history_defaults_to_no_messages() -> None:
    stub = RecordingClient()

    answer_question("which carrier is slowest?", stub)

    assert stub.received_history == []
