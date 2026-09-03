"""Turn a natural-language question into governed tool calls and an answer.

The division of labour is the point of the whole design: the model interprets
the question and drives the tools, application code computes every number. The
model never sees a row of data, and by default it never writes a figure in the
answer either, so a hallucinated number has nowhere to enter (PRD 9).

Since the refactor onto ``deepagents`` this module is no longer the loop - see
:mod:`backend.agent` for that. What stays here is the boundary the API depends
on: run the agent, decide whether the run produced an answer or a refusal, and
assemble the :class:`AskResponse` from what the tools filed.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any, Final

import pandas as pd

from backend import grounding
from backend.agent import (
    MAX_HISTORY_TURNS,
    SYSTEM_PROMPT,
    AgentRun,
    narration_mode,
    run_agent,
)
from backend.agent_tools import FORECAST_TOOL, QUERY_TOOL, tool_definitions
from backend.answers import SUPPORTED_CAPABILITIES
from backend.carrier_knowledge import compose_carrier_answer
from backend.ingestion import get_dataset
from backend.smalltalk import compose_smalltalk_answer
from backend.schemas import (
    AskResponse,
    AskResult,
    CarrierKnowledge,
    CarrierKnowledgeItem,
    Runtime,
    SmalltalkReply,
)


__all__ = [
    "FORECAST_TOOL",
    "MAX_HISTORY_TURNS",
    "QUERY_TOOL",
    "SUPPORTED_CAPABILITIES",
    "SYSTEM_PROMPT",
    "answer_question",
    "tool_definitions",
]

#: Marks a tool call the runtime rejected before our code saw it - an unknown
#: tool name rather than bad arguments for a real one.
_UNKNOWN_TOOL_MARKERS: Final = ("is not a valid tool", "not found", "no tool named")


def _unsupported(reason: str, thread_id: str | None = None) -> AskResponse:
    return AskResponse(
        answer="",
        results=[],
        thread_id=thread_id,
        unsupported=True,
        unsupported_reason=f"{reason} {SUPPORTED_CAPABILITIES}",
    )


def _attempted_a_tool(run: AgentRun) -> bool:
    """Whether the run tried to compute something, or ruled the question out."""

    return bool(
        run.collector.failures or run.tool_errors or run.collector.decline is not None
    )


def _refusal_reason(run: AgentRun) -> str:
    """Why a run that computed nothing produced no answer.

    The most specific explanation wins: a grammar violation our own tools
    raised, then arguments the tool schema rejected, then a model that declined
    to call a tool at all.
    """

    if run.collector.decline is not None:
        return run.collector.decline.rstrip(".") + "."

    if run.collector.failures:
        return run.collector.failures[-1].reason.rstrip(".") + "."

    if run.tool_errors:
        if any(
            marker in error.lower()
            for error in run.tool_errors
            for marker in _UNKNOWN_TOOL_MARKERS
        ):
            return "The agent asked for a tool that does not exist."
        return (
            "The request did not match the approved query grammar "
            f"({len(run.tool_errors)} rejected call(s))."
        )

    return "That question cannot be answered from this dataset."


def _with_runtime(results: list[AskResult], runtime: Runtime) -> list[AskResult]:
    """Stamp the run's timings onto every result block.

    Measured around the whole agent run - planning, model calls and
    computation - rather than in the API layer, so the number excludes the HTTP
    round trip. One agent run produces all the blocks, so they share it.
    """

    return [
        result.model_copy(
            update={
                "explainability": result.explainability.model_copy(
                    update={"runtime": runtime}
                )
            }
        )
        for result in results
    ]


def _compose_answer(run: AgentRun, results: list[AskResult]) -> tuple[str, str]:
    """The answer text and how it was produced.

    Composed prose is the default and the fallback. The agent's own synthesis
    is used only in ``verified`` mode and only when every number in it traces
    to a computed result, which is what makes it safe to print.
    """

    composed = " ".join(result.answer for result in results)
    if (
        narration_mode() == "verified"
        and run.narration
        and grounding.is_grounded(run.narration, results)
    ):
        return run.narration, "model"
    return composed, "composed"


def answer_question(
    question: str,
    agent: Any | None = None,
    frame: pd.DataFrame | None = None,
    history: list[dict[str, str]] | None = None,
    thread_id: str | None = None,
) -> AskResponse:
    """Run a question through the agent and assemble a grounded answer.

    Every failure mode - the agent declining, arguments that break the
    contract, a request that parses but is not allowed - resolves to an
    explained unsupported response rather than a guess (FR-15).

    ``agent`` defaults to the process-wide agent; tests pass one built around a
    scripted model. ``history`` is prior conversation as role/content messages
    for a stateless client, while ``thread_id`` continues a conversation the
    server already holds. Neither ever carries numbers into the answer.
    """

    if not question.strip():
        return _unsupported("Ask a question about the delivery data.")

    # A greeting has nothing to compute. Answering it from a template costs no
    # model call and keeps "halo" working when the provider is down; the match
    # is whole-message, so a greeting attached to a real question falls
    # through to the agent.
    greeting = compose_smalltalk_answer(question)
    if greeting is not None:
        return AskResponse(
            answer=greeting.reply,
            smalltalk=SmalltalkReply(
                intent=greeting.intent, language=greeting.language
            ),
            thread_id=thread_id,
            unsupported=False,
            unsupported_reason=None,
        )

    # Carrier descriptions are static, source-backed knowledge. Resolve them
    # before building the LLM agent so glossary questions work even when the
    # analytics model is unavailable, and keep performance questions on the
    # governed Query Tool path.
    carrier_answer = compose_carrier_answer(question)
    if carrier_answer is not None:
        answer, definitions = carrier_answer
        return AskResponse(
            answer=answer,
            carrier_knowledge=CarrierKnowledge(
                items=[
                    CarrierKnowledgeItem(
                        name=definition.name,
                        expanded_name=definition.expanded_name,
                        description=definition.description,
                        source_url=definition.source_url,
                    )
                    for definition in definitions
                ]
            ),
            thread_id=thread_id,
            unsupported=False,
            unsupported_reason=None,
        )

    source = get_dataset() if frame is None else frame

    started = perf_counter()
    run = run_agent(
        question, source, agent=agent, history=history, thread_id=thread_id
    )
    total_ms = (perf_counter() - started) * 1000

    if not run.collector.results:
        # A message that needed no tool - a question about what the agent can
        # do, a greeting the templates do not match - is answered by the agent
        # itself. Its prose still has to pass the numeric check: with nothing
        # computed, any figure in it would be invented, so the check rejects
        # it outright and the canned refusal is used instead. A question the
        # agent ruled out with decline_tool never takes this path.
        if (
            not _attempted_a_tool(run)
            and run.narration
            and grounding.is_grounded(run.narration, [])
        ):
            return AskResponse(
                answer=run.narration,
                results=[],
                plan=run.plan,
                narration="model",
                narrated=True,
                thread_id=run.thread_id,
                unsupported=False,
                unsupported_reason=None,
            )
        return _unsupported(_refusal_reason(run), thread_id=run.thread_id)

    runtime = Runtime(
        total_ms=round(total_ms, 1),
        model_ms=round(max(total_ms - run.compute_ms, 0.0), 1),
        compute_ms=round(min(run.compute_ms, total_ms), 1),
    )
    results = _with_runtime(run.collector.results, runtime)
    answer, narration = _compose_answer(run, results)

    return AskResponse(
        answer=answer,
        results=results,
        plan=run.plan,
        narration=narration,
        thread_id=run.thread_id,
        unsupported=False,
        unsupported_reason=None,
    )
