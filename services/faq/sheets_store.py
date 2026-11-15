"""Shop data from a Google Sheet (LIVE mode).

Expected worksheets (tab names) and header rows:

* ``Info``: key | value
* ``Hours``: day | open | close
* ``Services``: id | name_en | name_ru | name_az | duration_min | price
* ``FAQ`` (optional): question | answer_en | answer_ru | answer_az | keywords

``python -m tools.seed_sheet`` fills a blank sheet with the demo data.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from services.errors import KnowledgeError
from services.faq.parsing import parse_knowledge
from services.models import Knowledge
from services.retry import retry_async

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class SheetsKnowledge:
    def __init__(self, service_account_file: Path, sheet_id: str) -> None:
        self._file = service_account_file
        self._sheet_id = sheet_id
        self._client: Any = None

    async def get(self) -> Knowledge:
        raw = await retry_async(lambda: asyncio.to_thread(self._read_sync), op="sheets.read")
        return parse_knowledge(raw)

    def _read_sync(self) -> dict[str, Any]:
        import gspread

        if self._client is None:
            self._client = gspread.service_account(filename=str(self._file), scopes=SCOPES)
        spreadsheet = self._client.open_by_key(self._sheet_id)

        def records(title: str, *, required: bool = True) -> list[dict[str, Any]]:
            try:
                return spreadsheet.worksheet(title).get_all_records()
            except gspread.WorksheetNotFound:
                if required:
                    raise KnowledgeError(f"the Google Sheet has no '{title}' tab") from None
                return []

        info_rows = records("Info")
        info = {str(r.get("key", "")).strip(): r.get("value", "") for r in info_rows if r.get("key")}
        return {
            "info": info,
            "hours": records("Hours"),
            "services": records("Services"),
            "faq": records("FAQ", required=False),
        }
