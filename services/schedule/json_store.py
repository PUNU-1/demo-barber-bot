"""Bookings in a local JSON file (DEMO mode and tests). Single process only."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from services.errors import ScheduleUnavailable
from services.models import CANCELLED, Booking
from services.slots import Interval, overlaps


class JsonSchedule:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> list[Booking]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8-sig") or "[]")
            return [Booking.from_dict(item) for item in raw]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Refuse to continue rather than silently overwrite a file we couldn't parse.
            raise ScheduleUnavailable(f"cannot read {self._path.name}: {exc}") from exc

    def _write(self, bookings: list[Booking]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            payload = json.dumps([b.to_dict() for b in bookings], ensure_ascii=False, indent=2)
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self._path)  # atomic: readers never see a half-written file
        except OSError as exc:
            raise ScheduleUnavailable(f"cannot write {self._path.name}: {exc}") from exc

    async def busy_intervals(self, start: datetime, end: datetime) -> list[Interval]:
        return [
            (b.start, b.end)
            for b in self._read()
            if b.is_active and overlaps(b.start, b.end, start, end)
        ]

    async def create(self, booking: Booking) -> None:
        async with self._lock:
            bookings = self._read()
            bookings.append(booking)
            self._write(bookings)

    async def get(self, booking_id: str) -> Booking | None:
        return next((b for b in self._read() if b.id == booking_id and b.is_active), None)

    async def cancel(self, booking_id: str) -> Booking | None:
        async with self._lock:
            bookings = self._read()
            for index, booking in enumerate(bookings):
                if booking.id == booking_id and booking.is_active:
                    cancelled = replace(booking, status=CANCELLED)
                    bookings[index] = cancelled
                    self._write(bookings)
                    return cancelled
        return None

    async def list_between(self, start: datetime, end: datetime) -> list[Booking]:
        found = [b for b in self._read() if b.is_active and start <= b.start < end]
        return sorted(found, key=lambda b: b.start)
