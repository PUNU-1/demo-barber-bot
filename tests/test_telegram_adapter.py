"""The Telegram adapter's offline logic: keyboards, message splitting, edit-in-place, owner routing."""

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove

from bot.engine import Button, Outcome, Reply
from bot.telegram_app import TELEGRAM_LIMIT, TelegramSender, _split
from tests.conftest import OWNER_ID, Chat


def test_inline_buttons_become_an_inline_keyboard():
    markup = TelegramSender._markup(Reply("x", [[Button("📅 Book", "act:book"), Button("🏠 Menu", "act:menu")]]))
    assert isinstance(markup, InlineKeyboardMarkup)
    assert [b.callback_data for b in markup.inline_keyboard[0]] == ["act:book", "act:menu"]


def test_contact_request_becomes_a_share_contact_keyboard():
    markup = TelegramSender._markup(Reply("x", contact_request=("📱 Share", "✖️ Cancel")))
    assert isinstance(markup, ReplyKeyboardMarkup)
    assert markup.keyboard[0][0].request_contact is True
    assert markup.keyboard[1][0].text == "✖️ Cancel"


def test_keyboard_removal_and_plain_text():
    assert isinstance(TelegramSender._markup(Reply("x", remove_keyboard=True)), ReplyKeyboardRemove)
    assert TelegramSender._markup(Reply("x")) is None


def test_long_texts_are_split_under_the_limit():
    text = "\n".join(f"line {i} " + "x" * 80 for i in range(200))
    chunks = _split(text)
    assert len(chunks) > 1
    assert all(len(c) <= TELEGRAM_LIMIT for c in chunks)
    assert "".join(chunks) == text


async def test_callback_data_always_fits_telegrams_64_byte_limit(engine):
    chat = Chat(engine)
    seen: list[str] = []
    for step in ("act:book", "svc:combo", "day:combo:20261117"):
        await chat.press(step)
        seen += chat.buttons()
    assert seen and all(len(data.encode()) <= 64 for data in seen)


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str, object]] = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


class FakeMessage:
    def __init__(self):
        self.edits: list[tuple[str, object]] = []

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))

    async def edit_reply_markup(self, reply_markup=None):
        pass


async def test_button_press_edits_the_message_in_place_and_notifies_the_owner():
    bot, message = FakeBot(), FakeMessage()
    sender = TelegramSender(bot, owner_id=OWNER_ID)
    outcome = Outcome(
        replies=[Reply("Pick a day:", [[Button("Tomorrow", "day:haircut:20261117")]]), Reply("second")],
        owner_notices=["🆕 New booking"],
        user_messages=[(555, Reply("your booking was cancelled"))],
    )
    await sender.deliver(42, outcome, edit=message)

    assert [text for text, _ in message.edits] == ["Pick a day:"]  # first reply replaced the pressed message
    assert [(chat, text) for chat, text, _ in bot.sent] == [
        (42, "second"),
        (OWNER_ID, "🆕 New booking"),
        (555, "your booking was cancelled"),
    ]


async def test_contact_keyboard_is_never_sent_as_an_edit():
    bot, message = FakeBot(), FakeMessage()
    sender = TelegramSender(bot, owner_id=None)
    await sender.deliver(42, Outcome(replies=[Reply("phone?", contact_request=("Share", "Cancel"))]), edit=message)
    assert message.edits == []
    assert isinstance(bot.sent[0][2], ReplyKeyboardMarkup)
