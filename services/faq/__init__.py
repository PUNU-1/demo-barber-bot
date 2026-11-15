"""FAQ / shop data. DEMO: ``JsonKnowledge`` (faq.json). LIVE: ``SheetsKnowledge`` behind ``CachedKnowledge``."""

from __future__ import annotations

from typing import Protocol

from services.models import Knowledge


class KnowledgeSource(Protocol):
    async def get(self) -> Knowledge: ...


from services.faq.cache import CachedKnowledge  # noqa: E402
from services.faq.json_store import JsonKnowledge  # noqa: E402
from services.faq.parsing import parse_knowledge  # noqa: E402


class StaticKnowledge:
    """Fixed data, handy for tests."""

    def __init__(self, knowledge: Knowledge) -> None:
        self._knowledge = knowledge

    async def get(self) -> Knowledge:
        return self._knowledge


__all__ = ["CachedKnowledge", "JsonKnowledge", "KnowledgeSource", "StaticKnowledge", "parse_knowledge"]
