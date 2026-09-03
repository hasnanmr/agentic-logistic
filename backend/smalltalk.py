"""Template replies for greetings and other conversational filler.

A greeting is not an analytics question: there is nothing to compute, no tool
to call and no figure to ground. Routing "halo, selamat pagi" through the agent
spends a model call and a second of latency to produce a sentence application
code can write itself, so the whole class is resolved here - before the agent
is even built, which also keeps greetings working while the model provider is
unavailable.

Matching is deliberately conservative. A message is smalltalk only when *every*
part of it is a greeting phrase or harmless filler, so "hi, which carrier is
slowest?" falls straight through to the agent. Three languages are recognised
because the product is used in them: Indonesian, English and Chinese.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

from backend.schemas import SmalltalkIntent, SmalltalkLanguage


#: Longest phrase in the Latin table, in tokens.
_MAX_PHRASE_TOKENS: Final = 3

#: Anything longer than a greeting is a question that happens to open with one.
#: A cheap length guard keeps the scanner off every real question.
_MAX_LENGTH: Final = 64

#: Which reading wins when a message carries more than one - "halo selamat
#: pagi" is answered as a morning greeting, not a bare hello.
_INTENT_PRIORITY: Final[tuple[SmalltalkIntent, ...]] = (
    "morning",
    "noon",
    "afternoon",
    "evening",
    "thanks",
    "farewell",
    "hello",
)

_LATIN_PHRASES: Final[dict[str, tuple[SmalltalkIntent, SmalltalkLanguage]]] = {
    # Indonesian. The bare time word is included because "pagi" on its own is
    # how people actually greet in chat.
    "selamat pagi": ("morning", "id"),
    "pagi": ("morning", "id"),
    "selamat siang": ("noon", "id"),
    "siang": ("noon", "id"),
    "selamat sore": ("afternoon", "id"),
    "sore": ("afternoon", "id"),
    "selamat malam": ("evening", "id"),
    "malam": ("evening", "id"),
    "halo": ("hello", "id"),
    "hallo": ("hello", "id"),
    "hai": ("hello", "id"),
    "apa kabar": ("hello", "id"),
    "apa kabarnya": ("hello", "id"),
    "assalamualaikum": ("hello", "id"),
    "assalamu alaikum": ("hello", "id"),
    "salam": ("hello", "id"),
    "permisi": ("hello", "id"),
    "terima kasih": ("thanks", "id"),
    "makasih": ("thanks", "id"),
    "trims": ("thanks", "id"),
    "sampai jumpa": ("farewell", "id"),
    "dadah": ("farewell", "id"),
    # English.
    "good morning": ("morning", "en"),
    "good afternoon": ("afternoon", "en"),
    "good evening": ("evening", "en"),
    "good night": ("evening", "en"),
    "hello": ("hello", "en"),
    "hi": ("hello", "en"),
    "hey": ("hello", "en"),
    "howdy": ("hello", "en"),
    "good day": ("hello", "en"),
    "how are you": ("hello", "en"),
    "thanks": ("thanks", "en"),
    "thank you": ("thanks", "en"),
    "bye": ("farewell", "en"),
    "goodbye": ("farewell", "en"),
    "see you": ("farewell", "en"),
    "see ya": ("farewell", "en"),
}

_HAN_PHRASES: Final[dict[str, tuple[SmalltalkIntent, SmalltalkLanguage]]] = {
    "早上好": ("morning", "zh"),
    "早安": ("morning", "zh"),
    "早": ("morning", "zh"),
    "中午好": ("noon", "zh"),
    "下午好": ("afternoon", "zh"),
    "晚上好": ("evening", "zh"),
    "晚安": ("evening", "zh"),
    "你好": ("hello", "zh"),
    "您好": ("hello", "zh"),
    "大家好": ("hello", "zh"),
    "哈囉": ("hello", "zh"),
    "哈罗": ("hello", "zh"),
    "嗨": ("hello", "zh"),
    "谢谢": ("thanks", "zh"),
    "謝謝": ("thanks", "zh"),
    "多谢": ("thanks", "zh"),
    "感谢": ("thanks", "zh"),
    "再见": ("farewell", "zh"),
    "再見": ("farewell", "zh"),
    "拜拜": ("farewell", "zh"),
}

#: Words that may sit beside a greeting without changing it. They carry no
#: intent of their own, so a message made only of them is not smalltalk.
_LATIN_FILLERS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "again",
        "all",
        "and",
        "bang",
        "banget",
        "bot",
        "dear",
        "doing",
        "dong",
        "everyone",
        "folks",
        "gan",
        "guys",
        "juga",
        "kak",
        "lot",
        "mas",
        "mbak",
        "min",
        "much",
        "nih",
        "semua",
        "team",
        "there",
        "very",
        "ya",
    }
)
_HAN_FILLERS: Final[frozenset[str]] = frozenset("啊呀呢吧哦噢嗯了哈呐么嘛们")

_HAN_RUN: Final = re.compile(r"([㐀-䶿一-鿿]+)")
_PUNCTUATION: Final = re.compile(r"[^\w\s]|_", re.UNICODE)
_REPEATED: Final = re.compile(r"(.)\1+")

#: What the assistant offers, appended to every reply that opens a
#: conversation. Kept in the greeting's own language.
_INVITATIONS: Final[dict[SmalltalkLanguage, str]] = {
    "id": (
        "Saya asisten analitik pengiriman. Tanyakan soal keterlambatan, waktu "
        "pengiriman, jumlah order, atau perkiraan permintaan — misalnya "
        '"kurir mana yang paling sering telat bulan lalu?"'
    ),
    "en": (
        "I am the delivery analytics assistant. Ask about delays, delivery "
        "time, order volume, or demand forecasts — for example "
        '"which carrier has the highest delay rate last month?"'
    ),
    "zh": (
        "我是物流分析助手，可以问我延误率、配送时长、订单量或需求预测，"
        "例如“上个月哪家承运商的延误率最高？”"
    ),
}

_CLOSINGS: Final[dict[SmalltalkLanguage, str]] = {
    "id": "Sampai jumpa lagi kapan saja Anda perlu analisis pengiriman.",
    "en": "Come back any time you need a delivery analysis.",
    "zh": "需要分析配送数据时随时回来。",
}

_OPENERS: Final[dict[SmalltalkLanguage, dict[SmalltalkIntent, str]]] = {
    "id": {
        "morning": "Halo, selamat pagi!",
        "noon": "Halo, selamat siang!",
        "afternoon": "Halo, selamat sore!",
        "evening": "Halo, selamat malam!",
        "hello": "Halo!",
        "thanks": "Sama-sama!",
        "farewell": "Sampai jumpa!",
    },
    "en": {
        "morning": "Good morning!",
        "afternoon": "Good afternoon!",
        "evening": "Good evening!",
        "hello": "Hello!",
        "thanks": "You are welcome!",
        "farewell": "Goodbye!",
    },
    "zh": {
        "morning": "早上好！",
        "noon": "中午好！",
        "afternoon": "下午好！",
        "evening": "晚上好！",
        "hello": "你好！",
        "thanks": "不客气！",
        "farewell": "再见！",
    },
}


@dataclass(frozen=True)
class SmalltalkMatch:
    """A recognised greeting and the reply written for it."""

    intent: SmalltalkIntent
    language: SmalltalkLanguage
    reply: str


def _collapse(token: str) -> str:
    """Fold stretched spellings together: ``haloo`` and ``hallo`` both to ``halo``.

    Applied to the tables as well as to the input, so the two always agree.
    """

    return _REPEATED.sub(r"\1", token)


_COLLAPSED_LATIN: Final[dict[str, tuple[SmalltalkIntent, SmalltalkLanguage]]] = {
    " ".join(_collapse(token) for token in phrase.split()): value
    for phrase, value in _LATIN_PHRASES.items()
}
_COLLAPSED_FILLERS: Final[frozenset[str]] = frozenset(
    _collapse(word) for word in _LATIN_FILLERS
)
_MAX_HAN_PHRASE: Final = max(len(phrase) for phrase in _HAN_PHRASES)


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation and emoji, collapse whitespace.

    Digits survive because they are not greeting material: a message carrying
    one fails to match and goes to the agent, which is the wanted outcome.
    """

    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", _PUNCTUATION.sub(" ", folded)).strip()


