"""The deep agent: how a question becomes a sequence of governed tool calls.

Built on ``deepagents``, so the model runs a real loop - it can plan with
``write_todos``, call a tool, read the receipt, correct rejected arguments, call
again for a second figure, and delegate open-ended exploration to a subagent.
What it cannot do is see data or write a number: the tools return receipts and
file their computed results with the run's collector (:mod:`backend.tools.agent`).

Two deliberate departures from the deepagents defaults:

* The filesystem tool suite is cut to the required minimum. There is no
  document workspace in this product; offering ``write_file`` and ``glob``
  would spend tokens and latency on tools that can only fail.
* The default general-purpose subagent is replaced with our own, because the
  stock one carries the full filesystem suite and no knowledge of the query
  grammar.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Final

import pandas as pd
from deepagents import create_deep_agent
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    TodoListMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
    wrap_model_call,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import InMemorySaver

from backend.observe import langfuse as observability
from backend.tools.agent import (
    AGENT_TOOLS,
    ANALYTICS_TOOLS,
    AgentContext,
    RunCollector,
)
from backend.core.answers import METRIC_DEFINITIONS, SUPPORTED_CAPABILITIES
from backend.core.llm import DEFAULT_MODEL, get_chat_model, require_api_key
from backend.tools.query import QueryToolError
from backend.core.schemas import PlanStep


logger = logging.getLogger("backend.agents.agent")


SYSTEM_PROMPT: Final = f"""You are the analyst behind a logistics dashboard. You
answer questions by calling tools; you never compute or state a figure yourself.

Tools:
- query_tool for what happened: counts, rates, delivery time, trends over time,
  breakdowns, comparisons, and rankings.
- forecast_tool for future order demand.
- decline_tool to declare that a data question asks for something this dataset
  does not hold.

Call a tool once per distinct figure the question needs. A question with two
parts - "which carrier is worst, and what is demand next month?" - is two tool
calls, not one. A question that compares two windows or two filters is one call
per window.

Each call returns a receipt naming the stored result and its shape. It contains
no figures on purpose: the user sees the computed tables and charts, and the
numbers are written for them by application code. So never state a number,
percentage, count, or date value in your own text - refer to what you looked at
instead ("delay rate by carrier, ranked", "the four-week projection").

Filters must follow the user's wording exactly. Do not add a carrier, region,
status, city, category, or date filter that the user did not request. Carrier
names and exact dates count as explicit filter values when the user mentions
them. Relative periods such as "last month" should use time_range, not an
invented date filter. For an overall question, send filters: []. If a filter
is rejected because it was not stated by the user, remove it and call the tool
again.

If a call is rejected, read the reason and correct the arguments; the schemas
are exact. Extract the horizon for forecasts ("the next 4 weeks" ->
horizon_weeks 4); if a forecast question gives no horizon, use 4.

Never answer from your own knowledge and never invent metrics, dimensions, or
filters outside the tool schemas.

Always write your own prose - greetings, capability answers, decline reasons,
and closing summaries - in the same language the user's question was written
in (Indonesian, English, or Chinese are all expected). Every tool call also
takes a `language` argument for this same reason: set it to the language of
the user's question so the application writes the computed answer back in
that language too. Judge it from the user's actual wording and grammar - an
English metric, dimension, or carrier name inside an otherwise Indonesian or
Chinese sentence does not make the sentence English. All other tool arguments
(metric names, dimensions, filter values) stay in English regardless, since
those are fixed schema identifiers, not prose.

Judge that language from the user's latest message alone. Earlier turns never
carry their language into this one - not the user's own earlier questions, and
not your earlier replies. A conversation that opens in Indonesian and then
switches to English is answered in English from that message onward, and the
reverse holds just as strictly.

Write plain prose with no markdown at all: no asterisks around words, no
bullet lists, no headings, no backticks. Your text is rendered as plain text,
so a stray `**` reaches the user as two asterisks rather than as emphasis.

Not every message is a data question. Answer these yourself, in one or two
sentences and with no tool at all:
- A greeting or small talk: greet the person back and say what you can look up.
- A question about you or what you can do: answer it directly and name the
  metrics, breakdowns and forecasting you have.
