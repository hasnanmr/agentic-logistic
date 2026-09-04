"""Greetings are answered from templates, never by the model.

The point of the layer is what it costs: no model call, no credentials, no
latency. So the tests check both the reply and the fact that the agent was
never reached - and, just as important, that a greeting glued to a real
question still goes to the agent.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.agents.orchestrator import answer_question
from backend.core.smalltalk import compose_smalltalk_answer, is_smalltalk


AUTH = ("reviewer", "s3cret")


class ExplodingAgent:
    """Stands in for the agent; fails the test if a greeting reaches it."""

    def invoke(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("a greeting must not reach the agent")


@pytest.mark.parametrize(
    ("question", "intent", "language"),
    [
        ("Halo", "hello", "id"),
        ("Halo selamat pagi", "morning", "id"),
        ("Halo selamat siang", "noon", "id"),
        ("Selamat sore", "afternoon", "id"),
        ("Halo, selamat malam!", "evening", "id"),
        ("apa kabar?", "hello", "id"),
        ("Makasih ya kak", "thanks", "id"),
        ("Hello", "hello", "en"),
        ("hi there", "hello", "en"),
        ("Good morning!", "morning", "en"),
        ("Good evening", "evening", "en"),
        ("thank you very much", "thanks", "en"),
        ("Bye", "farewell", "en"),
        ("你好", "hello", "zh"),
        ("早上好", "morning", "zh"),
        ("晚上好！", "evening", "zh"),
        ("谢谢", "thanks", "zh"),
    ],
)
def test_greetings_are_recognised_with_their_language(
    question: str, intent: str, language: str
) -> None:
    match = compose_smalltalk_answer(question)

    assert match is not None
    assert (match.intent, match.language) == (intent, language)
    assert match.reply


def test_time_of_day_wins_over_the_bare_hello() -> None:
    """"Halo selamat pagi" is answered as a morning greeting, not a hello."""

    match = compose_smalltalk_answer("Halo selamat pagi")

    assert match is not None
    assert match.reply.startswith("Halo, selamat pagi!")


def test_reply_is_written_in_the_language_of_the_greeting() -> None:
    assert "delivery analytics" in (compose_smalltalk_answer("Hi").reply)
    assert "asisten analitik" in (compose_smalltalk_answer("Halo").reply)
    assert "物流分析助手" in (compose_smalltalk_answer("你好").reply)


def test_stretched_and_decorated_spellings_still_match() -> None:
    for greeting in ("Haloooo!!!", "hellooo", "Hai 👋", "hey!!"):
        assert is_smalltalk(greeting), greeting


@pytest.mark.parametrize(
    "question",
    [
        "Hi, which carrier has the highest delay rate?",
        "Halo, berapa order minggu lalu?",
        "你好，上个月有多少订单",
        "Good morning report",
        "Forecast demand for the next 4 weeks.",
        "ok",
        "",
    ],
)
def test_real_questions_are_left_to_the_agent(question: str) -> None:
    """A greeting attached to a question is a question."""

    assert not is_smalltalk(question)
    assert compose_smalltalk_answer(question) is None


def test_greeting_answers_without_calling_the_agent() -> None:
    response = answer_question("Selamat pagi", ExplodingAgent())

    assert response.unsupported is False
    assert response.smalltalk is not None
    assert response.smalltalk.intent == "morning"
    assert response.smalltalk.language == "id"
    assert response.results == []
    assert response.explainability is None
    assert response.answer.startswith("Halo, selamat pagi!")


def test_greeting_keeps_the_conversation_thread() -> None:
    response = answer_question("Halo", ExplodingAgent(), thread_id="ask-123")

    assert response.thread_id == "ask-123"


class TestGreetingEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("APP_USERNAME", AUTH[0])
        monkeypatch.setenv("APP_PASSWORD", AUTH[1])
        return TestClient(app)

    def test_greeting_needs_no_model_credentials(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 503 a missing key earns a real question must not reach a hello."""

        monkeypatch.delenv("LLM_API_KEY", raising=False)

        response = client.post(
            "/api/ask", json={"question": "Halo selamat pagi"}, auth=AUTH
        )

        assert response.status_code == 200
        body = response.json()
        assert body["unsupported"] is False
        assert body["smalltalk"] == {"intent": "morning", "language": "id"}
        assert body["chart"] is None and body["table"] is None