def _scan_latin(segment: str) -> list[tuple[SmalltalkIntent, SmalltalkLanguage]] | None:
    """Match a whitespace-delimited run, longest phrase first.

    Returns ``None`` as soon as a token is neither part of a greeting nor a
    filler - that word makes the message something other than smalltalk.
    """

    tokens = [_collapse(token) for token in segment.split()]
    found: list[tuple[SmalltalkIntent, SmalltalkLanguage]] = []
    index = 0
    while index < len(tokens):
        for width in range(_MAX_PHRASE_TOKENS, 0, -1):
            phrase = " ".join(tokens[index : index + width])
            match = _COLLAPSED_LATIN.get(phrase)
            if match is not None:
                found.append(match)
                index += width
                break
        else:
            if tokens[index] not in _COLLAPSED_FILLERS:
                return None
            index += 1
    return found


def _scan_han(segment: str) -> list[tuple[SmalltalkIntent, SmalltalkLanguage]] | None:
    """Match a run of Han characters, which carries no word boundaries."""

    found: list[tuple[SmalltalkIntent, SmalltalkLanguage]] = []
    index = 0
    while index < len(segment):
        for width in range(_MAX_HAN_PHRASE, 0, -1):
            match = _HAN_PHRASES.get(segment[index : index + width])
            if match is not None:
                found.append(match)
                index += width
                break
        else:
            if segment[index] not in _HAN_FILLERS:
                return None
            index += 1
    return found


def _detect(question: str) -> tuple[SmalltalkIntent, SmalltalkLanguage] | None:
    """The reading of a message that is nothing but greeting, or ``None``."""

    normalized = _normalize(question)
    if not normalized or len(normalized) > _MAX_LENGTH:
        return None

    found: list[tuple[SmalltalkIntent, SmalltalkLanguage]] = []
    for index, segment in enumerate(_HAN_RUN.split(normalized)):
        if not segment.strip():
            continue
        # split() alternates: odd positions are the captured Han runs.
        scanned = _scan_han(segment) if index % 2 else _scan_latin(segment)
        if scanned is None:
            return None
        found += scanned

    if not found:
        return None

    intent = min(found, key=lambda match: _INTENT_PRIORITY.index(match[0]))[0]
    language = next(match[1] for match in found if match[0] == intent)
    return intent, language


def is_smalltalk(question: str) -> bool:
    """Whether a message is a greeting the templates can answer.

    Used by the API layer to skip building the agent, so a greeting needs no
    credentials and no model call.
    """

    return _detect(question) is not None


def compose_smalltalk_answer(question: str) -> SmalltalkMatch | None:
    """The template reply for a greeting, or ``None`` for a real question."""

    detected = _detect(question)
    if detected is None:
        return None

    intent, language = detected
    openers = _OPENERS[language]
    # Languages differ in which greetings they have a word for; the generic
    # hello stands in when one is missing.
    opener = openers.get(intent) or openers["hello"]
    tail = _CLOSINGS[language] if intent == "farewell" else _INVITATIONS[language]
    separator = "" if language == "zh" else " "
    return SmalltalkMatch(
        intent=intent, language=language, reply=f"{opener}{separator}{tail}"
    )
