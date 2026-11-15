"""The assistant interface and a fallback wrapper."""

from __future__ import annotations

import logging
from typing import Literal, Protocol

from pydantic import BaseModel

from services.models import Knowledge

log = logging.getLogger(__name__)

Intent = Literal["faq", "booking", "human", "smalltalk"]


class AIReply(BaseModel):
    intent: Intent = "faq"
    found: bool = True  # False = the shop data doesn't answer this; the engine offers a human
    answer: str = ""  # Telegram-safe HTML (already escaped)


class Assistant(Protocol):
    async def reply(self, message: str, lang: str, knowledge: Knowledge) -> AIReply: ...


class FallbackAssistant:
    """Use ``primary`` (Gemini); if it fails even after retries, answer with ``fallback`` (offline)."""

    def __init__(self, primary: Assistant, fallback: Assistant) -> None:
        self._primary = primary
        self._fallback = fallback

    async def reply(self, message: str, lang: str, knowledge: Knowledge) -> AIReply:
        try:
            return await self._primary.reply(message, lang, knowledge)
        except Exception as exc:
            log.warning("Primary assistant failed (%s: %s); using offline fallback", type(exc).__name__, exc)
            return await self._fallback.reply(message, lang, knowledge)
