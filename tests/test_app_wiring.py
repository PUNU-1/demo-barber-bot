"""bot/app.py picks the right implementations for the settings it gets."""

from __future__ import annotations

from bot.app import build_engine
from config import Settings
from services.ai import FallbackAssistant, MockAssistant
from services.ai.gemini import GeminiAssistant
from services.faq import JsonKnowledge
from services.schedule import JsonSchedule


def demo_settings(tmp_path, **overrides) -> Settings:
    return Settings(_env_file=None, mode="demo", data_dir=tmp_path, **overrides)


def test_demo_without_a_gemini_key_is_fully_offline(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    engine = build_engine(demo_settings(tmp_path), owner_id=None)
    assert isinstance(engine._assistant, MockAssistant)
    assert isinstance(engine._knowledge, JsonKnowledge)


def test_demo_with_a_gemini_key_uses_gemini_on_local_data(tmp_path):
    engine = build_engine(demo_settings(tmp_path, gemini_api_key="test-key-not-real"), owner_id=None)
    assistant = engine._assistant
    assert isinstance(assistant, FallbackAssistant)
    assert isinstance(assistant._primary, GeminiAssistant)
    assert isinstance(assistant._fallback, MockAssistant)  # an outage still gets an answer
    assert isinstance(engine._knowledge, JsonKnowledge)  # no Google Sheets or Calendar needed
    assert isinstance(engine._booking._schedule, JsonSchedule)


def test_gemini_thinking_level_setting_reaches_the_request_config(tmp_path):
    settings = demo_settings(tmp_path, gemini_api_key="test-key-not-real", gemini_thinking_level=" LOW ")
    assert settings.gemini_thinking_level == "low"
    gemini = build_engine(settings, owner_id=None)._assistant._primary
    assert gemini._thinking is not None and gemini._thinking.thinking_level.value == "LOW"