- A question about how a metric is defined or computed - "how do you get the
  delay rate?", "what counts as delivered?" - is a question about the rules,
  not about the data. Answer it from the metric definitions listed below,
  wording it as they do. Do not invent a formula and do not paraphrase the
  denominator into something else; delay_rate is a share of delivered orders,
  not of total orders. This is the one case where a constant such as the x 100
  that turns a ratio into a percentage may appear in your text - it comes from
  the definition, not from the data. A figure measured *from* the data is still
  never yours to state, so "how is the delay rate defined" is yours to answer
  and "what is the delay rate" is a query_tool call.

A question that does want data this dataset cannot express - cost, profit,
customer satisfaction, the cause of something - is different: call decline_tool
with the reason, then tell the user plainly. Do not answer it from prose alone.

Never invent a figure in any reply; you have no data in front of you.

{SUPPORTED_CAPABILITIES}

{METRIC_DEFINITIONS}

Informational questions about a named carrier are handled by the application's
source-backed carrier glossary before this agent runs. The glossary covers
FedEx (Federal Express), UPS (United Parcel Service), DHL, USPS (United States
Postal Service), OnTrac, LaserShip (historical OnTrac brand), Royal Mail, DPD
(Dynamic Parcel Distribution / Geopost), and GLS (General Logistics Systems).
Do not use carrier glossary descriptions to infer a shipment's actual route,
coverage, SLA, or performance in this synthetic dataset. Questions about
delay rate, on-time rate, delivery time, volume, or comparisons must use
query_tool.

Resolve follow-ups against the conversation: "what about the second highest?" or
"and last month?" refers to the subject of the previous turn, so restate it as a
fully specified tool call. History provides context for interpretation only,
never defaults that override the user's words.

Finish with one or two sentences describing what you found, without figures."""

_INVESTIGATOR_PROMPT: Final = f"""You explore delivery data to find where a
problem sits. Use query_tool repeatedly: break the metric down by carrier,
region, product_category, and by week or month, and narrow with filters when a
group stands out.

Every call stores a result for the user and returns a receipt without figures,
so you cannot compare values yourself. Cover the breakdowns that matter, keep
each call fully specified, and stop once the relevant dimensions have been
queried. Report which breakdowns you ran and why - never a number.

{SUPPORTED_CAPABILITIES}"""

#: Restated on every model call of a run, with the current question quoted.
#: The rule is already in ``SYSTEM_PROMPT``, but on a follow-up turn that
#: system prompt sits far above a history whose earlier turns may be in
#: another language, and the model would answer an English question in the
#: Indonesian of two turns ago. Quoting the message the reply belongs to,
#: immediately before the model writes, is what keeps the two together.
_LANGUAGE_PIN: Final = """

