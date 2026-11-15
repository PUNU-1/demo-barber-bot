"""Telegram adapter (aiogram 3): turns updates into ``Incoming`` and ``Outcome`` into messages."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from bot.engine import Engine, Incoming, Outcome, Reply
from config import Settings
from services.retry import retry_async

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096

CUSTOMER_COMMANDS = {
    "en": [("start", "Main menu"), ("book", "Book an appointment"), ("help", "What I can do")],
    "ru": [("start", "Главное меню"), ("book", "Записаться"), ("help", "Что я умею")],
    "az": [("start", "Əsas menyu"), ("book", "Növbəyə yazıl"), ("help", "Nə edə bilərəm")],
}
OWNER_COMMANDS = [
    ("today", "Today's bookings"),
    ("bookings", "Upcoming bookings"),
    ("cancel", "Cancel a booking: /cancel <id>"),
    ("whoami", "Show my Telegram id"),
]


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (TelegramNetworkError, TelegramRetryAfter, TelegramServerError))


def _split(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split long texts on line breaks so no message exceeds Telegram's limit."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


class TelegramSender:
    def __init__(self, bot: Bot, owner_id: int | None) -> None:
        self._bot = bot
        self._owner_id = owner_id

    @staticmethod
    def _markup(reply: Reply) -> InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None:
        if reply.contact_request:
            share, cancel = reply.contact_request
            return ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=share, request_contact=True)], [KeyboardButton(text=cancel)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            )
        if reply.buttons:
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=b.text, callback_data=b.data) for b in row] for row in reply.buttons
                ]
            )
        if reply.remove_keyboard:
            return ReplyKeyboardRemove()
        return None

    async def _send_call(self, call: Callable[[], Awaitable[object]], what: str) -> bool:
        try:
            await retry_async(call, op=f"telegram.{what}", is_retryable=_is_transient)
            return True
        except TelegramForbiddenError:
            log.warning("Cannot %s: the user blocked the bot or never started it", what)
        except Exception:
            log.exception("Failed to %s", what)
        return False

    async def send(self, chat_id: int, reply: Reply) -> None:
        chunks = _split(reply.text)
        for index, chunk in enumerate(chunks):
            markup = self._markup(reply) if index == len(chunks) - 1 else None
            await self._send_call(
                lambda chunk=chunk, markup=markup: self._bot.send_message(chat_id, chunk, reply_markup=markup),
                "send_message",
            )

    async def _try_edit(self, message: Message, reply: Reply) -> bool:
        """Edit the message whose button was pressed, so the booking wizard updates in place."""
        if reply.contact_request or reply.remove_keyboard or len(reply.text) > TELEGRAM_LIMIT:
            return False
        markup = self._markup(reply)
        try:
            await message.edit_text(reply.text, reply_markup=markup if isinstance(markup, InlineKeyboardMarkup) else None)
            return True
        except TelegramBadRequest as exc:
            return "message is not modified" in str(exc).lower()
        except Exception:
            log.debug("Edit failed; sending a new message instead", exc_info=True)
            return False

    async def deliver(self, chat_id: int, outcome: Outcome, *, edit: Message | None = None) -> None:
        for index, reply in enumerate(outcome.replies):
            if index == 0 and edit is not None and await self._try_edit(edit, reply):
                continue
            if index == 0 and edit is not None:
                await self._clear_buttons(edit)
            await self.send(chat_id, reply)
        for notice in outcome.owner_notices:
            await self.notify_owner(notice)
        for user_id, reply in outcome.user_messages:
            await self.send(user_id, reply)

    async def _clear_buttons(self, message: Message) -> None:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass  # old or already-edited message: harmless

    async def notify_owner(self, text: str) -> None:
        if self._owner_id is None:
            log.warning("OWNER_TELEGRAM_ID is not set; owner notification dropped")
            return
        await self._send_call(lambda: self._bot.send_message(self._owner_id, text), "notify owner")


async def _set_commands(bot: Bot, owner_id: int | None) -> None:
    try:
        for lang, commands in CUSTOMER_COMMANDS.items():
            await bot.set_my_commands(
                [BotCommand(command=c, description=d) for c, d in commands],
                language_code=None if lang == "en" else lang,
            )
        if owner_id:
            owner = [BotCommand(command=c, description=d) for c, d in CUSTOMER_COMMANDS["en"] + OWNER_COMMANDS]
            await bot.set_my_commands(owner, scope=BotCommandScopeChat(chat_id=owner_id))
    except Exception as exc:  # e.g. the owner hasn't started the bot yet
        log.warning("Could not register the command menu: %s", exc)


def _incoming_from(user, **fields) -> Incoming:
    return Incoming(
        user_id=user.id,
        language_code=user.language_code,
        display_name=user.full_name,
        username=user.username,
        **fields,
    )


def build_dispatcher(engine: Engine, sender: TelegramSender) -> Dispatcher:
    """Wire Telegram updates to the engine. Separate from polling so tests can feed updates."""
    router = Router()
    router.message.filter(F.chat.type == ChatType.PRIVATE)  # ignore groups and channels

    @router.message()
    async def on_message(message: Message) -> None:
        user = message.from_user
        if user is None or user.is_bot:
            return
        incoming = _incoming_from(
            user,
            text=message.text,
            contact_phone=message.contact.phone_number if message.contact else None,
        )
        outcome = await engine.handle(incoming)
        await sender.deliver(message.chat.id, outcome)

    @router.callback_query()
    async def on_callback(query: CallbackQuery) -> None:
        try:
            await query.answer()  # stop the button's loading spinner right away
        except Exception:
            pass
        outcome = await engine.handle(_incoming_from(query.from_user, callback=query.data or ""))
        message = query.message if isinstance(query.message, Message) else None
        chat_id = message.chat.id if message else query.from_user.id
        await sender.deliver(chat_id, outcome, edit=message)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_telegram(engine: Engine, settings: Settings) -> None:
    assert settings.telegram_bot_token is not None
    await engine.warm_up()

    bot = Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dispatcher = build_dispatcher(engine, TelegramSender(bot, settings.owner_telegram_id))
    try:
        me = await bot.get_me()
        await _set_commands(bot, settings.owner_telegram_id)
        await bot.delete_webhook(drop_pending_updates=True)
        if settings.owner_telegram_id is None:
            log.warning("OWNER_TELEGRAM_ID is not set: admin commands and owner notifications are off")
        log.info("Demo Barber bot is running as @%s in %s mode. Press Ctrl+C to stop.", me.username, settings.mode.upper())
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()
