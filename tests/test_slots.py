"""Slot arithmetic: opening hours, durations, overlaps and lead time."""

from datetime import date, datetime, time, timedelta

import pytest

from services.models import TimeWindow
from services.slots import booking_days, candidate_starts, free_slots, overlaps
from tests.conftest import TZ

DAY = date(2026, 11, 17)  # Tuesday
WINDOW = TimeWindow(time(10), time(20))
STEP = timedelta(minutes=30)
LEAD = timedelta(minutes=60)
HALF_HOUR = timedelta(minutes=30)
HOUR = timedelta(minutes=60)
DAY_BEFORE = datetime(2026, 11, 16, 8, 0, tzinfo=TZ)  # "now" far enough back that lead time doesn't matter


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


def slots_for(duration=HALF_HOUR, busy=(), now=DAY_BEFORE, window=WINDOW):
    return free_slots(DAY, window, duration, list(busy), now=now, tz=TZ, step=STEP, min_lead=LEAD)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ((at(10), at(11)), (at(10, 30), at(11, 30)), True),  # partial overlap
        ((at(10), at(11)), (at(10, 15), at(10, 45)), True),  # contained
        ((at(10), at(10, 30)), (at(10, 30), at(11)), False),  # touching ends don't overlap
        ((at(10), at(10, 30)), (at(12), at(13)), False),  # far apart
    ],
)
def test_overlaps_uses_half_open_intervals(a, b, expected):
    assert overlaps(*a, *b) is expected
    assert overlaps(*b, *a) is expected


def test_closed_day_has_no_slots():
    assert slots_for(window=None) == []


def test_full_open_day_has_every_half_hour():
    slots = slots_for()
    assert slots[0] == at(10)
    assert slots[-1] == at(19, 30)
    assert len(slots) == 20


def test_long_service_must_finish_before_closing():
    slots = slots_for(duration=HOUR)
    assert slots[-1] == at(19)
    assert at(19, 30) not in slots


def test_existing_booking_blocks_its_slot_but_not_neighbours():
    slots = slots_for(busy=[(at(12), at(12, 30))])
    assert at(12) not in slots
    assert at(11, 30) in slots
    assert at(12, 30) in slots


def test_partial_overlap_blocks_both_affected_slots():
    slots = slots_for(busy=[(at(12, 15), at(12, 45))])  # e.g. something the owner added by hand
    assert at(12) not in slots
    assert at(12, 30) not in slots
    assert at(13) in slots


def test_long_service_is_blocked_by_a_later_booking():
    slots = slots_for(duration=HOUR, busy=[(at(13), at(13, 30))])
    assert at(12, 30) not in slots  # 12:30-13:30 would run into the 13:00 booking
    assert at(12) in slots
    assert at(13, 30) in slots


def test_past_times_and_lead_time_are_excluded():
    now = at(13, 10)
    slots = slots_for(now=now)
    assert slots[0] == at(14, 30)  # 13:10 + 60 min lead = 14:10, next grid slot is 14:30
    assert all(s >= now + LEAD for s in slots)


def test_grid_starts_at_opening_time():
    window = TimeWindow(time(10, 15), time(12))
    starts = candidate_starts(DAY, window, HALF_HOUR, tz=TZ, step=STEP)
    assert starts == [at(10, 15), at(10, 45), at(11, 15)]


def test_booking_window_includes_today():
    days = booking_days(date(2026, 11, 16), 3)
    assert days == [date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)]
