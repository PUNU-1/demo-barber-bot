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
        from services.ai.gemini import GeminiAssistant
        from services.faq.sheets_store import SheetsKnowledge
        from services.schedule.google_calendar import GoogleCalendarSchedule

        assert settings.google_service_account_file and settings.google_sheet_id and settings.google_calendar_id
        assert settings.gemini_api_key is not None
        knowledge = CachedKnowledge(
            SheetsKnowledge(settings.google_service_account_file, settings.google_sheet_id),
            ttl_seconds=settings.faq_cache_seconds,
        )
        schedule = GoogleCalendarSchedule(settings.google_service_account_file, settings.google_calendar_id, tz)
        assistant = FallbackAssistant(
            GeminiAssistant(settings.gemini_api_key.get_secret_value(), settings.gemini_model),
            MockAssistant(),
        )
        log.info("LIVE mode: Gemini (%s), Google Sheets, Google Calendar", settings.gemini_model)
    else:
        knowledge = JsonKnowledge(settings.data_dir / "faq.json")
        schedule = JsonSchedule(settings.data_dir / "bookings.json")
        assistant = MockAssistant()
        log.info("DEMO mode: %s, %s, offline assistant", settings.data_dir / "faq.json", settings.data_dir / "bookings.json")

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
