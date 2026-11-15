"""Keyword intent matching in three languages.

Used by the engine to route booking and "talk to a human" requests (and to
refuse prompt-extraction attempts) before any AI call, and by the offline
``MockAssistant`` to answer FAQ questions in DEMO mode.

Keyword syntax: ``book*`` = word starting with "book"; ``when`` = exact word;
``how much`` = phrase; ``bank card*`` = phrase where the starred word is a prefix.
Text and keywords are folded (lowercase, ə->e, ş->s, ё->е ...), so "qiymet" and
"qiymət" match the same keyword.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from services.models import FaqEntry, Knowledge


class Topic(Enum):
    PROBE = "probe"  # trying to extract the prompt / keys
    HUMAN = "human"
    BOOKING = "booking"
    PRICES = "prices"
    HOURS = "hours"
    ADDRESS = "address"
    FAQ = "faq"
    THANKS = "thanks"
    GREETING = "greeting"
    NONE = "none"


@dataclass(frozen=True)
class Match:
    topic: Topic
    faq: FaqEntry | None = None


_FOLD = str.maketrans({"ə": "e", "ı": "i", "ö": "o", "ü": "u", "ş": "s", "ç": "c", "ğ": "g", "ё": "е", "’": "'"})
_WORD_RE = re.compile(r"\w+")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold().replace("̇", "")  # "İ".casefold() -> "i̇"
    return text.translate(_FOLD)


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(fold(text))


@dataclass(frozen=True)
class _Keyword:
    parts: tuple[tuple[str, bool], ...]  # (folded word, is_prefix)

    @classmethod
    def parse(cls, raw: str) -> _Keyword | None:
        parts: list[tuple[str, bool]] = []
        for token in raw.split():
            sub_words = _words(token)  # "wi-fi" -> ["wi", "fi"]
            for index, word in enumerate(sub_words):
                parts.append((word, token.endswith("*") and index == len(sub_words) - 1))
        return cls(tuple(parts)) if parts else None

    def matches_at(self, words: list[str], start: int) -> bool:
        return all(
            words[start + i].startswith(word) if prefix else words[start + i] == word
            for i, (word, prefix) in enumerate(self.parts)
        )


def _compile(keywords: Iterable[str]) -> tuple[_Keyword, ...]:
    return tuple(k for k in (_Keyword.parse(raw) for raw in keywords) if k)


def _hits(words: list[str], keywords: Iterable[_Keyword]) -> int:
    """How many different keywords occur in the text (each counts once)."""
    return sum(
        any(kw.matches_at(words, i) for i in range(len(words) - len(kw.parts) + 1)) for kw in keywords
    )


_RAW: dict[Topic, list[str]] = {
    Topic.PROBE: [
        "system prompt", "your prompt", "the prompt", "ignore previous", "ignore all", "ignore your",
        "your instructions", "your rules",
        "api key*", "token*", "password*", "jailbreak*", "developer mode",
        "промпт*", "инструкци*", "игнорируй*", "пароль*", "токен*", "ключ api", "api ключ*",
        "təlimat*", "parol*", "tokeni*",
    ],
    Topic.HUMAN: [
        "human", "humans", "real person", "live person", "operator*", "manager*", "staff", "owner",
        "administrator*", "talk to a person",
        "живой человек", "живым человеком", "с человеком", "оператор*", "менеджер*", "администратор*",
        "сотрудник*", "позовите",
        "insan*", "canlı insan", "menecer*", "işçi*", "əməkdaş*",
    ],
    Topic.BOOKING: [
        "book*", "appointment*", "reserv*", "slot*", "availability",
        "запис*", "запиш*", "заброни*", "брон*", "свободное время", "свободное окно",
        "növbə*", "yazıl*", "yazdır*", "rezerv*", "bron*", "qeydiyyat*", "randevu*", "boş vaxt",
    ],
    Topic.PRICES: [
        "price*", "pricing", "cost*", "how much", "fee*", "cheap*", "expensive", "service*",
        "цен*", "стои*", "сколько", "почем", "прайс*", "услуг*", "дорог*", "дешев*",
        "qiymət*", "neçəyə", "nə qədər", "manat*", "pul*", "xidmət*", "baha*", "ucuz*",
    ],
    Topic.HOURS: [
        "hour*", "open*", "close*", "closing", "when", "working time*", "weekend*", "sunday*", "saturday*",
        "работае*", "открыв*", "открыт*", "закрыв*", "закрыт*", "график*", "часы работы", "режим работы",
        "время работы", "до скольки", "со скольки", "выходн*", "воскресень*", "суббот*",
        "iş saat*", "iş vaxt*", "açıq*", "açılır*", "açır*", "bağlı*", "bağlanır*", "işləyir*",
        "saat neçə*", "qrafik*", "bazar günü", "şənbə*", "istirahət*",
    ],
    Topic.ADDRESS: [
        "address*", "where", "location*", "located", "find you", "direction*", "map*", "metro", "how to get",
        "адрес*", "где", "находит*", "добрать*", "как найти", "метро", "локаци*", "на карте",
        "ünvan*", "harada", "harda", "hardasınız", "haradasınız", "yerləş*", "xəritə*", "necə gəlim",
    ],
    Topic.THANKS: [
        "thank*", "thx", "cheers", "спасибо", "благодар*", "спс", "sağ ol*", "sağol*", "təşəkkür*",
    ],
    Topic.GREETING: [
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "привет*", "здравствуй*", "добрый день", "доброе утро", "добрый вечер", "салам*",
        "salam*", "sabahınız xeyir", "axşamınız xeyir", "günortanız xeyir",
    ],
}

KEYWORDS: dict[Topic, tuple[_Keyword, ...]] = {topic: _compile(raw) for topic, raw in _RAW.items()}

_CANCEL_WORDS = frozenset(fold(w) for w in ("cancel", "stop", "отмена", "отменить", "стоп", "ləğv", "ləğv et", "dayan"))


def is_cancel(text: str) -> bool:
    """True for "cancel" in any language, including the Cancel button labels."""
    return " ".join(_words(text)) in _CANCEL_WORDS


def classify(text: str, knowledge: Knowledge | None = None) -> Match:
    words = _words(text)
    if not words:
        return Match(Topic.NONE)

    # Hard routes first: these never go to the AI.
    for topic in (Topic.PROBE, Topic.HUMAN, Topic.BOOKING):
        if _hits(words, KEYWORDS[topic]):
            return Match(topic)

    # Best-scoring information topic. Owner-defined FAQ entries win ties (they're more specific).
    candidates: list[tuple[int, int, Match]] = []
    for entry in knowledge.faq if knowledge else ():
        score = _hits(words, _compile(entry.keywords))
        if score:
            candidates.append((score, 3, Match(Topic.FAQ, entry)))
    for priority, topic in ((2, Topic.PRICES), (1, Topic.HOURS), (0, Topic.ADDRESS)):
        score = _hits(words, KEYWORDS[topic])
        if score:
            candidates.append((score, priority, Match(topic)))
    if candidates:
        return max(candidates, key=lambda c: (c[0], c[1]))[2]

    for topic in (Topic.THANKS, Topic.GREETING):
        if _hits(words, KEYWORDS[topic]):
            return Match(topic)
    return Match(Topic.NONE)
