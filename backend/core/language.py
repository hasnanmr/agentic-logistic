"""A minimal, non-LLM language guess for the one path that must work without
the model.

For the main Ask Operations path, the model itself names the question's
language as a tool-call argument (see ``backend.tools.agent``'s ``language``
field) - it already interprets the question either way (PRD 9), and it reads
grammar and code-switching far more reliably than a hand-built word list
ever could. A hand-built list is exactly what broke on ordinary code-switched
questions like "tampilkan total orders per carrier" (English field names
inside an Indonesian sentence), which is why this module carries no such list.

The one place that still needs a guess with no model involved is the carrier
glossary (:mod:`backend.core.carrier_knowledge`), which resolves *before* the LLM
agent is built on purpose - so glossary questions keep working even when the
model provider is unavailable. That trade-off is deliberate: a plain
statistical detector is worse than the model, but it is offline, dependency-
light, and only ever backs a short glossary lookup, not the main answer path.
"""

from __future__ import annotations

import re
from typing import Final

from backend.core.schemas import SmalltalkLanguage


#: Same Han-script ranges as smalltalk.py's greeting scanner. Script alone is
#: a reliable, cheap signal for Chinese regardless of text length.
_HAN_CHAR: Final = re.compile(r"[㐀-䶿一-鿿]")


def detect_language(text: str) -> SmalltalkLanguage:
    """Best-effort guess at which of id/en/zh a short glossary question is in.

    Defaults to English when the statistical detector is unavailable or
    returns something outside the three supported languages - the safest
    default given the carrier glossary's own source material is in English.
    """

    if _HAN_CHAR.search(text):
        return "zh"

    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        code = detect(text)
    except Exception:
        return "en"

    if code in {"id", "ms"}:
        return "id"
    if code.startswith("zh"):
        return "zh"
    return "en"
