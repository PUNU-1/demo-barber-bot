"""The assistant interface and a fallback wrapper."""

from __future__ import annotations

import asyncio
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
    """Use ``primary`` (Gemini); if it fails or is too slow, answer with ``fallback`` (offline).

    ``budget_seconds`` caps the whole primary call, retries included: a customer waiting in a chat
    should get some answer within seconds, not after every retry of an overloaded model.
    """

    def __init__(self, primary: Assistant, fallback: Assistant, *, budget_seconds: float = 12.0) -> None:
        self._primary = primary
        self._fallback = fallback
        self._budget = budget_seconds

    async def reply(self, message: str, lang: str, knowledge: Knowledge) -> AIReply:
        try:
            return await asyncio.wait_for(self._primary.reply(message, lang, knowledge), self._budget)
        except TimeoutError:
            log.warning("Primary assistant took over %.0fs; using offline fallback", self._budget)
        except Exception as exc:
            log.warning("Primary assistant failed (%s: %s); using offline fallback", type(exc).__name__, exc)
        return await self._fallback.reply(message, lang, knowledge)