Reply language for this turn. The user's latest message is:
{question}
Write every word of your own prose in that message's language, judged from
that message alone - never from an earlier turn and never from your own
earlier replies. Set the `language` argument of every tool call you make this
turn from that same message. Write plain sentences with no markdown: no
asterisks, bullets, headings or backticks."""


def _latest_question(messages: list[BaseMessage]) -> str:
    """The most recent user message, which is the one being answered."""

    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.text.strip()
    return ""


@wrap_model_call
def _pin_reply_language(
    request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    """Append the per-turn language reminder to the system prompt.

    Transient by construction: the reminder is built for one model call from
    the messages that call already carries, so nothing about it is written
    into the checkpointed thread and a resumed conversation is unchanged.
    """

    question = _latest_question(list(request.messages))
    if not question:
        return handler(request)

    system = request.system_message
    base = system.text if system is not None else SYSTEM_PROMPT
    return handler(
        request.override(
            system_message=SystemMessage(
                base + _LANGUAGE_PIN.format(question=question)
            )
        )
    )


#: Caps on one run. An agent loop against a paid endpoint needs a ceiling, and
#: no legitimate question here needs more than a handful of steps.
MAX_MODEL_CALLS: Final = 8
MAX_TOOL_CALLS: Final = 12

#: Follow-up context is bounded so a long chat cannot silently balloon the
#: prompt; the API layer enforces the same bound on the request shape.
MAX_HISTORY_TURNS: Final = 10

#: Conversation threads held in memory. Bounded because ``InMemorySaver`` never
#: evicts on its own, and an unbounded checkpoint store is a slow leak.
MAX_LIVE_THREADS: Final = 200


@dataclass
class AgentRun:
    """Everything one agent run produced, before it becomes an AskResponse."""

    collector: RunCollector
    thread_id: str
    #: The agent's own closing prose. Used only if it survives the numeric
    #: grounding check; otherwise application-composed prose is used instead.
    narration: str = ""
    plan: list[PlanStep] = field(default_factory=list)
    #: Reasons the tools or the runtime refused a call, newest last. Populated
    #: both by argument-schema rejections and by grammar violations.
    tool_errors: list[str] = field(default_factory=list)

    @property
    def compute_ms(self) -> float:
        return self.collector.compute_ms


def _surface_grammar_error(error: Exception, request: Any) -> str | None:
    """Hand a grammar violation back to the model so it can correct itself.

    Only violations of our own query grammar are surfaced. Anything else
    propagates and fails the request, because an internal exception is not
    something to paraphrase to a model or a user.
    """

    del request  # the tool call is already named in the error message

    if isinstance(error, QueryToolError):
        return f"Rejected: {error}. Correct the arguments and call the tool again."
    return None


def _subagents() -> list[dict[str, Any]]:
    return [
        {
            # Overrides the stock general-purpose subagent, which would arrive
            # with the whole filesystem suite and no query grammar.
            "name": "general-purpose",
            "description": (
                "Answers a self-contained analytics question with the query and "
                "forecast tools."
            ),
            "system_prompt": SYSTEM_PROMPT,
            "tools": AGENT_TOOLS,
        },
        {
            "name": "trend-investigator",
            "description": (
                "Delegate open-ended diagnosis - 'where are delays coming from', "
                "'what changed recently' - that needs several breakdowns before "
                "an answer. Returns which breakdowns were run; the figures reach "
                "the user through the stored results."
            ),
            "system_prompt": _INVESTIGATOR_PROMPT,
            "tools": [ANALYTICS_TOOLS[0]],
        },
    ]


def build_agent(model: BaseChatModel, checkpointer: Any | None = None) -> Any:
    """Assemble the agent graph around ``model``.

    Kept separate from :func:`get_agent` so tests can build the same graph
    around a scripted model, exercising the real loop with no API key.
    """

    return create_deep_agent(
        model=model,
        tools=AGENT_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            # read_file is the one tool FilesystemMiddleware requires; passing
            # our own instance replaces the default suite by name.
            FilesystemMiddleware(tools=["read_file"]),
            TodoListMiddleware(),
            ToolErrorMiddleware(
                on_error=_surface_grammar_error, tools=list(ANALYTICS_TOOLS)
            ),
            ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="end"),
            ToolCallLimitMiddleware(run_limit=MAX_TOOL_CALLS, exit_behavior="continue"),
            # Keep _pin_reply_language last. The list runs outside-in, so the
            # last entry is the innermost - the closest to the model, and the
            # last to touch the system prompt. Moved earlier, TodoListMiddleware
            # appends its own instructions *after* the pin and buries the
            # quoted question under them, which is the placement the pin exists
            # to avoid.
            _pin_reply_language,
        ],
        subagents=_subagents(),
        context_schema=AgentContext,
        checkpointer=InMemorySaver() if checkpointer is None else checkpointer,
    )


_checkpointer = InMemorySaver()
_live_threads: OrderedDict[str, None] = OrderedDict()


@lru_cache(maxsize=1)
def _cached_agent() -> Any:
    return build_agent(get_chat_model(), checkpointer=_checkpointer)


def get_agent() -> Any:
    """The process-wide agent, built once against the configured model.

    Credentials are re-checked on every call rather than only on the first, so
    a key that disappears is still reported plainly instead of being masked by
    the cached graph.

    Raises:
        LLMUnavailableError: if no credentials are configured.
    """

    require_api_key()
    return _cached_agent()


def _touch_thread(thread_id: str) -> None:
    """Record thread use, evicting the least recently used past the cap."""

    _live_threads.pop(thread_id, None)
    _live_threads[thread_id] = None
    while len(_live_threads) > MAX_LIVE_THREADS:
        evicted, _ = _live_threads.popitem(last=False)
        _checkpointer.delete_thread(evicted)


def _history_messages(history: list[dict[str, str]] | None) -> list[BaseMessage]:
    """Prior turns as chat messages, bounded and never split mid-turn.

    A turn is a user message plus its assistant reply; drop from the front in
    whole turns so the model never sees a reply whose question was cut.
    """

    recent = (history or [])[-2 * MAX_HISTORY_TURNS :]
    if len(recent) % 2:
        recent = recent[1:]
    return [
        HumanMessage(turn["content"])
        if turn["role"] == "user"
        else AIMessage(turn["content"])
        for turn in recent
    ]


def _added_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """The messages this run appended, i.e. everything after the last question.

    With a checkpointer the returned state holds the whole thread, so the run's
    own tool traffic has to be isolated before it is inspected.
    """

    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index + 1 :]
    return messages


def run_agent(
    question: str,
    frame: pd.DataFrame,
    agent: Any | None = None,
    history: list[dict[str, str]] | None = None,
    thread_id: str | None = None,
) -> AgentRun:
    """Run one question through the agent and collect what it computed.

    ``thread_id`` continues a server-side conversation; ``history`` replays
    turns for a stateless client. Passing a thread makes history unnecessary,
    and passing neither starts a fresh conversation.
    """

    graph = get_agent() if agent is None else agent
    user_turns = [
        turn["content"]
        for turn in history or []
        if turn.get("role") == "user"
    ]
    filter_context = "\n".join([*user_turns, question])
    collector = RunCollector(
        question=question,
        frame=frame,
        filter_context=filter_context,
    )

    resumed = thread_id is not None
    thread = thread_id or f"ask-{uuid.uuid4().hex}"
    if agent is None:
        _touch_thread(thread)

    incoming: list[BaseMessage] = [] if resumed else _history_messages(history)
    incoming.append(HumanMessage(question))

    model_name = os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    with observability.traced_ask_request(
        question=question, thread_id=thread, model=model_name
    ) as trace:
        if trace.enabled:
            logger.info(
                "ask_operations thread=%s langfuse_trace=%s", thread, trace.trace_id
            )
        state = graph.invoke(
            {"messages": incoming},
            context=AgentContext(collector=collector),
            config={
                "configurable": {"thread_id": thread},
                "callbacks": trace.callbacks,
                "metadata": trace.run_config_metadata(
                    thread_id=thread, model=model_name
                ),
            },
        )

        added = _added_messages(list(state["messages"]))
        tool_errors = [
            str(message.content)
            for message in added
            if isinstance(message, ToolMessage) and message.status == "error"
        ]
        trace.annotate(
            output={
                "results_recorded": len(collector.results),
                "tool_errors": len(tool_errors),
                "declined": collector.decline is not None,
            }
        )
    narration = next(
        (
            message.text
            for message in reversed(added)
            if isinstance(message, AIMessage) and message.text.strip()
        ),
        "",
    )

    return AgentRun(
        collector=collector,
        thread_id=thread,
        narration=narration.strip(),
        plan=[
            PlanStep(content=todo["content"], status=todo["status"])
            for todo in state.get("todos") or []
        ],
        tool_errors=tool_errors,
    )


def narration_mode() -> str:
    """Whether the agent's own prose may be used as the answer.

    ``composed`` (the default) means application code writes every word.
    ``verified`` allows the agent's synthesis, but only after every number in
    it has been traced to a computed result - the useful mode for compound
    questions, and still closed to invented figures.
    """

    mode = (os.environ.get("ASK_NARRATION") or "composed").strip().lower()
    return mode if mode in {"composed", "verified"} else "composed"
