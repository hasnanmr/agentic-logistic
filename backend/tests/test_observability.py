"""Stream G: Langfuse tracing must never affect the answer, only observe it.

Every test here proves the fail-open contract from ``backend/observability.py``
docstring: tracing off, tracing broken, or tracing's own flush failing must all
look identical to the caller - a normal :class:`AgentRun`, nothing raised. A
real Langfuse project is never contacted; the SDK's ``Langfuse`` client and its
LangChain ``CallbackHandler`` are replaced with local fakes so the suite runs
offline and deterministically.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from langchain_core.callbacks import BaseCallbackHandler

from backend import observability
from backend.agent import build_agent, run_agent
from backend.agent_tools import QUERY_TOOL
from backend.ingestion import load_dataset
from backend.tests.scripted_model import ScriptedChatModel, ToolCall, script_for


RANKING = ToolCall(
    QUERY_TOOL,
    {"metric": "delay_rate", "dimensions": ["carrier"], "limit": 3},
)


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


#: Every env var this module reads. Cleared before each test so a developer's
#: own local `.env` (real Langfuse keys, `LANGFUSE_ENABLED=true`, ...) can
#: never leak into a test's "tracing off" baseline - each test then opts back
#: into exactly the variables its scenario needs.
_OBSERVABILITY_ENV_VARS = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_ENABLED",
    "LANGFUSE_TRACING_ENVIRONMENT",
    "DEPLOYMENT_ENVIRONMENT",
    "CUSTOM_TAGS",
)


@pytest.fixture(autouse=True)
def _reset_observability_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from both the adapter's cache and the real `.env`.

    The adapter caches its client/failure state at module scope on purpose (so
    a bad key is reported once, not per-request), and `backend.config` loads
    the developer's real `.env` at import time - both would otherwise leak
    into tests that assume tracing starts off.
    """

    for name in _OBSERVABILITY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    observability._client = None
    observability._unavailable = False
    yield
    observability._client = None
    observability._unavailable = False


class FakeSpan:
    def __enter__(self) -> "FakeSpan":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False


class RaisingSpanContext:
    """A span context manager whose ``__enter__`` itself fails."""

    def __enter__(self) -> "RaisingSpanContext":
        raise RuntimeError("span backend unreachable")

    def __exit__(self, *exc_info: Any) -> bool:
        return False


class FakeLangfuseClient:
    """Records every call so tests can assert without a real Langfuse server."""

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.trace_updates: list[dict[str, Any]] = []
        self.flush_calls = 0
        self.span_started = False

    def start_as_current_span(self, **kwargs: Any) -> FakeSpan:
        self.span_started = True
        return FakeSpan()

    def update_current_trace(self, **kwargs: Any) -> None:
        self.trace_updates.append(kwargs)

    def get_current_trace_id(self) -> str:
        return "trace-fake-123"

    def flush(self) -> None:
        self.flush_calls += 1


class RaisingFlushClient(FakeLangfuseClient):
    def flush(self) -> None:
        raise RuntimeError("network timeout")


class RecordingCallbackHandler(BaseCallbackHandler):
    """A real LangChain callback handler, so a real graph run drives it."""

    def __init__(self) -> None:
        self.model_starts = 0
        self.tool_starts: list[str | None] = []

    def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        self.model_starts += 1

    def on_llm_start(self, serialized: Any, prompts: Any, **kwargs: Any) -> None:
        self.model_starts += 1

    def on_tool_start(self, serialized: Any, input_str: Any, **kwargs: Any) -> None:
        name = serialized.get("name") if isinstance(serialized, dict) else None
        self.tool_starts.append(name)


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)


# --- is_enabled / redact -----------------------------------------------------


def test_disabled_by_default_with_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)

    assert observability.is_enabled() is False


def test_enabled_once_both_keys_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)

    assert observability.is_enabled() is True


def test_explicit_flag_overrides_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")

    assert observability.is_enabled() is False


def test_custom_tags_parses_the_configured_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CUSTOM_TAGS",
        '{"org":"spaceship","project":"dashboard-logistic","developer":"hasnan"}',
    )

    assert observability.custom_tags() == {
        "org": "spaceship",
        "project": "dashboard-logistic",
        "developer": "hasnan",
    }


def test_custom_tags_defaults_to_empty_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CUSTOM_TAGS", raising=False)

    assert observability.custom_tags() == {}


@pytest.mark.parametrize("raw", ["not json", "[1, 2, 3]", '"just a string"'])
def test_custom_tags_ignores_malformed_or_non_object_values(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("CUSTOM_TAGS", raw)

    assert observability.custom_tags() == {}


def test_redact_masks_credential_shaped_keys() -> None:
    masked = observability.redact({"api_key": "sk-123", "Authorization": "Bearer x", "model": "gpt"})

    assert masked["api_key"] == "<redacted>"
    assert masked["Authorization"] == "<redacted>"
    assert masked["model"] == "gpt"


# --- traced_ask_request: disabled and broken paths never affect the caller --


def test_tracing_off_yields_a_disabled_trace_with_no_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    with observability.traced_ask_request(question="q", thread_id="t1") as trace:
        assert trace.enabled is False
        assert trace.callbacks == []
        assert trace.trace_id is None
        assert trace.run_config_metadata(thread_id="t1", model="m") == {}


def test_a_broken_client_constructor_falls_back_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)

    class BrokenClient:
        def __init__(self, **kwargs: Any) -> None:
            raise RuntimeError("bad credentials")

    monkeypatch.setattr("langfuse.Langfuse", BrokenClient)

    with observability.traced_ask_request(question="q", thread_id="t1") as trace:
        assert trace.enabled is False


