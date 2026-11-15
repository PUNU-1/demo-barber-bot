"""Retry with exponential backoff and jitter for flaky network calls."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _status_code(exc: BaseException) -> int | None:
    """Best-effort HTTP status from the exception types of google-genai, googleapiclient and gspread."""
    for candidate in (
        getattr(exc, "code", None),  # google.genai.errors.APIError
        getattr(exc, "status_code", None),
        getattr(getattr(exc, "resp", None), "status", None),  # googleapiclient HttpError
        getattr(getattr(exc, "response", None), "status_code", None),  # gspread APIError
    ):
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _network_error_types() -> tuple[type[BaseException], ...]:
    """Connection-level errors of the HTTP stacks the SDKs may use (whichever are installed).

    google-genai talks through aiohttp when it is installed (aiogram pulls it in), otherwise
    through httpx2 or httpx. None of their connection errors subclass ``ConnectionError``.
    """
    found: list[type[BaseException]] = []
    for module_name, attr in (("httpx", "TransportError"), ("httpx2", "TransportError"),
                              ("aiohttp", "ClientConnectionError")):
        try:
            module = __import__(module_name)
            found.append(getattr(module, attr))
        except (ImportError, AttributeError):
            continue
    return tuple(found)


_NETWORK_ERRORS: tuple[type[BaseException], ...] | None = None


def is_transient(exc: BaseException) -> bool:
    """True for errors that are worth retrying: timeouts, dropped connections, 429 and 5xx."""
    global _NETWORK_ERRORS
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if _NETWORK_ERRORS is None:
        _NETWORK_ERRORS = _network_error_types()
    if _NETWORK_ERRORS and isinstance(exc, _NETWORK_ERRORS):
        return True
    return _status_code(exc) in TRANSIENT_STATUS


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    op: str = "operation",
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    is_retryable: Callable[[BaseException], bool] = is_transient,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Call ``func`` until it succeeds, retrying transient errors with exponential backoff.

    Non-retryable errors and the last failure are re-raised unchanged. Exceptions that
    carry a ``retry_after`` (e.g. Telegram flood control) wait that long instead.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except Exception as exc:
            if attempt >= attempts or not is_retryable(exc):
                raise
            retry_after = getattr(exc, "retry_after", None)
            if isinstance(retry_after, (int, float)) and retry_after > 0:
                delay = min(float(retry_after), 30.0)
            else:
                delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * random.uniform(0.5, 1.0)
            log.warning(
                "%s failed (attempt %d/%d): %s: %s; retrying in %.1fs",
                op, attempt, attempts, type(exc).__name__, exc, delay,
            )
            await sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
