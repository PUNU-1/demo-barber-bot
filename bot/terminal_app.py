"""Terminal chat for zero-key DEMO mode. Same engine as Telegram; buttons become numbers."""

from __future__ import annotations

import asyncio
import html
import re
import textwrap

from bot.engine import Button, Engine, Incoming, Outcome
from config import Settings

_TAG_RE = re.compile(r"<[^>]+>")

BANNER = """\
──────────────────────────────────────────────────────────────
 💈 Demo Barber · terminal chat ({mode} mode · {ai})
──────────────────────────────────────────────────────────────
 • Chat as a customer, in English, Русский or Azərbaycanca.
 • Buttons show up as [1] [2] ...; type a number to press one.
 • You're also the owner here: /today, /bookings, /cancel <id>.
 • /start shows the menu, /quit exits.
{hint}
"""


def _plain(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text))


def _print_block(prefix: str, text: str) -> None:
    pad = " " * len(prefix)
    lines = _plain(text).splitlines() or [""]
    print(prefix + lines[0])
    for line in lines[1:]:
        print(pad + line)


def render(outcome: Outcome) -> list[Button]:
    """Print an outcome; returns the buttons in the order they were numbered."""
    buttons: list[Button] = []
    for reply in outcome.replies:
        print()
        _print_block("bot › ", reply.text)
        for row in reply.buttons:
            cells = []
            for button in row:
                buttons.append(button)
                cells.append(f"[{len(buttons)}] {button.text}")
            print("      " + "   ".join(cells))
        if reply.contact_request:
            print("      (on Telegram there's a 'share my phone number' button; here, just type it)")
    for notice in outcome.owner_notices:
        print()
        _print_block("📣 to owner › ", notice)
    for user_id, reply in outcome.user_messages:
        print()
        _print_block(f"✉️  to customer {user_id} › ", reply.text)
    print()
    return buttons


def run_terminal(engine: Engine, settings: Settings, *, user_id: int) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(engine.warm_up())
        ai = f"Gemini {settings.gemini_model}" if settings.gemini_api_key else "offline assistant"
        hint = (
            " Run without --terminal to start the same bot on Telegram."
            if settings.telegram_bot_token
            else " Set TELEGRAM_BOT_TOKEN in .env to run the same bot on Telegram."
        )
        print(BANNER.format(mode=settings.mode.upper(), ai=ai, hint=hint))
        buttons = render(loop.run_until_complete(engine.handle(Incoming(user_id=user_id, text="/start"))))
        while True:
            try:
                line = input("you › ").replace("﻿", "").strip()  # piped input may start with a BOM
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line.lower() in ("/quit", "/exit", "quit", "exit"):
                break
            if not line:
                continue
            if line.isdigit() and buttons and 1 <= int(line) <= len(buttons):
                button = buttons[int(line) - 1]
                print(textwrap.indent(f"↳ {button.text}", "      "))
                incoming = Incoming(user_id=user_id, callback=button.data, display_name="Terminal user")
            else:
                incoming = Incoming(user_id=user_id, text=line, display_name="Terminal user")
            buttons = render(loop.run_until_complete(engine.handle(incoming)))
    finally:
        loop.close()
    print("Bye! 👋")
