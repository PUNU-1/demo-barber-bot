"""Booking storage. DEMO: ``JsonSchedule`` (bookings.json). LIVE: ``GoogleCalendarSchedule``."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from services.models import Booking
from services.schedule.json_store import JsonSchedule
from services.slots import Interval


class ScheduleBackend(Protocol):
    async def busy_intervals(self, start: datetime, end: datetime) -> list[Interval]:
        """Busy time that overlaps ``[start, end)``: bookings plus anything else blocking the chair."""

    async def create(self, booking: Booking) -> None: ...

    async def get(self, booking_id: str) -> Booking | None:
        """The booking with this id if it is still active."""

    async def cancel(self, booking_id: str) -> Booking | None:
        """Cancel an active booking. Returns it, or None if there was nothing active to cancel."""

    async def list_between(self, start: datetime, end: datetime) -> list[Booking]:
        """Active bookings starting in ``[start, end)``, ordered by start time."""


__all__ = ["JsonSchedule", "ScheduleBackend"]
