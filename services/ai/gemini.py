"""Gemini-backed assistant (LIVE mode), using the google-genai SDK with structured JSON output."""

from __future__ import annotations

import html
import logging
import secrets
from typing import Literal

from pydantic import BaseModel, ValidationError

from services import i18n
from services.ai.base import AIReply
from services.ai.prompt import build_system_prompt, looks_like_leak
from services.models import Knowledge
from services.retry import retry_async

log = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 1200


class _GeminiReply(BaseModel):
    """The assistant's reply to one barbershop customer message."""

    # Sent to Gemini as the response schema (the docstring becomes its description).
    # No defaults on purpose: every field must be filled.
    intent: Literal["faq", "booking", "human", "smalltalk"]
    found: bool
    answer: str


class GeminiAssistant:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 20.0,
        transport: object | None = None,  # an httpx transport; tests use httpx.MockTransport
    ) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        http_options = types.HttpOptions(
            timeout=int(timeout_seconds * 1000),  # milliseconds
            async_client_args={"transport": transport} if transport is not None else None,
        )
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self._model = model
        self._canary = secrets.token_hex(8)

    async def reply(self, message: str, lang: str, knowledge: Knowledge) -> AIReply:
        config = self._types.GenerateContentConfig(
            system_instruction=build_system_prompt(knowledge, lang, self._canary),
            response_mime_type="application/json",
            response_schema=_GeminiReply,
            temperature=0.2,
        )

        async def call():
            return await self._client.aio.models.generate_content(model=self._model, contents=message, config=config)

        response = await retry_async(call, op="gemini.generate_content")
        parsed = response.parsed if isinstance(response.parsed, _GeminiReply) else None
        if parsed is None:
            try:
                parsed = _GeminiReply.model_validate_json(response.text or "")
            except ValidationError as exc:
                raise RuntimeError(f"Gemini returned an unexpected response: {exc}") from exc

        answer = parsed.answer.strip()
        if looks_like_leak(answer, self._canary):
            log.warning("Blocked a Gemini answer that looked like a system-prompt leak")
            return AIReply(intent="smalltalk", answer=i18n.t("refuse", lang, shop=html.escape(knowledge.shop_name)))
        if not answer:
            answer_html = i18n.t("not_found", lang) if not parsed.found else ""
        else:
            answer_html = html.escape(answer[:MAX_ANSWER_CHARS])
        return AIReply(intent=parsed.intent, found=parsed.found, answer=answer_html)
