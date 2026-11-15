"""Entry point: ``python -m bot``.

* ``TELEGRAM_BOT_TOKEN`` set -> runs on Telegram.
* No token (or ``--terminal``) -> chat with the same engine in this terminal.
* ``MODE=live`` -> Gemini + Google Sheets + Google Calendar; otherwise local DEMO data
  (answered by Gemini if ``GEMINI_API_KEY`` is set, by the offline assistant if not).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from pydantic import ValidationError

TERMINAL_USER_ID = 1  # the terminal user plays both customer and owner


def _force_utf8_console() -> None:
    """Emoji, Cyrillic and Azerbaijani must survive Windows consoles and pipes."""
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    for noisy in ("aiogram.event", "httpx", "httpcore", "googleapiclient.discovery_cache"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    _force_utf8_console()
    parser = argparse.ArgumentParser(prog="python -m bot", description="Demo Barber Telegram assistant")
    parser.add_argument("--terminal", action="store_true", help="chat in the terminal even if a token is set")
    args = parser.parse_args(argv)

    from config import Settings

    try:
        settings = Settings()
    except ValidationError as exc:
        print("Configuration error, please check your .env file:", file=sys.stderr)
        for error in exc.errors():
            name = ".".join(str(part) for part in error["loc"]).upper()
            print(f"  - {name}: {error['msg']}", file=sys.stderr)
        return 2

    use_telegram = settings.telegram_bot_token is not None and not args.terminal
    # In the terminal, log lines would mix with the chat, so only show warnings there.
    _setup_logging(settings.log_level if use_telegram else "WARNING")

    if settings.is_live:
        missing = settings.missing_live_settings()
        if missing:
            print("MODE=live needs these settings in .env:", file=sys.stderr)
            for name in missing:
                print(f"  - {name}", file=sys.stderr)
            print("Set MODE=demo to run without any keys.", file=sys.stderr)
            return 2

    from bot.app import build_engine
    from services.errors import ServiceUnavailable

    try:
        if use_telegram:
            from bot.telegram_app import run_telegram

            engine = build_engine(settings, owner_id=settings.owner_telegram_id)
            asyncio.run(run_telegram(engine, settings))
        else:
            from bot.terminal_app import run_terminal

            owner_id = settings.owner_telegram_id or TERMINAL_USER_ID
            engine = build_engine(settings, owner_id=owner_id)
            run_terminal(engine, settings, user_id=owner_id)
    except ServiceUnavailable as exc:
        print(f"Could not start: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
