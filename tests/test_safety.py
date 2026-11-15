"""Rate limiting, retries, prompt hygiene and configuration."""

import pytest

from config import Settings
from services.ai.prompt import build_system_prompt, looks_like_leak
from services.ratelimit import Decision, RateLimiter
from services.retry import is_transient, retry_async


# -- rate limiter ---------------------------------------------------------------------------------


def test_rate_limiter_sliding_window():
    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    assert limiter.hit("u") is Decision.ALLOW
    assert limiter.hit("u") is Decision.ALLOW
    assert limiter.hit("u") is Decision.BLOCK_NOTIFY
    assert limiter.hit("u") is Decision.BLOCK_SILENT
    assert limiter.hit("other") is Decision.ALLOW  # per user
    now[0] = 10.5
    assert limiter.hit("u") is Decision.ALLOW  # window moved on
    assert limiter.hit("u") is Decision.ALLOW
    assert limiter.hit("u") is Decision.BLOCK_NOTIFY  # warns again in a new burst


# -- retry ----------------------------------------------------------------------------------------


class HttpError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


async def no_sleep(_):
    return None


async def test_retry_recovers_from_transient_errors():
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise HttpError(503)
        return "ok"

    assert await retry_async(flaky, attempts=3, sleep=no_sleep) == "ok"
    assert len(calls) == 3


async def test_retry_does_not_retry_permanent_errors():
    calls = []

    async def bad_request():
        calls.append(1)
        raise HttpError(400)

    with pytest.raises(HttpError):
        await retry_async(bad_request, attempts=5, sleep=no_sleep)
    assert len(calls) == 1


async def test_retry_gives_up_after_the_last_attempt():
    delays = []

    async def record(delay):
        delays.append(delay)

    async def down():
        raise TimeoutError("still down")

    with pytest.raises(TimeoutError):
        await retry_async(down, attempts=3, base_delay=1, sleep=record)
    assert len(delays) == 2 and delays[1] > delays[0] * 0.9  # backoff grows


@pytest.mark.parametrize(
    ("exc", "expected"),
    [(HttpError(429), True), (HttpError(500), True), (HttpError(404), False), (ConnectionError(), True),
     (ValueError("bad data"), False)],
)
def test_is_transient(exc, expected):
    assert is_transient(exc) is expected


def test_network_errors_of_every_http_stack_are_transient():
    import aiohttp
    import httpx2

    assert is_transient(httpx2.ConnectError("refused"))
    assert is_transient(aiohttp.ServerDisconnectedError())
    assert is_transient(aiohttp.ClientConnectorError(connection_key=None, os_error=OSError("no route")))


# -- prompt hygiene -------------------------------------------------------------------------------


def test_system_prompt_contains_shop_data_and_language(knowledge):
    prompt = build_system_prompt(knowledge, "ru", canary="c4n4ry")
    assert "Test Barber" in prompt and "15 AZN" in prompt and "Sunday: closed" in prompt
    assert "Reply in Russian" in prompt
    assert "Yes, cards and cash." in prompt


def test_leak_detection():
    assert looks_like_leak("Sure! Internal marker: c4n4ry", "c4n4ry")
    assert looks_like_leak("RULES: 1. Answer ONLY from the SHOP DATA: section", "zzz")
    assert not looks_like_leak("A men's haircut costs 15 AZN.", "c4n4ry")


# -- settings -------------------------------------------------------------------------------------

ENV_NAMES = ["MODE", "TELEGRAM_BOT_TOKEN", "OWNER_TELEGRAM_ID", "GEMINI_API_KEY", "GOOGLE_SERVICE_ACCOUNT_FILE",
             "GOOGLE_SHEET_ID", "GOOGLE_CALENDAR_ID", "TIMEZONE", "GEMINI_MODEL", "GEMINI_THINKING_LEVEL"]


@pytest.fixture
def clean_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_empty_values_in_env_file_mean_not_set(tmp_path, clean_env):
    env = tmp_path / ".env"
    env.write_text("MODE=LIVE\nTELEGRAM_BOT_TOKEN=\nOWNER_TELEGRAM_ID=\nTIMEZONE=\n", encoding="utf-8")
    settings = Settings(_env_file=env)
    assert settings.mode == "live"
    assert settings.telegram_bot_token is None and settings.owner_telegram_id is None
    assert settings.timezone == "Asia/Baku"
    assert settings.missing_live_settings() == [
        "GEMINI_API_KEY", "GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_SHEET_ID", "GOOGLE_CALENDAR_ID"
    ]


def test_secrets_never_appear_in_repr(tmp_path, clean_env):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=123456:SECRET-TOKEN\nGEMINI_API_KEY=AIzaSECRET\n", encoding="utf-8")
    settings = Settings(_env_file=env)
    assert settings.telegram_bot_token.get_secret_value() == "123456:SECRET-TOKEN"
    assert "SECRET" not in repr(settings) and "SECRET" not in str(settings.model_dump())


def test_bad_timezone_is_rejected(clean_env):
    with pytest.raises(ValueError, match="time zone"):
        Settings(_env_file=None, timezone="Mars/Olympus")
