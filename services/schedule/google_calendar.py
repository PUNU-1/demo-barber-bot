"""Bookings as Google Calendar events (LIVE mode).

* Free/busy comes from the Calendar ``freebusy`` API, so anything the owner adds
  by hand (lunch, day off) also blocks slots.
* Each event created by the bot carries private extended properties
  (``source``, ``booking_id``, customer details), which is how ``/cancel <id>``
  and ``/today`` find the bot's bookings.
* googleapiclient is synchronous and not thread-safe, so calls run in a worker
  thread behind a lock and go through ``retry_async``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from services.errors import ScheduleUnavailable
from services.models import CANCELLED, DEFAULT_LANGUAGE, Booking
from services.retry import retry_async
from services.slots import Interval

log = logging.getLogger(__name__)

T = TypeVar("T")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
SOURCE_TAG = "demo-barber-bot"


class GoogleCalendarSchedule:
    def __init__(
        self,
        service_account_file: Path | None,
        calendar_id: str,
        tz: ZoneInfo,
        *,
        api: Any = None,  # a prebuilt googleapiclient resource (tests pass one backed by a fake HTTP)
    ) -> None:
        self._file = service_account_file
        self._calendar_id = calendar_id
        self._tz = tz
        self._api: Any = api
        self._lock = asyncio.Lock()

    # -- plumbing ---------------------------------------------------------------------------------

    def _client(self) -> Any:
        if self._api is None:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            credentials = service_account.Credentials.from_service_account_file(str(self._file), scopes=SCOPES)
            self._api = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return self._api

    async def _call(self, op: str, fn: Callable[[], T]) -> T:
        async def attempt() -> T:
            async with self._lock:
                return await asyncio.to_thread(fn)

        try:
            return await retry_async(attempt, op=f"calendar.{op}")
        except Exception as exc:
            raise ScheduleUnavailable(f"Google Calendar {op} failed: {exc}") from exc

    def _parse_dt(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(self._tz)

    def _to_booking(self, event: dict[str, Any]) -> Booking:
        props = event.get("extendedProperties", {}).get("private", {})
        user_id = props.get("user_id")
        return Booking(
            id=props["booking_id"],
            service_id=props.get("service_id", ""),
            service_name=props.get("service_name") or event.get("summary", ""),
            start=self._parse_dt(event["start"]["dateTime"]),
            end=self._parse_dt(event["end"]["dateTime"]),
            customer_name=props.get("customer_name", ""),
            phone=props.get("phone", ""),
            user_id=int(user_id) if user_id else None,
            lang=props.get("lang") or DEFAULT_LANGUAGE,
            created_at=self._parse_dt(event["created"]) if event.get("created") else None,
        )

    async def _find_event(self, booking_id: str) -> dict[str, Any] | None:
        def run() -> dict[str, Any]:
            return (
                self._client()
                .events()
                .list(
                    calendarId=self._calendar_id,
                    privateExtendedProperty=f"booking_id={booking_id}",
                    singleEvents=True,
                    maxResults=5,
                )
                .execute()
            )

        items = (await self._call("find", run)).get("items", [])
        return next((e for e in items if e.get("status") != "cancelled"), None)

    # -- ScheduleBackend --------------------------------------------------------------------------

    async def busy_intervals(self, start: datetime, end: datetime) -> list[Interval]:
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "timeZone": str(self._tz),
            "items": [{"id": self._calendar_id}],
        }
        response = await self._call("freebusy", lambda: self._client().freebusy().query(body=body).execute())
        calendar = response.get("calendars", {}).get(self._calendar_id, {})
        if calendar.get("errors"):
            # Typically "notFound": the calendar isn't shared with the service account.
            raise ScheduleUnavailable(f"calendar access error: {calendar['errors']}")
        return [(self._parse_dt(b["start"]), self._parse_dt(b["end"])) for b in calendar.get("busy", [])]

    async def create(self, booking: Booking) -> None:
        body = {
            "summary": f"{booking.service_name}: {booking.customer_name}",
            "description": (
                f"Booking ID: {booking.id}\nCustomer: {booking.customer_name}\nPhone: {booking.phone}\n"
                "Created by the Demo Barber Telegram bot."
            ),
            "start": {"dateTime": booking.start.isoformat(), "timeZone": str(self._tz)},
            "end": {"dateTime": booking.end.isoformat(), "timeZone": str(self._tz)},
            "extendedProperties": {
                "private": {
                    "source": SOURCE_TAG,
                    "booking_id": booking.id,
                    "service_id": booking.service_id,
                    "service_name": booking.service_name,
                    "customer_name": booking.customer_name,
                    "phone": booking.phone,
                    "user_id": str(booking.user_id or ""),
                    "lang": booking.lang,
                }
            },
        }
        await self._call(
            "insert", lambda: self._client().events().insert(calendarId=self._calendar_id, body=body).execute()
        )

    async def get(self, booking_id: str) -> Booking | None:
        event = await self._find_event(booking_id)
        return self._to_booking(event) if event else None

    async def cancel(self, booking_id: str) -> Booking | None:
        event = await self._find_event(booking_id)
        if event is None:
            return None
        booking = self._to_booking(event)
        await self._call(
            "delete",
            lambda: self._client().events().delete(calendarId=self._calendar_id, eventId=event["id"]).execute(),
        )
        return replace(booking, status=CANCELLED)

    async def list_between(self, start: datetime, end: datetime) -> list[Booking]:
        def run() -> dict[str, Any]:
            return (
                self._client()
                .events()
                .list(
                    calendarId=self._calendar_id,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    privateExtendedProperty=f"source={SOURCE_TAG}",
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                )
                .execute()
            )

        items = (await self._call("list", run)).get("items", [])
        bookings = [self._to_booking(e) for e in items if e.get("status") != "cancelled"]
        # timeMin/timeMax match by overlap; keep only bookings that *start* in the range.
        return [b for b in bookings if start <= b.start < end]
