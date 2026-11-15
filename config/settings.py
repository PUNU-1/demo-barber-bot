"""Application settings.

Configuration comes only from environment variables, optionally loaded from a
``.env`` file in the project root. Nothing secret is hard-coded, and secret
values are wrapped in ``SecretStr`` so they never show up in logs or reprs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed view of the environment. ``.env.example`` documents every variable."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # "KEY=" in .env means "not set", not "empty string"
        extra="ignore",
    )

    mode: Literal["demo", "live"] = "demo"

    # Telegram
    telegram_bot_token: SecretStr | None = None
    owner_telegram_id: int | None = None

    # LIVE integrations
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    google_service_account_file: Path | None = None
    google_sheet_id: str | None = None
    google_calendar_id: str | None = None

    # Booking rules
    timezone: str = "Asia/Baku"
    default_country_code: str = Field("994", pattern=r"^\d{1,3}$")
    booking_days_ahead: int = Field(14, ge=1, le=60)
    slot_step_minutes: int = Field(30, ge=5, le=120)
    min_lead_minutes: int = Field(60, ge=0, le=24 * 60)

    # Safety
    rate_limit_messages: int = Field(10, ge=1)
    rate_limit_window_seconds: int = Field(60, ge=1)
    max_input_chars: int = Field(500, ge=50, le=4000)

    # Misc
    faq_cache_seconds: int = Field(300, ge=0)
    data_dir: Path = PROJECT_ROOT / "data"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("mode", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("google_service_account_file", "data_dir")
    @classmethod
    def _resolve_relative(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            return PROJECT_ROOT / value
        return value

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}") from exc
        return value

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def missing_live_settings(self) -> list[str]:
        """Names of the variables LIVE mode needs but doesn't have (empty list = ready)."""
        missing: list[str] = []
        if self.gemini_api_key is None:
            missing.append("GEMINI_API_KEY")
        if self.google_service_account_file is None:
            missing.append("GOOGLE_SERVICE_ACCOUNT_FILE")
        elif not self.google_service_account_file.is_file():
            missing.append(f"GOOGLE_SERVICE_ACCOUNT_FILE (no file at {self.google_service_account_file})")
        if not self.google_sheet_id:
            missing.append("GOOGLE_SHEET_ID")
        if not self.google_calendar_id:
            missing.append("GOOGLE_CALENDAR_ID")
        return missing
