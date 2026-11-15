"""Turn raw rows (from faq.json or the Google Sheet) into a validated ``Knowledge`` object.

Both sources use the same layout, so the owner can move from DEMO to LIVE by
pasting the same tables into a sheet:

* ``info``: key/value pairs (shop_name, address, phone, currency, maps_url)
* ``hours``: day | open | close (empty open/close = closed)
* ``services``: id | name_en | name_ru | name_az | duration_min | price
* ``faq``: question | answer_en | answer_ru | answer_az | keywords
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import time
from decimal import Decimal, InvalidOperation
from typing import Any

from services.errors import KnowledgeError
from services.models import LANGUAGES, FaqEntry, Knowledge, Service, TimeWindow

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_INDEX = {name: i for i, name in enumerate(_DAYS)} | {name[:3]: i for i, name in enumerate(_DAYS)}

_SERVICE_ID_RE = re.compile(r"^[a-z0-9_-]{1,20}$")  # short: it travels inside Telegram callback data
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _lower_keys(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(k).strip().lower(): v for k, v in row.items()}


def _parse_time(value: Any, where: str) -> time:
    match = _TIME_RE.match(_text(value))
    if not match:
        raise KnowledgeError(f"{where}: expected a time like 10:00, got {value!r}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise KnowledgeError(f"{where}: invalid time {value!r}")
    return time(hour, minute)


def _parse_hours(rows: Iterable[Mapping[str, Any]]) -> dict[int, TimeWindow | None]:
    hours: dict[int, TimeWindow | None] = {day: None for day in range(7)}
    for number, raw in enumerate(rows, start=1):
        row = _lower_keys(raw)
        where = f"hours row {number}"
        day_name = _text(row.get("day")).lower()
        if day_name not in DAY_INDEX:
            raise KnowledgeError(f"{where}: unknown day {row.get('day')!r} (use Monday ... Sunday)")
        opens_raw, closes_raw = _text(row.get("open")), _text(row.get("close"))
        if not opens_raw and not closes_raw:
            hours[DAY_INDEX[day_name]] = None
            continue
        if not opens_raw or not closes_raw:
            raise KnowledgeError(f"{where}: fill both open and close, or leave both empty for a day off")
        opens, closes = _parse_time(opens_raw, where), _parse_time(closes_raw, where)
        if opens >= closes:
            raise KnowledgeError(f"{where}: open ({opens_raw}) must be before close ({closes_raw})")
        hours[DAY_INDEX[day_name]] = TimeWindow(opens, closes)
    return hours


def _parse_services(rows: Iterable[Mapping[str, Any]]) -> tuple[Service, ...]:
    services: list[Service] = []
    seen: set[str] = set()
    for number, raw in enumerate(rows, start=1):
        row = _lower_keys(raw)
        where = f"services row {number}"
        service_id = _text(row.get("id")).lower()
        if not _SERVICE_ID_RE.match(service_id):
            raise KnowledgeError(f"{where}: id must be 1-20 chars of a-z, 0-9, '-' or '_' (got {service_id!r})")
        if service_id in seen:
            raise KnowledgeError(f"{where}: duplicate id {service_id!r}")
        seen.add(service_id)
        names = {lang: _text(row.get(f"name_{lang}")) for lang in LANGUAGES if _text(row.get(f"name_{lang}"))}
        if not names:
            raise KnowledgeError(f"{where}: at least one of name_en / name_ru / name_az is required")
        try:
            duration = int(float(_text(row.get("duration_min"))))
        except ValueError:
            raise KnowledgeError(f"{where}: duration_min must be a number of minutes") from None
        if not 5 <= duration <= 8 * 60:
            raise KnowledgeError(f"{where}: duration_min must be between 5 and 480")
        try:
            price = Decimal(_text(row.get("price")).replace(",", "."))
        except InvalidOperation:
            raise KnowledgeError(f"{where}: price must be a number") from None
        if price < 0:
            raise KnowledgeError(f"{where}: price can't be negative")
        services.append(Service(id=service_id, names=names, duration_min=duration, price=price))
    return tuple(services)


def _parse_faq(rows: Iterable[Mapping[str, Any]]) -> tuple[FaqEntry, ...]:
    entries: list[FaqEntry] = []
    for number, raw in enumerate(rows, start=1):
        row = _lower_keys(raw)
        question = _text(row.get("question"))
        answers = {lang: _text(row.get(f"answer_{lang}")) for lang in LANGUAGES if _text(row.get(f"answer_{lang}"))}
        if not question and not answers:
            continue  # blank row in the sheet
        if not question or not answers:
            raise KnowledgeError(f"faq row {number}: needs a question and at least one answer_* column")
        keywords = row.get("keywords") or ""
        if isinstance(keywords, str):
            keywords = keywords.split(",")
        entries.append(
            FaqEntry(question=question, answers=answers, keywords=tuple(k.strip() for k in keywords if k.strip()))
        )
    return tuple(entries)


def parse_knowledge(raw: Mapping[str, Any]) -> Knowledge:
    info = {str(k).strip().lower(): _text(v) for k, v in (raw.get("info") or {}).items()}
    for required in ("shop_name", "address", "phone"):
        if not info.get(required):
            raise KnowledgeError(f"info: '{required}' is required")
    services = _parse_services(raw.get("services") or [])
    if not services:
        raise KnowledgeError("services: add at least one service")
    return Knowledge(
        shop_name=info["shop_name"],
        address=info["address"],
        phone=info["phone"],
        currency=info.get("currency") or "AZN",
        hours=_parse_hours(raw.get("hours") or []),
        services=services,
        faq=_parse_faq(raw.get("faq") or []),
        maps_url=info.get("maps_url", ""),
    )
