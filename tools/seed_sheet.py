"""Copy data/faq.json into your Google Sheet (LIVE setup helper).

Usage::

    python -m tools.seed_sheet

Needs GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_SHEET_ID in .env, and the sheet shared
with the service account as *Editor* (the bot itself only needs Viewer afterwards).
Creates or overwrites the tabs Info, Hours, Services and FAQ.
"""

from __future__ import annotations

import json
import sys

from config import Settings

TABS: dict[str, list[str]] = {
    "Info": ["key", "value"],
    "Hours": ["day", "open", "close"],
    "Services": ["id", "name_en", "name_ru", "name_az", "duration_min", "price"],
    "FAQ": ["question", "answer_en", "answer_ru", "answer_az", "keywords"],
}


def build_rows(data: dict) -> dict[str, list[list[object]]]:
    return {
        "Info": [[key, value] for key, value in data["info"].items()],
        "Hours": [[row["day"], row["open"], row["close"]] for row in data["hours"]],
        "Services": [[row.get(col, "") for col in TABS["Services"]] for row in data["services"]],
        "FAQ": [[row.get(col, "") for col in TABS["FAQ"]] for row in data.get("faq", [])],
    }


def main() -> int:
    settings = Settings()
    if not settings.google_service_account_file or not settings.google_sheet_id:
        print("Set GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_SHEET_ID in .env first.", file=sys.stderr)
        return 2

    import gspread

    data = json.loads((settings.data_dir / "faq.json").read_text(encoding="utf-8-sig"))
    rows = build_rows(data)
    client = gspread.service_account(filename=str(settings.google_service_account_file))
    spreadsheet = client.open_by_key(settings.google_sheet_id)
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}

    for title, header in TABS.items():
        worksheet = existing.get(title) or spreadsheet.add_worksheet(title=title, rows=100, cols=len(header))
        worksheet.clear()
        # RAW keeps "+994 ..." and "10:00" as text instead of formulas / time values.
        worksheet.update(values=[header] + rows[title], range_name="A1", value_input_option="RAW")
        print(f"  ✓ {title}: {len(rows[title])} rows")

    print(f"Done. Open https://docs.google.com/spreadsheets/d/{settings.google_sheet_id} to edit the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
