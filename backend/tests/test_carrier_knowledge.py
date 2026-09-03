import pytest
from fastapi.testclient import TestClient

from backend.carrier_knowledge import (
    CARRIER_DEFINITIONS,
    compose_carrier_answer,
    is_carrier_knowledge_question,
)
from backend.main import app
from backend.orchestrator import answer_question


AUTH = ("reviewer", "s3cret")


def test_named_carrier_question_uses_the_source_backed_glossary() -> None:
    answer = compose_carrier_answer("Apa itu UPS?")

    assert answer is not None
    text, definitions = answer
    assert len(definitions) == 1
    assert definitions[0].name == "UPS"
    assert "United Parcel Service" in text
    assert definitions[0].source_url in text


def test_each_carrier_question_returns_all_dataset_carriers() -> None:
    answer = compose_carrier_answer("Jelaskan masing-masing carrier")

    assert answer is not None
    _, definitions = answer
    assert [definition.name for definition in definitions] == [
        definition.name for definition in CARRIER_DEFINITIONS
    ]


def test_performance_question_stays_on_the_analytics_path() -> None:
    assert not is_carrier_knowledge_question(
        "Which carrier has the highest delay rate?"
    )


def test_carrier_glossary_does_not_need_an_agent() -> None:
    response = answer_question("Apa itu USPS?")

    assert response.unsupported is False
    assert response.results == []
    assert response.carrier_knowledge is not None
    assert response.carrier_knowledge.items[0].name == "USPS"
    assert response.explainability is None


def test_carrier_glossary_keeps_the_conversation_thread() -> None:
    """A glossary answer must not strand the turns that follow it."""

    response = answer_question("Apa itu USPS?", thread_id="ask-123")

    assert response.thread_id == "ask-123"


class TestCarrierGlossaryEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        monkeypatch.setenv("APP_USERNAME", AUTH[0])
        monkeypatch.setenv("APP_PASSWORD", AUTH[1])
        return TestClient(app)

    def test_glossary_question_echoes_the_thread_back(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asking what a carrier is mid-conversation keeps the same thread."""

        monkeypatch.delenv("LLM_API_KEY", raising=False)

        response = client.post(
            "/api/ask",
            json={"question": "Apa itu USPS?", "thread_id": "ask-123"},
            auth=AUTH,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["thread_id"] == "ask-123"
        assert body["carrier_knowledge"]["items"][0]["name"] == "USPS"
