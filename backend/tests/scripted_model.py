"""A chat model that replays a fixed script, for testing the real agent loop.

Before the deepagents refactor the tests stubbed a one-shot ``choose_tool``
call, which meant the loop itself - planning, tool errors, retries, threads -
was never exercised. Scripting the *model* instead runs the actual graph with
no API key, so what the tests assert on is the behaviour that ships.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


@dataclass(frozen=True)
class ToolCall:
    """A tool the model should ask for, with the arguments it supplies."""

    name: str
    arguments: dict[str, Any]


#: Used when the script runs out, so an exhausted script ends the run instead
#: of looping on its last message.
EXHAUSTED = "Nothing further."


class ScriptedChatModel(BaseChatModel):
    """Replays ``script`` one message per model call, recording what it saw."""

    script: list[AIMessage] = Field(default_factory=list)
    #: The message list passed on each call, so tests can assert on history.
    seen: list[list[BaseMessage]] = Field(default_factory=list)
    #: Names of the tools the agent offered, from the last bind_tools call.
    offered_tools: list[str] = Field(default_factory=list)
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        index, self.calls = self.calls, self.calls + 1
        message = (
            self.script[index] if index < len(self.script) else AIMessage(EXHAUSTED)
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        # The agent binds tools per node; recording rather than wrapping keeps
        # the same instance in play so `seen` and `calls` stay observable.
        self.offered_tools = [
            getattr(offered, "name", str(offered)) for offered in tools
        ]
        return self


_ids = itertools.count(1)


def asks_for(*calls: ToolCall) -> AIMessage:
    """One assistant turn requesting every tool call in ``calls``."""

    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": call.name,
                "args": dict(call.arguments),
                "id": f"call-{next(_ids)}",
            }
            for call in calls
        ],
    )


def says(text: str) -> AIMessage:
    """One assistant turn of plain prose."""

    return AIMessage(text)


def script_for(*calls: ToolCall | None, closing: str = "Reviewed the results.") -> list[AIMessage]:
    """A script that requests each call in turn, then closes with prose.

    ``None`` stands for the model declining to call anything, which is how an
    out-of-scope question is expressed.
    """

    requested = [call for call in calls if call is not None]
    if not requested:
        return [says("That cannot be answered from this dataset.")]
    return [asks_for(call) for call in requested] + [says(closing)]
