"""Domain models shared by every service. Pure data, no I/O."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any

LANGUAGES: tuple[str, ...] = ("az", "ru", "en")
DEFAULT_LANGUAGE = "en"


def _pick(texts: Mapping[str, str], lang: str, default: str) -> str:
    return texts.get(lang) or texts.get(DEFAULT_LANGUAGE) or next(iter(texts.values()), default)


@dataclass(frozen=True)
class Service:
    id: str
    names: Mapping[str, str]
    duration_min: int
    price: Decimal

    @property
    def duration(self) -> timedelta:
        return timedelta(minutes=self.duration_min)

    def name(self, lang: str) -> str:
        return _pick(self.names, lang, self.id)


@dataclass(frozen=True)
class TimeWindow:
    opens: time
    closes: time


@dataclass(frozen=True)
class FaqEntry:
    question: str
    answers: Mapping[str, str]
    keywords: tuple[str, ...] = ()

    def answer(self, lang: str) -> str:
        return _pick(self.answers, lang, "")


@dataclass(frozen=True)
class Knowledge:
    """Everything the bot is allowed to say about the shop (from faq.json or the Google Sheet)."""

    shop_name: str
    address: str
    phone: str
    currency: str
    hours: Mapping[int, TimeWindow | None]  # 0 = Monday ... 6 = Sunday; None = closed
    services: tuple[Service, ...]
    faq: tuple[FaqEntry, ...] = ()
    maps_url: str = ""

    def service(self, service_id: str | None) -> Service | None:
        return next((s for s in self.services if s.id == service_id), None)

    def window(self, weekday: int) -> TimeWindow | None:
        return self.hours.get(weekday)


ACTIVE = "active"
CANCELLED = "cancelled"


@dataclass(frozen=True)
class Booking:
    id: str
    service_id: str
    service_name: str
    start: datetime
    end: datetime
    customer_name: str
    phone: str
    user_id: int | None = None
    lang: str = DEFAULT_LANGUAGE
    status: str = ACTIVE
    created_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status == ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "service_id": self.service_id,
            "service_name": self.service_name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "customer_name": self.customer_name,
            "phone": self.phone,
            "user_id": self.user_id,
            "lang": self.lang,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Booking:
        created = data.get("created_at")
        return cls(
            id=str(data["id"]),
            service_id=str(data["service_id"]),
            service_name=str(data.get("service_name") or data["service_id"]),
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
            customer_name=str(data["customer_name"]),
            phone=str(data["phone"]),
            user_id=int(data["user_id"]) if data.get("user_id") is not None else None,
            lang=str(data.get("lang") or DEFAULT_LANGUAGE),
            status=str(data.get("status") or ACTIVE),
            created_at=datetime.fromisoformat(created) if created else None,
        )
