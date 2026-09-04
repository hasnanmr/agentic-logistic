"""Thin boundary around the language model.

Only two things live here: where credentials come from and how the chat model
is constructed. Keeping that in one small module means the agent can be built
against a scripted model in tests with no API key, and swapping providers
touches nothing else.

The model's job is choosing tools and their arguments. It never sees the
dataset and never produces a number - see :mod:`backend.tools.agent`.
"""

from __future__ import annotations

import os
from typing import Final

from langchain_core.language_models import BaseChatModel


# OpenRouter speaks the OpenAI chat-completions protocol, so the OpenAI client
# works against it unchanged; its model ids carry a provider prefix.
DEFAULT_MODEL: Final = "openai/gpt-5.6-luna"
DEFAULT_BASE_URL: Final = "https://openrouter.ai/api/v1"


class LLMUnavailableError(RuntimeError):
    """Raised when no language-model credentials are configured."""


def build_chat_model(
    api_key: str, base_url: str | None = None, model: str | None = None
) -> BaseChatModel:
    """A chat model for any OpenAI-compatible endpoint.

    ``temperature=0`` because tool choice should be reproducible: the same
    question must route to the same tool with the same arguments.
    """

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL,
        api_key=api_key,
        base_url=base_url or os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL,
        temperature=0,
    )


def require_api_key() -> str:
    """The configured credential, or a plain explanation of its absence.

    Checked separately from model construction so a missing key is reported the
    same way whether or not the agent has already been built and cached.

    Raises:
        LLMUnavailableError: if ``LLM_API_KEY`` is not set, so a missing key is
            reported plainly instead of surfacing as a provider error.
    """

    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise LLMUnavailableError(
            "LLM_API_KEY is not set; the Ask Operations endpoint needs it."
        )
    return api_key


def get_chat_model() -> BaseChatModel:
    """Build the configured chat model from the environment."""

    return build_chat_model(api_key=require_api_key())
