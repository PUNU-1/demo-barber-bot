"""Transport-agnostic conversation engine.

Adapters (Telegram, terminal) turn their events into an ``Incoming``, call
``Engine.handle()`` and render the returned ``Outcome``: replies for this user,
notices for the owner and messages for other customers. Nothing here imports
aiogram, which is what lets the zero-key terminal mode run the exact same
flow, and lets tests drive a full conversation without Telegram.

Booking buttons carry everything they need (``time:haircut:202611181430``), so
a button keeps working even after the bot restarts and in-memory sessions are lost.
"""

from __future__ import annotations

import logging
import time as _time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from html import escape

from services import i18n
from services.ai import Assistant
from services.booking import (
    BookingError,
    BookingRequest,
    BookingService,
    InvalidName,
    InvalidPhone,
    SlotTaken,
    normalize_booking_id,
    normalize_name,
    normalize_phone,
)
from services.errors import ServiceUnavailable
from services.faq import KnowledgeSource
from services.intents import Topic, classify, is_cancel
from services.language import detect_language
from services.models import DEFAULT_LANGUAGE, LANGUAGES, Booking, Knowledge, Service
from services.ratelimit import Decision, RateLimiter

log = logging.getLogger(__name__)
t = i18n.t


# -- messages in and out --------------------------------------------------------------------------


@dataclass(frozen=True)
class Button:
    text: str
    data: str  # callback payload, at most 64 bytes (Telegram limit)


@dataclass
class Reply:
    text: str  # Telegram HTML
    buttons: list[list[Button]] = field(default_factory=list)  # inline keyboard rows
    contact_request: tuple[str, str] | None = None  # (share label, cancel label): Telegram reply keyboard
    remove_keyboard: bool = False  # hide a previously shown reply keyboard


@dataclass(frozen=True)
class Incoming:
    user_id: int
    text: str | None = None
    callback: str | None = None
    contact_phone: str | None = None
    language_code: str | None = None  # from the Telegram client, used until the user writes something
    display_name: str = ""
    username: str | None = None


@dataclass
class Outcome:
    replies: list[Reply] = field(default_factory=list)
    owner_notices: list[str] = field(default_factory=list)
    user_messages: list[tuple[int, Reply]] = field(default_factory=list)

    def say(self, text: str, buttons: list[list[Button]] | None = None, **options) -> Reply:
        reply = Reply(text, buttons or [], **options)
        self.replies.append(reply)
        return reply


# -- per-user state -------------------------------------------------------------------------------


class Step(Enum):
    IDLE = "idle"
    SERVICE = "service"
    DATE = "date"
    TIME = "time"
    NAME = "name"
    PHONE = "phone"
    CONFIRM = "confirm"


BUTTON_STEPS = (Step.SERVICE, Step.DATE, Step.TIME)


@dataclass
class Session:
    lang: str = DEFAULT_LANGUAGE
    step: Step = Step.IDLE
    service_id: str | None = None
    day: date | None = None
    start: datetime | None = None
    name: str | None = None
    phone: str | None = None
    last_question: str | None = None
    contact_keyboard: bool = False  # the "share phone" reply keyboard is currently shown
    touched: float = 0.0

    def reset_flow(self) -> None:
        self.step = Step.IDLE
        self.service_id = self.day = self.start = self.name = self.phone = None


