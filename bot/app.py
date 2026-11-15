"""Composition root: picks DEMO or LIVE implementations and wires them into an Engine."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from bot.engine import Engine
from config import Settings
from services.ai import Assistant, FallbackAssistant, MockAssistant
from services.booking import BookingService
from services.faq import CachedKnowledge, JsonKnowledge, KnowledgeSource
from services.ratelimit import RateLimiter
from services.schedule import JsonSchedule, ScheduleBackend

log = logging.getLogger(__name__)


def _gemini_assistant(settings: Settings) -> Assistant:
    """Gemini, with the offline assistant answering whenever Gemini fails or is too slow."""
    from services.ai.gemini import GeminiAssistant  # google-genai is only imported when needed

    assert settings.gemini_api_key is not None
    gemini = GeminiAssistant(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        thinking_level=settings.gemini_thinking_level,
    )
    return FallbackAssistant(gemini, MockAssistant())


def build_engine(
    settings: Settings,
    *,
    owner_id: int | None,
    clock: Callable[[], datetime] | None = None,
) -> Engine:
    tz = settings.tz
    knowledge: KnowledgeSource
    schedule: ScheduleBackend
    assistant: Assistant

    if settings.is_live:
        # Imported here so DEMO mode never needs the Google libraries.
        from services.faq.sheets_store import SheetsKnowledge
        from services.schedule.google_calendar import GoogleCalendarSchedule

        assert settings.google_service_account_file and settings.google_sheet_id and settings.google_calendar_id
        knowledge = CachedKnowledge(
            SheetsKnowledge(settings.google_service_account_file, settings.google_sheet_id),
            ttl_seconds=settings.faq_cache_seconds,
        )
        schedule = GoogleCalendarSchedule(settings.google_service_account_file, settings.google_calendar_id, tz)
        assistant = _gemini_assistant(settings)
        log.info("LIVE mode: Gemini (%s), Google Sheets, Google Calendar", settings.gemini_model)
    else:
        knowledge = JsonKnowledge(settings.data_dir / "faq.json")
        schedule = JsonSchedule(settings.data_dir / "bookings.json")
        if settings.gemini_api_key is not None:
            # A Gemini key alone is enough for real AI answers: no Google Cloud setup needed.
            assistant = _gemini_assistant(settings)
            ai_name = f"Gemini ({settings.gemini_model})"
        else:
            assistant = MockAssistant()
            ai_name = "offline assistant"
        log.info("DEMO mode: %s, %s, %s", settings.data_dir / "faq.json", settings.data_dir / "bookings.json", ai_name)

    booking = BookingService(
        schedule,
        knowledge,
        tz=tz,
        days_ahead=settings.booking_days_ahead,
        step_minutes=settings.slot_step_minutes,
        min_lead_minutes=settings.min_lead_minutes,
        default_country_code=settings.default_country_code,
        clock=clock,
    )
    return Engine(
        knowledge=knowledge,
        booking=booking,
        assistant=assistant,
        owner_id=owner_id,
        rate_limiter=RateLimiter(settings.rate_limit_messages, settings.rate_limit_window_seconds),
        max_input_chars=settings.max_input_chars,
        default_country_code=settings.default_country_code,
    )
