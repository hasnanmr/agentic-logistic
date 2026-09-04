"""The non-LLM language guess used only by the carrier glossary bypass.

The main Ask Operations path no longer uses this module at all - the model
names the question's language itself as a tool-call argument (see
``backend.tools.agent``), which is what ``test_answer_localization.py`` covers.
This module backs one narrower, offline path: carrier glossary questions,
answered before the LLM agent is even built so they keep working without a
model provider.
"""

from __future__ import annotations

import pytest

from backend.core.language import detect_language


@pytest.mark.parametrize(
    "question",
    [
        "Apa itu UPS?",
        "Jelaskan masing-masing carrier",
        "carrier apa saja yang tersedia?",
    ],
)
def test_detects_indonesian(question: str) -> None:
    assert detect_language(question) == "id"


@pytest.mark.parametrize(
    "question",
    [
        "What is DHL?",
        "list of carriers",
        "tell me about USPS",
        "definition of DPD",
    ],
)
def test_detects_english(question: str) -> None:
    assert detect_language(question) == "en"


@pytest.mark.parametrize(
    "question",
    [
        "什么是DHL？",
        "介绍一下UPS",
        "承运商列表",
    ],
)
def test_detects_chinese_by_script(question: str) -> None:
    assert detect_language(question) == "zh"


@pytest.mark.parametrize("question", ["GLS", "DHL", "UPS", ""])
def test_ambiguous_or_empty_text_defaults_to_english(question: str) -> None:
    """A bare carrier name or empty text carries no real language signal -
    the safe default matches the glossary's own English source material."""

    assert detect_language(question) == "en"