class SessionStore:
    """In-memory sessions. A booking left idle for ``ttl`` seconds starts over."""

    def __init__(self, ttl_seconds: float = 30 * 60, clock: Callable[[], float] = _time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._sessions: dict[int, Session] = {}

    def get(self, user_id: int, language_code: str | None) -> Session:
        now = self._clock()
        session = self._sessions.get(user_id)
        if session is None:
            code = (language_code or "").split("-")[0].lower()
            session = Session(lang=code if code in LANGUAGES else DEFAULT_LANGUAGE)
            self._sessions[user_id] = session
            if len(self._sessions) > 5_000:
                self._purge(now)
        elif now - session.touched > self._ttl:
            session.reset_flow()
        session.touched = now
        return session

    def _purge(self, now: float) -> None:
        for uid in [u for u, s in self._sessions.items() if now - s.touched > self._ttl]:
            del self._sessions[uid]


def _clean(text: str) -> str:
    """Strip control characters (keeps newlines) and surrounding whitespace."""
    return "".join(ch for ch in text if ch == "\n" or unicodedata.category(ch)[0] != "C").strip()


def _chunk(buttons: list[Button], size: int) -> list[list[Button]]:
    return [buttons[i : i + size] for i in range(0, len(buttons), size)]


# -- the engine -----------------------------------------------------------------------------------


class Engine:
    def __init__(
        self,
        *,
        knowledge: KnowledgeSource,
        booking: BookingService,
        assistant: Assistant,
        owner_id: int | None,
        rate_limiter: RateLimiter,
        max_input_chars: int = 500,
        default_country_code: str = "994",
        sessions: SessionStore | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._booking = booking
        self._assistant = assistant
        self._owner_id = owner_id
        self._limiter = rate_limiter
        self._max_chars = max_input_chars
        self._country_code = default_country_code
        self._sessions = sessions or SessionStore()

    @property
    def owner_id(self) -> int | None:
        return self._owner_id

    def is_owner(self, user_id: int) -> bool:
        return self._owner_id is not None and user_id == self._owner_id

    async def warm_up(self) -> Knowledge:
        """Load the shop data once at startup so configuration problems surface immediately."""
        return await self._knowledge.get()

    async def handle(self, msg: Incoming) -> Outcome:
        session = self._sessions.get(msg.user_id, msg.language_code)
        out = Outcome()
        if not self.is_owner(msg.user_id):
            decision = self._limiter.hit(msg.user_id)
            if decision is Decision.BLOCK_SILENT:
                return out
            if decision is Decision.BLOCK_NOTIFY:
                out.say(t("rate_limited", session.lang))
                return out
        try:
            if msg.callback is not None:
                await self._on_callback(msg, session, out)
            elif msg.contact_phone:
                await self._on_contact(msg, session, out)
            elif msg.text is not None:
                await self._on_text(msg, session, out)
            else:
                out.say(t("text_only", session.lang))
        except ServiceUnavailable as exc:
            log.error("Dependency unavailable while handling user %s: %s", msg.user_id, exc)
            out = Outcome([Reply(t("error_generic", session.lang))])
        except Exception:
            log.exception("Unexpected error while handling user %s", msg.user_id)
            out = Outcome([Reply(t("error_generic", session.lang))])
        self._sync_keyboard(session, out)
        return out

    # -- routing ----------------------------------------------------------------------------------

    async def _on_text(self, msg: Incoming, session: Session, out: Outcome) -> None:
        text = _clean(msg.text or "")
        if not text:
            return
        if len(text) > self._max_chars:
            lang = detect_language(text[:300], session.lang)
            out.say(t("too_long", lang, limit=self._max_chars))
            return
        if text.startswith("/"):
            await self._on_command(text, msg, session, out)
            return
        if session.step in (Step.NAME, Step.PHONE, Step.CONFIRM) and is_cancel(text):
            await self._cancel_flow(session, out)
            return
        if session.step is Step.NAME:  # don't re-detect language on a name like "Ali"
            await self._on_name(text, session, out)
            return
        if session.step is Step.PHONE:
            await self._accept_phone(text, session, out)
            return
        session.lang = detect_language(text, fallback=session.lang)
        await self._on_free_text(text, msg, session, out)

    async def _on_callback(self, msg: Incoming, session: Session, out: Outcome) -> None:
        data = (msg.callback or "")[:64]
        kind, _, arg = data.partition(":")
        if kind == "act":
            if arg == "book":
                await self._ask_service(session, out)
                return
            if arg == "menu":
                session.reset_flow()
                await self._menu(session, out)
                return
            if arg == "cancel":
                await self._cancel_flow(session, out)
                return
            if arg == "human":
                await self._handoff(msg, session, out)
                return
            if arg in ("prices", "hours", "address"):
                k = await self._knowledge.get()
                render = {"prices": i18n.render_prices, "hours": i18n.render_hours, "address": i18n.render_address}
                out.say(render[arg](k, session.lang), self._book_menu_row(session.lang))
                return
        elif kind == "svc":
            await self._ask_date(session, out, arg)
            return
        elif kind == "day":
            service_id, _, raw_day = arg.partition(":")
            day = self._parse_day(raw_day)
            if day is not None:
                await self._ask_time(session, out, service_id, day)
                return
        elif kind == "time":
            service_id, _, raw_start = arg.partition(":")
            start = self._parse_start(raw_start)
            if start is not None:
                await self._on_slot(session, out, service_id, start)
                return
        elif kind == "confirm":
            await self._confirm(msg, session, out)
            return
        log.info("Ignoring unknown callback %r", data)
        await self._menu(session, out)

    async def _on_command(self, text: str, msg: Incoming, session: Session, out: Outcome) -> None:
        command, _, arg = text.partition(" ")
        command = command.split("@", 1)[0].lower()  # "/start@DemoBarberBot" in group-style links
        arg = arg.strip()
        lang = session.lang
        owner = self.is_owner(msg.user_id)

        if command in ("/start", "/menu"):
            session.reset_flow()
            await self._menu(session, out, welcome=True)
        elif command == "/help":
            out.say(t("help", lang), self._main_menu(lang))
        elif command == "/book":
            await self._ask_service(session, out)
        elif command == "/whoami":
            out.say(t("whoami", lang, id=msg.user_id))
        elif command == "/cancel" and owner and arg:
            await self._admin_cancel(arg, out)
        elif command == "/cancel" and owner and session.step is Step.IDLE:
            out.say("Usage: <code>/cancel &lt;booking id&gt;</code>, e.g. <code>/cancel AB12CD</code>")
        elif command == "/cancel":
            await self._cancel_flow(session, out)
        elif command == "/today" and owner:
            await self._admin_today(out)
        elif command == "/bookings" and owner:
            await self._admin_upcoming(out)
        else:
            # Non-owners get the same answer for admin commands as for any unknown command.
            out.say(t("unknown_command", lang))

    # -- menu, FAQ, handoff -----------------------------------------------------------------------

    def _main_menu(self, lang: str) -> list[list[Button]]:
        return [
            [Button(t("btn_book", lang), "act:book")],
            [Button(t("btn_prices", lang), "act:prices"), Button(t("btn_hours", lang), "act:hours")],
            [Button(t("btn_address", lang), "act:address"), Button(t("btn_human", lang), "act:human")],
        ]

    def _book_menu_row(self, lang: str) -> list[list[Button]]:
        return [[Button(t("btn_book", lang), "act:book"), Button(t("btn_menu", lang), "act:menu")]]

    async def _menu(self, session: Session, out: Outcome, *, welcome: bool = False) -> None:
        if welcome:
            k = await self._knowledge.get()
            text = t("welcome", session.lang, shop=escape(k.shop_name))
        else:
            text = t("menu_prompt", session.lang)
        out.say(text, self._main_menu(session.lang))

    async def _on_free_text(self, text: str, msg: Incoming, session: Session, out: Outcome) -> None:
        lang = session.lang
        k = await self._knowledge.get()
        topic = classify(text, k).topic
        if topic is Topic.BOOKING:
            await self._ask_service(session, out)
            return
        if topic is Topic.HUMAN:
            session.last_question = session.last_question or text
            await self._handoff(msg, session, out)
            return
        if topic is Topic.PROBE:
            out.say(t("refuse", lang, shop=escape(k.shop_name)), self._book_menu_row(lang))
            return

        reply = await self._assistant.reply(text, lang, k)
        if reply.intent == "booking":
            await self._ask_service(session, out)
            return
        if reply.intent == "human":
            session.last_question = text
            await self._handoff(msg, session, out)
            return

        session.last_question = text
        answer = reply.answer or t("not_found", lang)
        in_flow = session.step in BUTTON_STEPS
        if not reply.found:
            out.say(answer, [[Button(t("btn_human", lang), "act:human")]] + ([] if in_flow else self._book_menu_row(lang)))
        else:
            out.say(answer, [] if in_flow else self._book_menu_row(lang))
        if in_flow:  # answered a side question mid-booking: show the current step again
            await self._render_step(session, out)

    async def _handoff(self, msg: Incoming, session: Session, out: Outcome) -> None:
        lang = session.lang
        if self._owner_id is None:
            k = await self._knowledge.get()
            out.say(t("handoff_unavailable", lang, phone=escape(k.phone)), self._book_menu_row(lang))
            return
        question = session.last_question or "(no message yet)"
        out.owner_notices.append(
            "🙋 <b>A customer asked for a human</b>\n"
            f"👤 {self._customer_link(msg)}\n"
            f"🌐 Language: {lang}\n"
            f"💬 Last message: {escape(question[:300])}"
        )
        out.say(t("handoff_done", lang), [[Button(t("btn_menu", lang), "act:menu")]])

    @staticmethod
    def _customer_link(msg: Incoming) -> str:
        name = escape(msg.display_name or "Customer")
        link = f'<a href="tg://user?id={msg.user_id}">{name}</a>'
        return f"@{escape(msg.username)} ({link})" if msg.username else link

    # -- booking flow -----------------------------------------------------------------------------

    async def _render_step(self, session: Session, out: Outcome) -> None:
        if session.step is Step.SERVICE:
            await self._ask_service(session, out)
        elif session.step is Step.DATE and session.service_id:
            await self._ask_date(session, out, session.service_id)
        elif session.step is Step.TIME and session.service_id and session.day:
            await self._ask_time(session, out, session.service_id, session.day)

    async def _ask_service(self, session: Session, out: Outcome) -> None:
        lang = session.lang
        k = await self._knowledge.get()
        session.reset_flow()
        session.step = Step.SERVICE
        rows = [
            [Button(f"{s.name(lang)} · {i18n.fmt_price(s.price, k.currency)}", f"svc:{s.id}")]
            for s in k.services
        ]
        rows.append([Button(t("btn_cancel", lang), "act:menu")])
        out.say(t("choose_service", lang), rows)

    async def _service(self, service_id: str | None) -> Service | None:
        return (await self._knowledge.get()).service(service_id)

    async def _ask_date(self, session: Session, out: Outcome, service_id: str) -> None:
        lang = session.lang
        service = await self._service(service_id)
        if service is None:  # removed from the sheet, or a mangled button
            await self._ask_service(session, out)
            return
        days = await self._booking.available_days(service)
        if not days:
            session.reset_flow()
            k = await self._knowledge.get()
            out.say(
                t("no_days", lang, days=i18n.fmt_days(self._booking.days_ahead, lang), phone=escape(k.phone)),
                [[Button(t("btn_human", lang), "act:human")], [Button(t("btn_menu", lang), "act:menu")]],
            )
            return
        session.reset_flow()
        session.step, session.service_id = Step.DATE, service.id
        today = self._booking.today()
        buttons = [Button(i18n.fmt_day_button(d, today, lang), f"day:{service.id}:{d:%Y%m%d}") for d in days]
        rows = _chunk(buttons, 3)
        rows.append([Button(t("btn_back", lang), "act:book"), Button(t("btn_cancel", lang), "act:menu")])
        out.say(t("choose_date", lang, service=escape(service.name(lang))), rows)

    async def _ask_time(self, session: Session, out: Outcome, service_id: str, day: date) -> None:
        lang = session.lang
        service = await self._service(service_id)
        if service is None:
            await self._ask_service(session, out)
            return
        free = await self._booking.free_slots(day, service)
        if not free:
            out.say(t("no_slots_day", lang))
            await self._ask_date(session, out, service.id)
            return
        session.reset_flow()
        session.step, session.service_id, session.day = Step.TIME, service.id, day
        buttons = [Button(i18n.fmt_time(s), f"time:{service.id}:{s:%Y%m%d%H%M}") for s in free]
        rows = _chunk(buttons, 4)
        rows.append([Button(t("btn_back", lang), f"svc:{service.id}"), Button(t("btn_cancel", lang), "act:menu")])
        out.say(t("choose_time", lang, service=escape(service.name(lang)), date=i18n.fmt_date(day, lang)), rows)

    async def _on_slot(self, session: Session, out: Outcome, service_id: str, start: datetime) -> None:
        lang = session.lang
        service = await self._service(service_id)
        if service is None:
            await self._ask_service(session, out)
            return
        if not await self._booking.is_free(service, start):
            out.say(t("slot_taken", lang))
            await self._ask_time(session, out, service.id, start.date())
            return
        session.reset_flow()
        session.step, session.service_id, session.day, session.start = Step.NAME, service.id, start.date(), start
        out.say(
            t("ask_name", lang, date=i18n.fmt_date(start.date(), lang), time=i18n.fmt_time(start)),
            [[Button(t("btn_cancel", lang), "act:cancel")]],
        )

    async def _on_name(self, text: str, session: Session, out: Outcome) -> None:
        lang = session.lang
        try:
            session.name = normalize_name(text)
        except InvalidName:
            out.say(t("invalid_name", lang), [[Button(t("btn_cancel", lang), "act:cancel")]])
            return
        session.step = Step.PHONE
        session.contact_keyboard = True
        out.say(
            t("ask_phone", lang, name=escape(session.name)),
            contact_request=(t("btn_share_contact", lang), t("btn_cancel", lang)),
        )

    async def _on_contact(self, msg: Incoming, session: Session, out: Outcome) -> None:
        if session.step is not Step.PHONE:
            await self._menu(session, out)
            return
        phone = (msg.contact_phone or "").strip()
        # Telegram contacts are always international, sometimes without the "+".
        await self._accept_phone(phone if phone.startswith("+") else "+" + phone, session, out)

    async def _accept_phone(self, raw: str, session: Session, out: Outcome) -> None:
        lang = session.lang
        try:
            session.phone = normalize_phone(raw, self._country_code)
        except InvalidPhone:
            out.say(
                t("invalid_phone", lang),
                contact_request=(t("btn_share_contact", lang), t("btn_cancel", lang)),
            )
            return
        session.step = Step.CONFIRM
        out.say(t("phone_saved", lang, phone=escape(session.phone)), remove_keyboard=True)
        await self._show_summary(session, out)

    async def _show_summary(self, session: Session, out: Outcome) -> None:
        lang = session.lang
        k = await self._knowledge.get()
        service = k.service(session.service_id)
        if service is None or session.start is None or not session.name or not session.phone:
            await self._expired(session, out)
            return
        out.say(
            t(
                "summary",
                lang,
                service=escape(service.name(lang)),
                price=escape(i18n.fmt_price(service.price, k.currency)),
                date=i18n.fmt_date(session.start.date(), lang),
                start=i18n.fmt_time(session.start),
                end=i18n.fmt_time(session.start + service.duration),
                name=escape(session.name),
                phone=escape(session.phone),
            ),
            [[Button(t("btn_confirm", lang), "confirm")], [Button(t("btn_cancel", lang), "act:cancel")]],
        )

    async def _confirm(self, msg: Incoming, session: Session, out: Outcome) -> None:
        lang = session.lang
        if session.step is not Step.CONFIRM or not (session.service_id and session.start and session.name
                                                     and session.phone):
            await self._expired(session, out)
            return
        service_id, start = session.service_id, session.start
        request = BookingRequest(
            service_id=service_id,
            start=start,
            customer_name=session.name,
            phone=session.phone,
            user_id=msg.user_id,
            lang=lang,
        )
        try:
            booking = await self._booking.book(request)
        except SlotTaken:
            out.say(t("slot_taken", lang))
            await self._ask_time(session, out, service_id, start.date())
            return
        except BookingError as exc:
            log.info("Booking rejected for user %s: %s", msg.user_id, type(exc).__name__)
            out.say(t("slot_unavailable", lang))
            await self._ask_date(session, out, service_id)
            return

        session.reset_flow()
        k = await self._knowledge.get()
        service = k.service(booking.service_id)
        out.say(
            t(
                "booked",
                lang,
                service=escape(service.name(lang) if service else booking.service_name),
                date=i18n.fmt_date(booking.start.date(), lang),
                start=i18n.fmt_time(booking.start),
                end=i18n.fmt_time(booking.end),
                name=escape(booking.customer_name),
                id=booking.id,
                address=escape(k.address),
            ),
            [[Button(t("btn_menu", lang), "act:menu")]],
        )
        price = i18n.fmt_price(service.price, k.currency) if service else ""
        out.owner_notices.append(
            f"🆕 <b>New booking</b> · <code>{booking.id}</code>\n"
            f"💈 {escape(booking.service_name)}{f' ({escape(price)})' if price else ''}\n"
            f"📅 {i18n.fmt_date(booking.start.date(), 'en')} · "
            f"{i18n.fmt_time(booking.start)}–{i18n.fmt_time(booking.end)}\n"
            f"👤 {escape(booking.customer_name)}\n"
            f"📞 {escape(booking.phone)}\n"
            f"💬 {self._customer_link(msg)}"
        )

    async def _cancel_flow(self, session: Session, out: Outcome) -> None:
        was_booking = session.step is not Step.IDLE
        session.reset_flow()
        if was_booking:
            out.say(t("flow_cancelled", session.lang), remove_keyboard=session.contact_keyboard)
        await self._menu(session, out)

    async def _expired(self, session: Session, out: Outcome) -> None:
        session.reset_flow()
        out.say(t("session_expired", session.lang))
        await self._menu(session, out)

    def _sync_keyboard(self, session: Session, out: Outcome) -> None:
        """Make sure the "share phone" keyboard disappears once the user leaves the phone step.

        Telegram allows one keyboard per message, so removal must ride on a message
        without inline buttons; if there isn't one, send a short "OK" first.
        """
        if not session.contact_keyboard or session.step is Step.PHONE or not out.replies:
            return
        if not any(r.remove_keyboard for r in out.replies):
            first = out.replies[0]
            if first.buttons or first.contact_request:
                out.replies.insert(0, Reply(t("ok", session.lang), remove_keyboard=True))
            else:
                first.remove_keyboard = True
        session.contact_keyboard = False

    # -- admin ------------------------------------------------------------------------------------

    @staticmethod
    def _admin_line(b: Booking) -> str:
        return (
            f"<b>{i18n.fmt_time(b.start)}–{i18n.fmt_time(b.end)}</b> · {escape(b.service_name)} · "
            f"{escape(b.customer_name)} · {escape(b.phone)} · <code>{b.id}</code>"
        )

    async def _admin_today(self, out: Outcome) -> None:
        today = self._booking.today()
        start = self._booking.day_start(today)
        bookings = await self._booking.bookings_between(start, start + timedelta(days=1))
        header = f"📋 <b>Today, {i18n.fmt_date(today, 'en')}</b>"
        if not bookings:
            out.say(f"{header}\nNo bookings yet.")
            return
        lines = [f"{header}: {len(bookings)} booking(s)", ""] + [self._admin_line(b) for b in bookings]
        out.say("\n".join(lines))

    async def _admin_upcoming(self, out: Outcome) -> None:
        now = self._booking.now()
        end = self._booking.day_start(self._booking.today() + timedelta(days=self._booking.days_ahead))
        bookings = [b for b in await self._booking.bookings_between(self._booking.day_start(now.date()), end)
                    if b.end > now]
        if not bookings:
            out.say(f"📋 No upcoming bookings in the next {self._booking.days_ahead} days.")
            return
        lines = [f"📋 <b>Upcoming bookings</b>: {len(bookings)}"]
        current_day: date | None = None
        for b in bookings:
            if b.start.date() != current_day:
                current_day = b.start.date()
                lines += ["", f"<b>{i18n.fmt_date(current_day, 'en')}</b>"]
            lines.append(self._admin_line(b))
        lines += ["", "Cancel one with <code>/cancel &lt;id&gt;</code>."]
        out.say("\n".join(lines))

    async def _admin_cancel(self, raw_id: str, out: Outcome) -> None:
        booking = await self._booking.cancel(raw_id)
        if booking is None:
            out.say(f"No active booking with ID <code>{escape(normalize_booking_id(raw_id))}</code>.")
            return
        when = f"{i18n.fmt_date(booking.start.date(), 'en')} {i18n.fmt_time(booking.start)}"
        notified = " The customer has been notified." if booking.user_id else ""
        out.say(
            f"❌ Cancelled <code>{booking.id}</code>: {when} · {escape(booking.service_name)} · "
            f"{escape(booking.customer_name)} · {escape(booking.phone)}.{notified}"
        )
        if booking.user_id:
            lang = booking.lang
            out.user_messages.append(
                (
                    booking.user_id,
                    Reply(
                        t(
                            "cancelled_by_shop",
                            lang,
                            id=booking.id,
                            date=i18n.fmt_date(booking.start.date(), lang),
                            time=i18n.fmt_time(booking.start),
                        ),
                        [[Button(t("btn_book", lang), "act:book")]],
                    ),
                )
            )

    # -- parsing helpers --------------------------------------------------------------------------

    @staticmethod
    def _parse_day(raw: str) -> date | None:
        try:
            return datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            return None

    def _parse_start(self, raw: str) -> datetime | None:
        try:
            return datetime.strptime(raw, "%Y%m%d%H%M").replace(tzinfo=self._booking.tz)
        except ValueError:
            return None
