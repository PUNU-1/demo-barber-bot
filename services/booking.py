"""Booking rules: input validation, slot rules and double-booking protection."""

from __future__ import annotations

import asyncio
import re
import secrets
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from services import slots
from services.faq import KnowledgeSource
from services.models import DEFAULT_LANGUAGE, Booking, Knowledge, Service
from services.schedule import ScheduleBackend

NAME_MIN_LEN = 2
NAME_MAX_LEN = 50
ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I: easy to read out over the phone
ID_LENGTH = 6


class BookingError(Exception):
    """Base class. ``code`` is the i18n key of the message shown to the customer."""

    code = "booking_failed"


class InvalidName(BookingError):
    code = "invalid_name"


class InvalidPhone(BookingError):
    code = "invalid_phone"


class UnknownService(BookingError):
    code = "unknown_service"


class SlotUnavailable(BookingError):
    """The time breaks a rule: outside hours, in the past, too soon, off-grid or outside the window."""

    code = "slot_unavailable"


class SlotTaken(BookingError):
    """Someone else already booked an overlapping time."""

    code = "slot_taken"


# Unicode letters, single separators between words (space, apostrophe, hyphen, "J. Smith").
_NAME_RE = re.compile(r"^[^\W\d_]+(?:(?:[ '’\-]|\.\s?)[^\W\d_]+)*\.?$")
_PHONE_SEPARATORS = re.compile(r"[\s\-().]")


def normalize_name(raw: str) -> str:
    name = " ".join(unicodedata.normalize("NFC", raw or "").split())
    if not NAME_MIN_LEN <= len(name) <= NAME_MAX_LEN or not _NAME_RE.match(name):
        raise InvalidName(raw)
    return name


def normalize_phone(raw: str, default_country_code: str = "994") -> str:
    """Return the number in E.164 form (``+994501234567``) or raise ``InvalidPhone``.

    Accepted: ``+994 50 123 45 67``, ``00994501234567``, ``994501234567`` and local numbers
    of the default country with or without the trunk ``0`` (``050 123 45 67``, ``50 123 45 67``).
    """
    phone = _PHONE_SEPARATORS.sub("", (raw or "").strip())
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    if phone.startswith("+"):
        digits = phone[1:]
    elif phone.startswith("0"):
        digits = default_country_code + phone[1:]
    elif phone.startswith(default_country_code) and len(phone) > len(default_country_code) + 7:
        digits = phone
    else:
        digits = default_country_code + phone
    if not re.fullmatch(r"[0-9]{8,15}", digits):
        raise InvalidPhone(raw)
    return "+" + digits


def new_booking_id() -> str:
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


def normalize_booking_id(raw: str) -> str:
    return raw.strip().lstrip("#").upper()


@dataclass(frozen=True)
class BookingRequest:
    service_id: str
    start: datetime
    customer_name: str
    phone: str
    user_id: int | None = None
    lang: str = DEFAULT_LANGUAGE


class BookingService:
    """Answers "what's free?" and creates bookings without ever double-booking the chair."""

    def __init__(
        self,
        schedule: ScheduleBackend,
        knowledge: KnowledgeSource,
        *,
        tz: ZoneInfo,
        days_ahead: int = 14,
        step_minutes: int = 30,
        min_lead_minutes: int = 60,
        default_country_code: str = "994",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._schedule = schedule
        self._knowledge = knowledge
        self._tz = tz
        self._days_ahead = days_ahead
        self._step = timedelta(minutes=step_minutes)
        self._lead = timedelta(minutes=min_lead_minutes)
        self._country_code = default_country_code
        self._clock = clock or (lambda: datetime.now(tz))
        # Serialises check-then-create so two customers can't grab the same slot at once.
        self._lock = asyncio.Lock()

    # -- time helpers -----------------------------------------------------------------------------

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    @property
    def days_ahead(self) -> int:
        return self._days_ahead

    def now(self) -> datetime:
        return self._clock().astimezone(self._tz)

    def today(self) -> date:
        return self.now().date()

    def window_days(self) -> list[date]:
        return slots.booking_days(self.today(), self._days_ahead)

    def day_start(self, day: date) -> datetime:
        return datetime.combine(day, time.min, tzinfo=self._tz)

    def _slots_for(self, k: Knowledge, day: date, service: Service, busy, now: datetime) -> list[datetime]:
        return slots.free_slots(
            day,
            k.window(day.weekday()),
            service.duration,
            busy,
            now=now,
            tz=self._tz,
            step=self._step,
            min_lead=self._lead,
        )

    # -- queries ----------------------------------------------------------------------------------

    async def available_days(self, service: Service) -> list[date]:
        """Days in the booking window with at least one free slot for ``service``."""
        k = await self._knowledge.get()
        now = self.now()
        days = self.window_days()
        busy = await self._schedule.busy_intervals(now, self.day_start(days[-1] + timedelta(days=1)))
        return [day for day in days if self._slots_for(k, day, service, busy, now)]

    async def free_slots(self, day: date, service: Service) -> list[datetime]:
        if day not in self.window_days():
            return []
        k = await self._knowledge.get()
        start = self.day_start(day)
        busy = await self._schedule.busy_intervals(start, start + timedelta(days=1))
        return self._slots_for(k, day, service, busy, self.now())

    async def is_free(self, service: Service, start: datetime) -> bool:
        start = start.astimezone(self._tz)
        return start in await self.free_slots(start.date(), service)

    async def bookings_between(self, start: datetime, end: datetime) -> list[Booking]:
        return await self._schedule.list_between(start, end)

    # -- commands ---------------------------------------------------------------------------------

    async def book(self, request: BookingRequest) -> Booking:
        name = normalize_name(request.customer_name)
        phone = normalize_phone(request.phone, self._country_code)
        k = await self._knowledge.get()
        service = k.service(request.service_id)
        if service is None:
            raise UnknownService(request.service_id)

        start = request.start.astimezone(self._tz)
        end = start + service.duration
        day = start.date()
        allowed = self._slots_for(k, day, service, (), self.now()) if day in self.window_days() else []
        if start not in allowed:
            raise SlotUnavailable(start.isoformat())

        async with self._lock:
            # Re-read busy time inside the lock: this is the double-booking guard. In LIVE mode it
            # also catches events the owner added to the calendar by hand a moment ago.
            busy = await self._schedule.busy_intervals(start, end)
            if not slots.is_free(start, end, busy):
                raise SlotTaken(start.isoformat())
            booking = Booking(
                id=await self._unique_id(),
                service_id=service.id,
                service_name=service.name(DEFAULT_LANGUAGE),
                start=start,
                end=end,
                customer_name=name,
                phone=phone,
                user_id=request.user_id,
                lang=request.lang,
                created_at=self.now(),
            )
            await self._schedule.create(booking)
        return booking

    async def cancel(self, booking_id: str) -> Booking | None:
        return await self._schedule.cancel(normalize_booking_id(booking_id))

    async def _unique_id(self) -> str:
        for _ in range(10):
            candidate = new_booking_id()
            if await self._schedule.get(candidate) is None:
                return candidate
        raise RuntimeError("could not generate a unique booking id")  # pragma: no cover
