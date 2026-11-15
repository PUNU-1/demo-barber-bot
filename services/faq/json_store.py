"""faq.json reader. Re-reads the file when it changes, so the owner can edit it while the bot runs."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from services.errors import KnowledgeUnavailable
from services.faq.parsing import parse_knowledge
from services.models import Knowledge

log = logging.getLogger(__name__)


class JsonKnowledge:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._mtime: int | None = None
        self._cached: Knowledge | None = None

    async def get(self) -> Knowledge:
        try:
            mtime = self._path.stat().st_mtime_ns
        except OSError as exc:
            if self._cached is not None:
                return self._cached
            raise KnowledgeUnavailable(f"cannot read {self._path}: {exc}") from exc

        if self._cached is not None and mtime == self._mtime:
            return self._cached

        self._mtime = mtime
        try:
            # utf-8-sig: Windows editors (Notepad, PowerShell) may save the file with a BOM.
            knowledge = parse_knowledge(json.loads(self._path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError) as exc:  # JSONDecodeError and KnowledgeError are ValueErrors
            if self._cached is not None:
                log.error("%s is invalid (%s); still using the previous version", self._path.name, exc)
                return self._cached
            raise KnowledgeUnavailable(f"{self._path.name} is invalid: {exc}") from exc

        if self._cached is not None:
            log.info("Reloaded %s", self._path.name)
        self._cached = knowledge
        return knowledge
