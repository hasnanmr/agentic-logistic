"""Thin boundary around the language model.

The model's only job is choosing which tool to call and with what arguments -
it never sees the dataset and never produces a number. Keeping that boundary in
one small module means the orchestrator can be tested with a stub client and no
API key, and swapping providers touches nothing else.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Final, Protocol


# OpenRouter speaks the OpenAI chat-completions protocol, so this client works
# against it unchanged; its model ids carry a provider prefix.
DEFAULT_MODEL: Final = "openai/gpt-5.6-luna"
DEFAULT_BASE_URL: Final = "https://openrouter.ai/api/v1"


class LLMUnavailableError(RuntimeError):
    """Raised when no language-model credentials are configured."""


@dataclass(frozen=True)
class ToolCall:
    """A tool the model chose, with the arguments it supplied."""

    name: str
    arguments: dict[str, Any]


class LLMClient(Protocol):
    """What the orchestrator needs from a model provider."""

    def choose_tool(
        self,
        question: str,
        tools: list[dict[str, Any]],
        system_prompt: str,
        history: list[dict[str, str]] | None = None,
    ) -> ToolCall | None:
        """Return the tool the model selected, or None if it declined.

        ``history`` carries prior turns as role/content messages so follow-up
        questions can be resolved against the conversation so far.
        """


class OpenAICompatibleClient:
    """Tool-calling against any OpenAI-compatible chat completions endpoint."""

    def __init__(
        self, api_key: str, base_url: str | None = None, model: str | None = None
    ) -> None:
        from openai import OpenAI

        self._model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self._client = OpenAI(
            api_key=api_key, base_url=base_url or DEFAULT_BASE_URL
        )

    def choose_tool(
        self,
        question: str,
        tools: list[dict[str, Any]],
        system_prompt: str,
        history: list[dict[str, str]] | None = None,
    ) -> ToolCall | None:
        # Prior turns come in as ordinary chat messages so the model sees the
        # conversation when resolving follow-ups; only the latest question is
        # interpreted for a tool call.
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,
            # "auto" lets the model decline, which is how an out-of-scope
            # question reaches the unsupported path instead of being forced
            # into a tool call that would answer the wrong question.
            tool_choice="auto",
            temperature=0,
        )

        message = response.choices[0].message
        if not getattr(message, "tool_calls", None):
            return None

        call = message.tool_calls[0]
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            return None
        if not isinstance(arguments, dict):
            return None
        return ToolCall(name=call.function.name, arguments=arguments)


def get_client() -> LLMClient:
    """Build a client from the environment.

    Raises:
        LLMUnavailableError: if ``LLM_API_KEY`` is not set, so a missing key is
            reported plainly instead of surfacing as a provider error.
    """

    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise LLMUnavailableError(
            "LLM_API_KEY is not set; the Ask Operations endpoint needs it."
        )
    return OpenAICompatibleClient(
        api_key=api_key, base_url=os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL
    )
