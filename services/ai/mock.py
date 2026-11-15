"""Offline assistant for DEMO mode (and fallback in LIVE mode).

No model: keyword intents (``services.intents``) pick a topic, and the answer is
rendered from the shop data. Like the real assistant, it never makes anything
up. Questions it can't match get ``found=False``.
"""

from __future__ import annotations

from html import escape

from services import i18n
from services.ai.base import AIReply
from services.intents import Topic, classify
from services.models import Knowledge


class MockAssistant:
    async def reply(self, message: str, lang: str, knowledge: Knowledge) -> AIReply:
        match = classify(message, knowledge)
        topic = match.topic
        if topic is Topic.BOOKING:
            return AIReply(intent="booking")
        if topic is Topic.HUMAN:
            return AIReply(intent="human")
        if topic is Topic.PROBE:
            return AIReply(intent="smalltalk", answer=i18n.t("refuse", lang, shop=escape(knowledge.shop_name)))
        if topic is Topic.PRICES:
            return AIReply(answer=i18n.render_prices(knowledge, lang))
        if topic is Topic.HOURS:
            return AIReply(answer=i18n.render_hours(knowledge, lang))
        if topic is Topic.ADDRESS:
            return AIReply(answer=i18n.render_address(knowledge, lang))
        if topic is Topic.FAQ and match.faq is not None:
            return AIReply(answer=escape(match.faq.answer(lang)))
        if topic is Topic.THANKS:
            return AIReply(intent="smalltalk", answer=i18n.t("thanks", lang))
        if topic is Topic.GREETING:
            return AIReply(intent="smalltalk", answer=i18n.t("greeting", lang))
        return AIReply(found=False, answer=i18n.t("not_found", lang))
