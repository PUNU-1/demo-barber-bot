"""Answering free-text questions. DEMO: ``MockAssistant``. LIVE: ``GeminiAssistant`` with mock fallback."""

from services.ai.base import AIReply, Assistant, FallbackAssistant
from services.ai.mock import MockAssistant

__all__ = ["AIReply", "Assistant", "FallbackAssistant", "MockAssistant"]
