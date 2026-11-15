"""Full booking through aiogram's real Dispatcher and Bot, with a fake HTTP session instead of Telegram.

Updates go in as Telegram would send them; every Bot API call the bot makes is recorded.
"""

from __future__ import annotations

from datetime import datetime
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update

from bot.telegram_app import TelegramSender, build_dispatcher
from tests.conftest import CUSTOMER_ID, OWNER_ID, TZ

BOT_USER = {"id": 999, "is_bot": True, "first_name": "Demo Barber", "username": "demo_barber_bot"}


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []
        self._ids = count(500)

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message.model_validate(
                {"message_id": next(self._ids), "date": 1763280000, "text": method.text, "from": BOT_USER,
                 "chat": {"id": method.chat_id, "type": "private"}},
                context={"bot": bot},
            )
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - not used
        yield b""

    async def close(self) -> None:
        pass

    def take(self) -> list:
        calls, self.calls = self.calls, []
        return calls


class TelegramHarness:
    def __init__(self, engine) -> None:
        self.session = RecordingSession()
        self.bot = Bot("123456:TEST-not-a-real-token", session=self.session,
                       default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dispatcher = build_dispatcher(engine, TelegramSender(self.bot, OWNER_ID))
        self._update_ids = count(1)

    def _user(self, user_id: int, lang: str) -> dict:
        return {"id": user_id, "is_bot": False, "first_name": "Ali", "username": "ali_test", "language_code": lang}

    async def _feed(self, payload: dict) -> list:
        update = Update.model_validate({"update_id": next(self._update_ids), **payload}, context={"bot": self.bot})
        await self.dispatcher.feed_update(self.bot, update)
        return self.session.take()

    async def text(self, text: str, user_id: int = CUSTOMER_ID, lang: str = "ru", chat_type: str = "private"):
        return await self._feed({"message": {
            "message_id": next(self._update_ids), "date": 1763280000, "text": text,
            "chat": {"id": user_id if chat_type == "private" else -100123, "type": chat_type},
            "from": self._user(user_id, lang),
        }})

    async def contact(self, phone: str, user_id: int = CUSTOMER_ID, lang: str = "ru"):
        return await self._feed({"message": {
            "message_id": next(self._update_ids), "date": 1763280000,
            "contact": {"phone_number": phone, "first_name": "Ali", "user_id": user_id},
            "chat": {"id": user_id, "type": "private"}, "from": self._user(user_id, lang),
        }})

    async def press(self, data: str, user_id: int = CUSTOMER_ID, lang: str = "ru"):
        return await self._feed({"callback_query": {
            "id": str(next(self._update_ids)), "chat_instance": "ci", "data": data,
            "from": self._user(user_id, lang),
            "message": {"message_id": 500, "date": 1763280000, "text": "…",
                        "chat": {"id": user_id, "type": "private"}, "from": BOT_USER},
        }})


def sent(calls, kind=SendMessage):
    return [c for c in calls if isinstance(c, kind)]


def callback_data(method) -> list[str]:
    markup = method.reply_markup
    return [b.callback_data for row in markup.inline_keyboard for b in row] if isinstance(markup, InlineKeyboardMarkup) else []


@pytest.fixture
def tg(engine) -> TelegramHarness:
    return TelegramHarness(engine)


async def test_full_booking_over_telegram(tg, schedule):
    calls = await tg.text("/start")
    [welcome] = sent(calls)
    assert welcome.chat_id == CUSTOMER_ID and "Здравствуйте" in welcome.text
    assert "act:book" in callback_data(welcome)

    calls = await tg.press("act:book")
    assert sent(calls, AnswerCallbackQuery)  # the button spinner is stopped
    [edit] = sent(calls, EditMessageText)  # the wizard updates the same message
    assert "Выберите услугу" in edit.text and "svc:haircut" in callback_data(edit)
    assert not sent(calls)

    for data, expected in (("svc:haircut", "Выберите день"), ("day:haircut:20261117", "Выберите время"),
                           ("time:haircut:202611171400", "На какое имя")):
        [edit] = sent(await tg.press(data), EditMessageText)
        assert expected in edit.text

    [ask_phone] = sent(await tg.text("Али Алиев"))
    assert isinstance(ask_phone.reply_markup, ReplyKeyboardMarkup)
    assert ask_phone.reply_markup.keyboard[0][0].request_contact is True

    saved, summary = sent(await tg.contact("994501234567"))
    assert isinstance(saved.reply_markup, ReplyKeyboardRemove) and "+994501234567" in saved.text
    assert callback_data(summary) == ["confirm", "act:cancel"]

    calls = await tg.press("confirm")
    [confirmation] = sent(calls, EditMessageText)
    assert "Вы записаны" in confirmation.text
    [owner_notice] = sent(calls)
    assert owner_notice.chat_id == OWNER_ID
    assert "New booking" in owner_notice.text and "Али Алиев" in owner_notice.text and "@ali_test" in owner_notice.text

    [booking] = await schedule.list_between(datetime(2026, 11, 17, tzinfo=TZ), datetime(2026, 11, 18, tzinfo=TZ))
    assert booking.id in confirmation.text

    [today] = sent(await tg.text("/bookings", user_id=OWNER_ID, lang="en"))
    assert today.chat_id == OWNER_ID and booking.id in today.text


async def test_group_messages_are_ignored(tg):
    assert await tg.text("/start", chat_type="group") == []


async def test_admin_commands_are_hidden_from_customers(tg):
    [reply] = sent(await tg.text("/today", lang="en"))
    assert "don't know that command" in reply.text
