"""TTL cache around a slow knowledge source, serving the last good copy if the source fails."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from services.errors import KnowledgeUnavailable
from services.models import Knowledge

if TYPE_CHECKING:
    from services.faq import KnowledgeSource

log = logging.getLogger(__name__)


class CachedKnowledge:
    def __init__(
        self,
        source: KnowledgeSource,
        ttl_seconds: float,
        *,
        retry_after_failure: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._ttl = ttl_seconds
        self._retry_after_failure = retry_after_failure
        self._clock = clock
        self._value: Knowledge | None = None
        self._fresh_until = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> Knowledge:
        if self._value is not None and self._clock() < self._fresh_until:
            return self._value
        async with self._lock:
            now = self._clock()
            if self._value is not None and now < self._fresh_until:
                return self._value  # another task refreshed it while we waited
            try:
                value = await self._source.get()
            except Exception as exc:
                if self._value is None:
                    if isinstance(exc, KnowledgeUnavailable):
                        raise
                    raise KnowledgeUnavailable(f"could not load shop data: {exc}") from exc
                log.warning("Could not refresh shop data (%s); serving the cached copy", exc)
                self._fresh_until = now + self._retry_after_failure
                return self._value
            self._value = value
            self._fresh_until = now + self._ttl
            return value
