"""Shared fixtures. Tests never touch the network, the real .env or data/bookings.json."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from bot.engine import Engine, Incoming, Outcome
from services.ai import MockAssistant
from services.booking import BookingService
from services.faq import StaticKnowledge, parse_knowledge
from services.models import Knowledge
from services.ratelimit import RateLimiter
from services.schedule import JsonSchedule

TZ = ZoneInfo("Asia/Baku")
OWNER_ID = 1000
CUSTOMER_ID = 2000

# Monday 16 November 2026, 09:00 in Baku. The shop opens at 10:00.
MONDAY_9AM = datetime(2026, 11, 16, 9, 0, tzinfo=TZ)

SHOP_DATA = {
    "info": {"shop_name": "Test Barber", "address": "1 Test St", "phone": "+994 12 000 00 00", "currency": "AZN"},
    "hours": [
        {"day": "Monday", "open": "10:00", "close": "20:00"},
        {"day": "Tuesday", "open": "10:00", "close": "20:00"},
        {"day": "Wednesday", "open": "10:00", "close": "20:00"},
        {"day": "Thursday", "open": "10:00", "close": "20:00"},
        {"day": "Friday", "open": "10:00", "close": "20:00"},
        {"day": "Saturday", "open": "10:00", "close": "18:00"},
        {"day": "Sunday", "open": "", "close": ""},
    ],
    "services": [
        {"id": "haircut", "name_en": "Men's haircut", "name_ru": "Мужская стрижка", "name_az": "Kişi saç kəsimi",
         "duration_min": 30, "price": 15},
        {"id": "combo", "name_en": "Haircut + beard", "name_ru": "Стрижка + борода", "name_az": "Saç + saqqal",
         "duration_min": 60, "price": 22},
    ],
    "faq": [
        {"question": "Do you accept cards?", "answer_en": "Yes, cards and cash.",
         "answer_ru": "Да, карты и наличные.", "answer_az": "Bəli, kart və nağd.",
         "keywords": "card*, cash, карт*, налич*, kart*, nağd*"},
    ],
}


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(MONDAY_9AM)


@pytest.fixture
def knowledge() -> Knowledge:
    return parse_knowledge(SHOP_DATA)


@pytest.fixture
def schedule(tmp_path) -> JsonSchedule:
    return JsonSchedule(tmp_path / "bookings.json")


@pytest.fixture
def booking_service(schedule, knowledge, clock) -> BookingService:
    return BookingService(
        schedule,
        StaticKnowledge(knowledge),
        tz=TZ,
        days_ahead=14,
        step_minutes=30,
        min_lead_minutes=60,
        clock=clock,
    )


def make_engine(booking_service: BookingService, knowledge: Knowledge, *, limiter: RateLimiter | None = None,
                owner_id: int | None = OWNER_ID) -> Engine:
    return Engine(
        knowledge=StaticKnowledge(knowledge),
        booking=booking_service,
        assistant=MockAssistant(),
        owner_id=owner_id,
        rate_limiter=limiter or RateLimiter(1000, 60),
        max_input_chars=500,
    )


@pytest.fixture
def engine(booking_service, knowledge) -> Engine:
    return make_engine(booking_service, knowledge)


class Chat:
    """Drives the engine like a Telegram user would: send text, press buttons by label or data."""

    def __init__(self, engine: Engine, user_id: int = CUSTOMER_ID, language_code: str | None = "en") -> None:
        self.engine = engine
        self.user_id = user_id
        self.language_code = language_code
        self.last: Outcome = Outcome()

    async def send(self, text: str) -> Outcome:
        self.last = await self.engine.handle(
            Incoming(user_id=self.user_id, text=text, language_code=self.language_code, display_name="Test User")
        )
        return self.last

    async def press(self, data: str) -> Outcome:
        self.last = await self.engine.handle(
            Incoming(user_id=self.user_id, callback=data, language_code=self.language_code, display_name="Test User")
        )
        return self.last

    async def share_contact(self, phone: str) -> Outcome:
        self.last = await self.engine.handle(
            Incoming(user_id=self.user_id, contact_phone=phone, language_code=self.language_code)
        )
        return self.last

    def buttons(self) -> list[str]:
        return [b.data for r in self.last.replies for row in r.buttons for b in row]

    def first_button(self, prefix: str) -> str:
        return next(d for d in self.buttons() if d.startswith(prefix))

    def text(self) -> str:
        return "\n".join(r.text for r in self.last.replies)
