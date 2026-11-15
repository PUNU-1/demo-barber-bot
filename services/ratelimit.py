"""Per-user sliding-window rate limiter (in memory)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Hashable
from enum import Enum


class Decision(Enum):
    ALLOW = "allow"
    BLOCK_NOTIFY = "block_notify"  # first blocked message in a burst: tell the user once
    BLOCK_SILENT = "block_silent"  # keep ignoring without replying, so spam gets no answers


class RateLimiter:
    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_events
        self._window = window_seconds
        self._clock = clock
        self._events: dict[Hashable, deque[float]] = {}
        self._warned: set[Hashable] = set()

    def hit(self, key: Hashable) -> Decision:
        now = self._clock()
        events = self._events.setdefault(key, deque())
        while events and events[0] <= now - self._window:
            events.popleft()
        if len(events) >= self._max:
            if key in self._warned:
                return Decision.BLOCK_SILENT
            self._warned.add(key)
            return Decision.BLOCK_NOTIFY
        events.append(now)
        self._warned.discard(key)
        if len(self._events) > 10_000:
            self._purge(now)
        return Decision.ALLOW

    def _purge(self, now: float) -> None:
        stale = [k for k, q in self._events.items() if not q or q[-1] <= now - self._window]
        for key in stale:
            self._events.pop(key, None)
            self._warned.discard(key)
