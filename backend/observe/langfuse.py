"""Langfuse tracing adapter for the Ask Operations request lifecycle.

The only place backend code talks to Langfuse. :func:`traced_ask_request` wraps
one agent run: it opens a root span, hands back a LangChain callback handler to
attach to the graph's ``invoke`` config (so model generations and tool calls
nest under it automatically), and flushes on exit.

Fail-open by construction: every Langfuse call is isolated in its own
try/except. A missing dependency, a bad key, an unreachable host, or a flush
timeout degrades to "no trace" - never to a failed or delayed answer. Callers
never need to check whether tracing is enabled; :class:`RequestTrace` is always
safe to use (its ``callbacks`` list is simply empty when tracing is off).
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


logger = logging.getLogger("backend.observe.langfuse")

#: Keys redacted from anything sent to Langfuse, case-insensitively. Belt and
#: braces: nothing here should ever hold a credential, but a metadata dict
#: assembled from several call sites is exactly where one could sneak in.
_REDACT_KEYS = frozenset(
    {"api_key", "apikey", "authorization", "password", "secret", "token", "key"}
)


def _flag(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def is_enabled() -> bool:
    """Whether tracing should be attempted in this process.

    ``LANGFUSE_ENABLED`` is an explicit override. Absent that, tracing is on
    only once both keys are configured, so an unconfigured deployment stays
    silent instead of logging a warning on every single request.
    """

    has_keys = bool(os.environ.get("LANGFUSE_PUBLIC_KEY")) and bool(
        os.environ.get("LANGFUSE_SECRET_KEY")
    )
    return _flag("LANGFUSE_ENABLED", default=has_keys)


def include_query_source_rows() -> bool:
    """Whether Langfuse may receive the filtered source rows for a query.

    Aggregated query results are safe and useful for auditability, so they are
    always attached to the query observation. Raw shipment rows are opt-in
    because a real deployment may contain sensitive operational data.
    """

    return _flag("LANGFUSE_INCLUDE_QUERY_SOURCE_ROWS", default=False)


def deployment_environment() -> str:
    """The environment label attached to every trace (dev/staging/prod/...)."""

    return (
        os.environ.get("LANGFUSE_TRACING_ENVIRONMENT")
        or os.environ.get("DEPLOYMENT_ENVIRONMENT")
        or "development"
    )


def custom_tags() -> dict[str, str]:
    """Static labels from ``CUSTOM_TAGS``, attached to every trace.

    Configured as one JSON-object env var (e.g. ``{"org": "...", "project":
    "...", "developer": "..."}``) rather than fixed fields, so a deployment can
    attach whatever labels it wants - team, project, owner - without a code
    change. Malformed input is logged and ignored, never fatal: a broken
    ``CUSTOM_TAGS`` value must not take tracing down with it.
    """

    raw = os.environ.get("CUSTOM_TAGS")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("CUSTOM_TAGS is not valid JSON; ignoring it.")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("CUSTOM_TAGS must be a JSON object; ignoring it.")
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def redact(metadata: dict[str, Any]) -> dict[str, Any]:
    """Replace credential-shaped values before they leave the process."""

    return {
        key: ("<redacted>" if key.lower() in _REDACT_KEYS else value)
        for key, value in metadata.items()
    }


def annotate_current_observation(
    *,
    input: Any | None = None,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
    level: str | None = None,
) -> None:
    """Attach computed tool input/output to the active Langfuse observation.

    LangChain creates the ``query_tool`` observation before entering the tool
    function. Updating the current span enriches that existing observation
    instead of creating a second, detached span. This is best effort for the
    same reason as the rest of this adapter: observability must never change
    the answer path.
    """

    client = _client_or_none()
    if client is None:
        return
    try:
        client.update_current_span(
            input=redact(input) if isinstance(input, dict) else input,
            output=redact(output) if isinstance(output, dict) else output,
            metadata=redact(metadata) if metadata else None,
            level=level,
        )
    except Exception:
        logger.debug("Could not annotate current Langfuse observation.", exc_info=True)


_client: Any = None
#: Set once client construction fails, so a bad key/host is reported once and
#: every later request short-circuits to "disabled" instead of retrying and
#: logging the same warning on every question.
_unavailable = False


def _client_or_none() -> Any | None:
    """The process-wide Langfuse client, built once, or ``None`` if unusable."""

    global _client, _unavailable

    if _unavailable or not is_enabled():
        return None
    if _client is not None:
        return _client

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
            base_url=os.environ.get("LANGFUSE_BASE_URL") or None,
            environment=deployment_environment(),
        )
        return _client
    except Exception:
        logger.warning(
            "Langfuse client failed to initialize; tracing disabled for this "
            "process.",
            exc_info=True,
        )
        _unavailable = True
        _client = None
        return None


@dataclass
class RequestTrace:
    """What one Ask Operations request gets back from tracing.

    ``callbacks`` is always safe to splice into a LangChain ``config`` dict: it
    is an empty list whenever tracing is off, unconfigured, or broken, so
    callers never need an ``if enabled`` branch.
    """

    enabled: bool
    trace_id: str | None = None
    callbacks: list[Any] = field(default_factory=list)

    def run_config_metadata(
        self, *, thread_id: str | None, model: str | None
    ) -> dict[str, Any]:
        """LangChain run-config ``metadata`` that threads session/tags in.

        Keys prefixed ``langfuse_`` are read specially by the callback handler
        (session id, tags); everything else rides along as-is.
        """

        if not self.enabled:
            return {}
        tags = custom_tags()
        metadata: dict[str, Any] = dict(tags)
        if model:
            metadata["model"] = model
        return {
            "langfuse_session_id": thread_id,
            "langfuse_tags": [
                "ask-operations",
                deployment_environment(),
                *(f"{key}:{value}" for key, value in tags.items()),
            ],
            "langfuse_metadata": redact(metadata),
        }

    def annotate(
        self, *, output: Any | None = None, metadata: dict[str, Any] | None = None
    ) -> None:
        """Attach a non-fatal outcome (decline reason, tool-error count, ...).

        Best-effort: called while the root span is still open, so a broken
        Langfuse call here must not interrupt the response either.
        """

        if not self.enabled or _client is None:
            return
        try:
            _client.update_current_trace(
                output=output,
                metadata=redact(metadata) if metadata else None,
            )
        except Exception:
            logger.debug("Could not annotate Langfuse trace.", exc_info=True)


_DISABLED = RequestTrace(enabled=False)


@contextmanager
def traced_ask_request(
    *, question: str, thread_id: str | None, model: str | None = None
) -> Iterator[RequestTrace]:
    """Wrap one Ask Operations agent run in a root Langfuse trace.

    Yields a :class:`RequestTrace`. Pass ``trace.callbacks`` and
    ``trace.run_config_metadata(...)`` into the LangChain ``invoke`` config the
    agent graph runs with - the callback handler then creates generation spans
    per model call and spans per tool call, nested under the root span opened
    here, all keyed to ``thread_id`` as the Langfuse session.

    Every Langfuse call is individually guarded: a failure at any step falls
    back to "no tracing" rather than raising into the caller.
    """

    client = _client_or_none()
    if client is None:
        yield _DISABLED
        return

    try:
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler()
    except Exception:
        logger.warning(
            "Could not build the Langfuse callback handler; continuing "
            "without tracing.",
            exc_info=True,
        )
        yield _DISABLED
        return

    try:
        span_cm = client.start_as_current_span(
            name="ask-operations-request",
            input=redact({"question": question}),
        )
        span_cm.__enter__()
    except Exception:
        logger.warning(
            "Could not start a Langfuse span; continuing without tracing.",
            exc_info=True,
        )
        yield _DISABLED
        return

    try:
        tags = custom_tags()
        client.update_current_trace(
            session_id=thread_id,
            tags=[
                "ask-operations",
                deployment_environment(),
                *(f"{key}:{value}" for key, value in tags.items()),
            ],
            metadata=redact(
                {
                    **tags,
                    "deployment_environment": deployment_environment(),
                    "model": model,
                }
            ),
        )
    except Exception:
        logger.debug("Could not set Langfuse trace attributes.", exc_info=True)

    trace_id: str | None = None
    try:
        trace_id = client.get_current_trace_id()
    except Exception:
        logger.debug("Could not read the Langfuse trace id.", exc_info=True)

    try:
        yield RequestTrace(enabled=True, trace_id=trace_id, callbacks=[handler])
    except BaseException as exc:
        try:
            span_cm.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            logger.debug("Could not close the Langfuse span.", exc_info=True)
        raise
    else:
        try:
            span_cm.__exit__(None, None, None)
        except Exception:
            logger.debug("Could not close the Langfuse span.", exc_info=True)
    finally:
        try:
            client.flush()
        except Exception:
            logger.debug("Could not flush the Langfuse client.", exc_info=True)
