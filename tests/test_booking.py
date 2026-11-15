"""Booking validation and double-booking protection."""

import asyncio
from datetime import date, datetime, time

import pytest

from services.booking import (
    ID_ALPHABET,
    ID_LENGTH,
    BookingRequest,
    BookingService,
    InvalidName,
    InvalidPhone,
    SlotTaken,
    SlotUnavailable,
    UnknownService,
    normalize_name,
    normalize_phone,
)
from services.faq import StaticKnowledge
from services.schedule import JsonSchedule
from tests.conftest import TZ

TUESDAY = date(2026, 11, 17)


def at(hour: int, minute: int = 0, day: date = TUESDAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


def request(start: datetime, service_id: str = "haircut", name: str = "Ali", phone: str = "+994501234567"):
    return BookingRequest(service_id=service_id, start=start, customer_name=name, phone=phone, user_id=42, lang="en")


# -- name and phone validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ali", "Ali"),
        ("  Anna    Maria ", "Anna Maria"),
        ("Aysel Məmmədova", "Aysel Məmmədova"),
        ("Анна-Мария", "Анна-Мария"),
        ("O'Neil", "O'Neil"),
        ("J. Smith", "J. Smith"),
    ],
)
def test_valid_names_are_normalized(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "A", "Ali123", "x" * 51, "!!!", "<b>Ali</b>", "Ali  --  Veli", "12345"])
def test_invalid_names_are_rejected(raw):
    with pytest.raises(InvalidName):
        normalize_name(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+994 50 123 45 67", "+994501234567"),
        ("050-123-45-67", "+994501234567"),
        ("(050) 123 45 67", "+994501234567"),
        ("00994501234567", "+994501234567"),
        ("994501234567", "+994501234567"),
        ("50 123 45 67", "+994501234567"),
        ("+44 20 7946 0958", "+442079460958"),
    ],
)
def test_valid_phones_become_e164(raw, expected):
    assert normalize_phone(raw, "994") == expected


@pytest.mark.parametrize("raw", ["", "abc", "123", "+12", "+9945012345678901234", "050 12a 45 67", "+994 50 123 45 67 ext 2"])
def test_invalid_phones_are_rejected(raw):
    with pytest.raises(InvalidPhone):
        normalize_phone(raw, "994")


# -- availability ---------------------------------------------------------------------------------


async def test_available_days_skip_sundays_and_stay_in_window(booking_service, knowledge):
    days = await booking_service.available_days(knowledge.service("haircut"))
    assert days[0] == date(2026, 11, 16)  # today still has slots (now is 09:00, opening 10:00)
    assert len(days) == 12  # 14-day window minus Sundays 22 and 29 Nov
    assert all(d.weekday() != 6 for d in days)


async def test_fully_booked_day_disappears_from_available_days(booking_service, knowledge):
    combo = knowledge.service("combo")
    for hour in range(10, 20):  # book Tuesday solid with one-hour services
        await booking_service.book(request(at(hour), service_id="combo"))
    days = await booking_service.available_days(combo)
    assert TUESDAY not in days


# -- creating bookings ----------------------------------------------------------------------------


async def test_booking_is_saved_and_slot_disappears(booking_service, schedule, knowledge):
    booking = await booking_service.book(request(at(14), name="  Ali   Aliyev ", phone="050 123 45 67"))
    assert len(booking.id) == ID_LENGTH and set(booking.id) <= set(ID_ALPHABET)
    assert booking.customer_name == "Ali Aliyev"
    assert booking.phone == "+994501234567"
    assert booking.end == at(14, 30)
    assert await schedule.get(booking.id) == booking
    assert at(14) not in await booking_service.free_slots(TUESDAY, knowledge.service("haircut"))


async def test_same_slot_cannot_be_booked_twice(booking_service):
    await booking_service.book(request(at(15)))
    with pytest.raises(SlotTaken):
        await booking_service.book(request(at(15), name="Veli"))


async def test_overlapping_longer_service_is_rejected(booking_service):
    await booking_service.book(request(at(12), service_id="combo"))  # 12:00-13:00
    with pytest.raises(SlotTaken):
        await booking_service.book(request(at(12, 30)))
    assert await booking_service.book(request(at(13)))  # right after is fine


class SlowSchedule(JsonSchedule):
    """Yields to the event loop like a real network backend would, so a missing lock would show."""

    async def busy_intervals(self, start, end):
        await asyncio.sleep(0.01)
        return await super().busy_intervals(start, end)

    async def create(self, booking):
        await asyncio.sleep(0.01)
        await super().create(booking)


async def test_concurrent_requests_for_one_slot_produce_exactly_one_booking(tmp_path, knowledge, clock):
    schedule = SlowSchedule(tmp_path / "bookings.json")
    service = BookingService(schedule, StaticKnowledge(knowledge), tz=TZ, clock=clock)
    results = await asyncio.gather(
        *(service.book(request(at(16), name=n)) for n in ("Ali", "Veli", "Leyla", "Nigar")),
        return_exceptions=True,
    )
    booked = [r for r in results if not isinstance(r, Exception)]
    assert len(booked) == 1
    assert all(isinstance(r, SlotTaken) for r in results if isinstance(r, Exception))
    assert len(await schedule.list_between(at(0), at(23, 59))) == 1


@pytest.mark.parametrize(
    "start",
    [
        datetime(2026, 11, 16, 8, 0, tzinfo=TZ),  # in the past (now is Mon 09:00)
        datetime(2026, 11, 16, 9, 30, tzinfo=TZ),  # before opening
        at(21),  # after closing
        at(19, 45),  # off the 30-minute grid
        at(10, 10),  # off the grid
        datetime(2026, 11, 22, 12, 0, tzinfo=TZ),  # Sunday: closed
        datetime(2026, 12, 8, 12, 0, tzinfo=TZ),  # beyond the 14-day window
    ],
)
async def test_slot_rules_are_enforced_on_booking(booking_service, start):
    with pytest.raises(SlotUnavailable):
        await booking_service.book(request(start))


async def test_minimum_lead_time_is_enforced(booking_service, clock):
    clock.now = datetime(2026, 11, 16, 10, 20, tzinfo=TZ)  # earliest bookable start: 11:20
    with pytest.raises(SlotUnavailable):
        await booking_service.book(request(datetime(2026, 11, 16, 11, 0, tzinfo=TZ)))
    assert await booking_service.book(request(datetime(2026, 11, 16, 11, 30, tzinfo=TZ)))


async def test_service_must_fit_before_closing(booking_service):
    with pytest.raises(SlotUnavailable):
        await booking_service.book(request(at(19, 30), service_id="combo"))  # would end at 20:30


async def test_unknown_service_is_rejected(booking_service):
    with pytest.raises(UnknownService):
        await booking_service.book(request(at(12), service_id="massage"))


async def test_invalid_customer_details_are_rejected(booking_service):
    with pytest.raises(InvalidName):
        await booking_service.book(request(at(12), name="1"))
    with pytest.raises(InvalidPhone):
        await booking_service.book(request(at(12), phone="call me"))


async def test_cancel_frees_the_slot_and_is_idempotent(booking_service, knowledge):
    booking = await booking_service.book(request(at(17)))
    cancelled = await booking_service.cancel(f"#{booking.id.lower()}")  # forgiving input
    assert cancelled is not None and not cancelled.is_active
    assert await booking_service.cancel(booking.id) is None
    assert at(17) in await booking_service.free_slots(TUESDAY, knowledge.service("haircut"))
    assert await booking_service.cancel("NOPE42") is None