def test_a_broken_span_start_falls_back_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    fake = FakeLangfuseClient()
    fake.start_as_current_span = lambda **kwargs: RaisingSpanContext()  # type: ignore[method-assign]
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: fake)

    with observability.traced_ask_request(question="q", thread_id="t1") as trace:
        assert trace.enabled is False


def test_a_broken_callback_handler_falls_back_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: FakeLangfuseClient())

    def broken_handler(**kwargs: Any) -> Any:
        raise RuntimeError("handler init failed")

    monkeypatch.setattr("langfuse.langchain.CallbackHandler", broken_handler)

    with observability.traced_ask_request(question="q", thread_id="t1") as trace:
        assert trace.enabled is False


def test_flush_failure_does_not_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    fake = RaisingFlushClient()
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: fake)
    monkeypatch.setattr(
        "langfuse.langchain.CallbackHandler", lambda **kwargs: RecordingCallbackHandler()
    )

    with observability.traced_ask_request(question="q", thread_id="t1") as trace:
        assert trace.enabled is True
    # No exception escaped the flush failure above - that is the assertion.


def test_a_question_exception_still_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-open means Langfuse never masks a real application error."""

    _enable(monkeypatch)
    fake = FakeLangfuseClient()
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: fake)
    monkeypatch.setattr(
        "langfuse.langchain.CallbackHandler", lambda **kwargs: RecordingCallbackHandler()
    )

    with pytest.raises(ValueError, match="boom"):
        with observability.traced_ask_request(question="q", thread_id="t1"):
            raise ValueError("boom")

    assert fake.flush_calls == 1


# --- traced_ask_request: the happy path ------------------------------------


def test_enabled_trace_carries_session_and_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "staging")
    fake = FakeLangfuseClient()
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: fake)
    monkeypatch.setattr(
        "langfuse.langchain.CallbackHandler", lambda **kwargs: RecordingCallbackHandler()
    )

    with observability.traced_ask_request(
        question="Which carrier is worst?", thread_id="thread-9", model="test-model"
    ) as trace:
        assert trace.enabled is True
        assert trace.trace_id == "trace-fake-123"
        assert len(trace.callbacks) == 1
        metadata = trace.run_config_metadata(thread_id="thread-9", model="test-model")
        assert metadata["langfuse_session_id"] == "thread-9"
        assert "staging" in metadata["langfuse_tags"]

    assert fake.span_started is True
    assert fake.flush_calls == 1
    [update] = fake.trace_updates
    assert update["session_id"] == "thread-9"
    assert update["metadata"]["deployment_environment"] == "staging"


def test_custom_tags_reach_both_the_trace_update_and_run_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    monkeypatch.setenv(
        "CUSTOM_TAGS",
        '{"org":"spaceship","project":"dashboard-logistic","developer":"hasnan"}',
    )
    fake = FakeLangfuseClient()
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: fake)
    monkeypatch.setattr(
        "langfuse.langchain.CallbackHandler", lambda **kwargs: RecordingCallbackHandler()
    )

    with observability.traced_ask_request(
        question="q", thread_id="thread-9", model="test-model"
    ) as trace:
        metadata = trace.run_config_metadata(thread_id="thread-9", model="test-model")

    assert "org:spaceship" in metadata["langfuse_tags"]
    assert "project:dashboard-logistic" in metadata["langfuse_tags"]
    assert "developer:hasnan" in metadata["langfuse_tags"]
    assert metadata["langfuse_metadata"]["org"] == "spaceship"

    [update] = fake.trace_updates
    assert "org:spaceship" in update["tags"]
    assert update["metadata"]["project"] == "dashboard-logistic"
    assert update["metadata"]["developer"] == "hasnan"


def test_annotate_is_a_noop_when_tracing_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    with observability.traced_ask_request(question="q", thread_id="t1") as trace:
        trace.annotate(output={"x": 1})  # must not raise


# --- end to end: one real agent run produces model + tool observations ------


def test_a_real_agent_run_drives_model_and_tool_observations(
    monkeypatch: pytest.MonkeyPatch, dataset: pd.DataFrame
) -> None:
    """The wiring in ``backend.agent.run_agent``, not just the adapter alone.

    Runs the real deepagents graph against a scripted model with tracing
    "on" via fakes, and checks the callback handler that would have shipped
    spans to Langfuse actually observed both a model call and the tool call
    the script requests - i.e. one trace with model plus tool observations.
    """

    _enable(monkeypatch)
    fake_client = FakeLangfuseClient()
    recorder = RecordingCallbackHandler()
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: fake_client)
    monkeypatch.setattr("langfuse.langchain.CallbackHandler", lambda **kwargs: recorder)

    model = ScriptedChatModel(script=script_for(RANKING))
    run_agent("Which carrier is worst?", dataset, agent=build_agent(model))

    assert recorder.model_starts >= 1
    assert QUERY_TOOL in recorder.tool_starts
    assert fake_client.span_started is True
    assert fake_client.flush_calls == 1


def test_tracing_disabled_leaves_the_agent_run_unaffected(
    monkeypatch: pytest.MonkeyPatch, dataset: pd.DataFrame
) -> None:
    """The default state (no keys configured) must not change agent behavior."""

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    model = ScriptedChatModel(script=script_for(RANKING))
    run = run_agent("Which carrier is worst?", dataset, agent=build_agent(model))

    assert run.collector.results
    assert not run.tool_errors
