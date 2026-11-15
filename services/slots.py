"""Pure slot arithmetic.

No I/O and no clock: "now", busy intervals and opening hours are passed in,
which keeps every rule here easy to unit-test.

Intervals are half-open ``[start, end)``: a 10:00-10:30 booking and a
10:30-11:00 booking touch but do not overlap.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, tzinfo

from services.models import TimeWindow

Interval = tuple[datetime, datetime]


def overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def is_free(start: datetime, end: datetime, busy: Iterable[Interval]) -> bool:
    return not any(overlaps(start, end, b_start, b_end) for b_start, b_end in busy)


def candidate_starts(
    day: date,
    window: TimeWindow | None,
    duration: timedelta,
    *,
    tz: tzinfo,
    step: timedelta,
) -> list[datetime]:
    """Grid-aligned start times on ``day`` where the whole service fits inside opening hours."""
    if window is None:
        return []
    opens = datetime.combine(day, window.opens, tzinfo=tz)
    closes = datetime.combine(day, window.closes, tzinfo=tz)
    starts: list[datetime] = []
    current = opens
    while current + duration <= closes:
        starts.append(current)
        current += step
    return starts


def free_slots(
    day: date,
    window: TimeWindow | None,
    duration: timedelta,
    busy: Iterable[Interval],
    *,
    now: datetime,
    tz: tzinfo,
    step: timedelta,
    min_lead: timedelta,
) -> list[datetime]:
    """Start times a customer can book: inside opening hours, far enough in the future, not overlapping."""
    busy = list(busy)
    earliest = now + min_lead
    return [
        start
        for start in candidate_starts(day, window, duration, tz=tz, step=step)
        if start >= earliest and is_free(start, start + duration, busy)
    ]


def booking_days(today: date, days_ahead: int) -> list[date]:
    """The booking window: today plus the following ``days_ahead - 1`` days."""
    return [today + timedelta(days=offset) for offset in range(days_ahead)]
