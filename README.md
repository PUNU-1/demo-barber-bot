# 💈 Demo Barber: Telegram AI assistant for a barbershop

A Telegram bot for a fictional barbershop. It answers customer questions, books appointments
without double booking, and notifies the owner. It speaks **Azerbaijani, Russian and English**
and replies in the language each customer writes in.

It runs in two modes:

* **DEMO**: local JSON files, no Google Cloud setup. With zero keys an offline keyword "AI"
  answers; add a free Gemini API key and **Gemini answers from the same local data**.
  `python -m bot` just works, in your terminal, or on Telegram if you add a bot token.
* **LIVE**: Gemini answers questions, a Google Sheet holds the FAQ the owner edits, and Google
  Calendar holds the bookings.

**Tech stack:** Python 3.11+, asyncio, aiogram 3 (Telegram Bot API), Google Gemini via
`google-genai` (structured JSON output), Google Sheets (`gspread`) and Google Calendar API,
pydantic v2 + pydantic-settings, pytest + pytest-asyncio.

## What it does

| Feature | How |
|---|---|
| **FAQ** | Prices, hours, address and custom Q&A come from a Google Sheet (`faq.json` in DEMO) that the owner edits without touching code. The AI answers **only** from that data. If the answer isn't there, it says so and offers a "Talk to a human" button. |
| **Booking** | Guided flow: service → day → free time → name → phone (typed, or Telegram's "share contact" button) → confirm. Free slots come from Google Calendar (or `bookings.json`), so events the owner adds by hand (lunch, day off) also block slots. Double booking is prevented. |
| **Owner notifications** | Every new booking and every "talk to a human" request goes to the owner's chat, with a link to the customer. |
| **Admin commands** | Owner only, checked by Telegram user id: `/today`, `/bookings`, `/cancel <id>`. A cancelled customer is told in their own language. |
| **Languages** | Detected on every message (Cyrillic → Russian; ə/ğ/ı/ş… or common words like *salam, qiymet* → Azerbaijani; otherwise English). All texts and buttons exist in all three languages. |
| **Safety** | Per-user rate limit, input length limit, prompt-extraction refusal, a canary that blocks leaked prompts, no secrets in prompts or logs, retries with backoff, friendly error messages, offline fallback when Gemini is down. |

## Screenshots

> Add your own after recording the demo (see [Recording the 60-second demo](#recording-the-60-second-demo)).
> Put the images in `docs/screenshots/` and uncomment the lines below.

<!--
| Menu | Booking | Confirmation | Owner notification |
|---|---|---|---|
| ![Menu](docs/screenshots/01-menu.png) | ![Booking](docs/screenshots/02-booking.png) | ![Confirmed](docs/screenshots/03-confirmed.png) | ![Owner](docs/screenshots/04-owner.png) |
-->

## Quick start: DEMO mode (no keys)

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m bot
```

With no Telegram token, the bot opens a **chat in your terminal**. It runs the same engine,
with buttons shown as `[1] [2] …` (type the number to press one). You're the owner there too,
so `/today`, `/bookings` and `/cancel <id>` work.

### DEMO on Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. `cp .env.example .env` (Windows: `copy .env.example .env`) and set `TELEGRAM_BOT_TOKEN`.
3. Run `python -m bot`, open your bot in Telegram, send `/whoami` and put that number in
   `OWNER_TELEGRAM_ID`. Restart the bot. Admin commands and notifications are now on.

Edit `data/faq.json` while the bot runs and the changes are picked up on the next message.
Bookings are written to `data/bookings.json` (git-ignored).

### DEMO with real AI (just a Gemini key)

Get a free key at <https://aistudio.google.com/apikey> and set `GEMINI_API_KEY` in `.env`.
Keep `MODE=demo`: Gemini now answers free-form questions in all three languages from
`data/faq.json` (*"my son is 8, can I bring him?"*, *"what time do you close on Saturday?"*),
while bookings stay in `bookings.json`. No Google Sheet or Calendar is needed.

`GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`, which answers in about 1–3 seconds. Google
retires models regularly, so if you get a 404, pick another model your key lists. If Gemini
fails or takes more than 12 seconds, the offline assistant answers instead, so the chat never
hangs.

## LIVE mode setup

1. **Gemini key**: create one at <https://aistudio.google.com/apikey> and set `GEMINI_API_KEY`
   (see [DEMO with real AI](#demo-with-real-ai-just-a-gemini-key) for the model settings).
2. **Service account**: in Google Cloud Console, enable the *Google Sheets API* and the
   *Google Calendar API*, create a service account, download its JSON key to
   `secrets/service_account.json` (git-ignored) and set `GOOGLE_SERVICE_ACCOUNT_FILE`.
3. **Sheet**: create an empty Google Sheet and share it with the service account's email
   (Editor for the next step; Viewer is enough afterwards). Put the id from the URL
   (`/d/<id>/edit`) in `GOOGLE_SHEET_ID`, then fill it with the demo data:
   ```bash
   python -m tools.seed_sheet
   ```
   | Tab | Columns |
   |---|---|
   | `Info` | `key`, `value` (shop_name, address, phone, currency, maps_url) |
   | `Hours` | `day`, `open`, `close` (leave both empty for a day off) |
   | `Services` | `id`, `name_en`, `name_ru`, `name_az`, `duration_min`, `price` |
   | `FAQ` | `question`, `answer_en`, `answer_ru`, `answer_az`, `keywords` |
4. **Calendar**: create a calendar for bookings and share it with the service account
   (*Make changes to events*). Copy the *Calendar ID* from its settings into `GOOGLE_CALENDAR_ID`.
5. Set `MODE=live` and run `python -m bot`. If anything is missing, the bot lists exactly which
   settings it needs and exits.

The sheet is cached for `FAQ_CACHE_SECONDS` (default 5 minutes). If Google is unreachable,
the bot keeps serving the last copy it loaded.

## Architecture

```
  Telegram customer / owner               You, in a terminal (zero keys)
            │                                         │
  ┌─────────▼──────────┐                    ┌─────────▼──────────┐
  │ bot/telegram_app   │                    │ bot/terminal_app   │
  │ aiogram 3 adapter  │                    │ stdin/stdout       │
  └─────────┬──────────┘                    └─────────┬──────────┘
            │      Incoming (text / button / contact) │
            └──────────────────┬──────────────────────┘
                               ▼
  ┌───────────────────────────────────────────────────────────────┐
  │ bot/engine.py: conversation engine (no Telegram imports)      │
  │ rate limit · length limit · language detection · intents      │
  │ booking wizard · human handoff · admin commands               │
  └──────┬───────────────────┬────────────────────┬───────────────┘
         │ Outcome: replies + owner notices + messages to customers
         ▼                   ▼                    ▼
  ┌──────────────┐   ┌───────────────┐   ┌──────────────────┐   ┌───────────────────┐
  │ services/ai  │   │ services/faq  │   │ services/booking │──▶│ services/slots    │
  │ Gemini │ Mock│   │ Sheet │ JSON  │   │ validation, lock │   │ pure slot maths   │
  └──────────────┘   └───────────────┘   └────────┬─────────┘   └───────────────────┘
                                                  ▼
                                         ┌──────────────────┐
                                         │ services/schedule│
                                         │ Calendar │ JSON  │
                                         └──────────────────┘
```

* **One engine, two front ends.** The engine takes an `Incoming` and returns an `Outcome`. The
  Telegram and terminal runners are thin adapters, so the zero-key demo is the real bot, and
  tests drive whole conversations without Telegram.
* **Each integration sits behind a small interface** with a DEMO and a LIVE implementation,
  chosen in one place (`bot/app.py`). Google libraries are imported only when they're used.
* **Buttons carry their own state** (`time:haircut:202611181430`), so they keep working after a
  restart. The in-memory session holds only the name and phone being typed.
* On Telegram, pressing a button **edits the message in place**, so the booking wizard doesn't
  flood the chat.

```
bot/        __main__.py (entry), app.py (wiring), engine.py, telegram_app.py, terminal_app.py
services/   slots.py, booking.py, intents.py, language.py, i18n.py, ratelimit.py, retry.py
            faq/ (json, sheets, cache, parsing)  schedule/ (json, google_calendar)  ai/ (gemini, mock, prompt)
config/     settings.py (environment variables only)
data/       faq.json (demo shop data)
tools/      seed_sheet.py (LIVE setup helper)
tests/      slots, booking, engine conversations, language, knowledge, safety,
            telegram adapter + end-to-end, LIVE adapters (Gemini, Calendar, Sheets) offline
```

### No double booking

`BookingService.book()` validates the request (name, phone, opening hours, 30-minute grid,
60-minute lead time, 14-day window), then **under an asyncio lock** re-reads busy time from
storage and only then creates the booking. In LIVE mode that re-read is a Calendar free/busy
query, so it also catches an event the owner added a second ago. A test fires four concurrent
requests at one slot and expects exactly one booking. Remove the lock and it fails.

### Safety

* Rate limit per user (sliding window). The first blocked message gets a warning, later ones get
  silence, so spam isn't answered. The owner is exempt.
* Messages longer than `MAX_INPUT_CHARS` are rejected, and control characters are stripped.
* The system prompt contains **only public shop data**. No keys or ids ever reach the model.
  Prompt-extraction attempts are refused before the model is called, and a random canary in the
  prompt blocks any answer that leaks it.
* Secrets are `SecretStr` (never printed). `.env`, `secrets/` and key files are git-ignored.
* Gemini, Sheets, Calendar and Telegram calls retry transient failures (timeouts, 429, 5xx) with
  exponential backoff and jitter. If Gemini still fails, or the whole answer takes more than
  12 seconds, the offline assistant answers. Any other error gives the customer a polite
  message, and the bot keeps running.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite (~200 tests, a few seconds) never touches the network or your real `.env`. It covers:

* **Core rules**: slot maths, booking validation, the concurrent double-booking guard.
* **Conversations**: full bookings in all three languages, human handoff, admin commands, rate
  limiting, prompt-extraction refusal.
* **Data**: FAQ parsing and hot reload, the stale-cache fallback, retries, settings.
* **Telegram, end to end**: updates go through aiogram's real `Dispatcher` and `Bot`, with a
  recording session in place of the Telegram servers.
* **LIVE adapters, offline**: the real google-genai SDK sends its requests to a mocked HTTP
  transport, and the real googleapiclient (whose static discovery document rejects unknown
  parameters) talks to a small in-memory fake of the Calendar API. Gemini retries, the offline
  fallback and the prompt-leak block are tested the same way.

## Recording the 60-second demo

Use Telegram Desktop for the customer and your phone (or a second account) as the owner.

Before recording, open the bot once **from the owner account** and press **Start**: Telegram
doesn't let a bot message anyone who hasn't started it, so until then the owner gets no
notifications (the bot logs a warning about this at startup). Restart the bot afterwards so the
owner's command menu appears.

| Time | Action |
|---|---|
| 0:00 | `/start`: the menu appears in the language of your Telegram app |
| 0:05 | Type a free-form question, e.g. *Можно прийти с сыном, ему 8 лет?*: the answer arrives in Russian |
| 0:12 | Tap **📅 Записаться** → a service → a day → a time (the message updates in place) |
| 0:30 | Type a name, tap **📱 Отправить мой номер** |
| 0:40 | **✅ Подтвердить**: confirmation with a booking ID. The owner's phone gets the notification |
| 0:50 | As the owner: `/today` shows the booking |

## What I would improve next

* **Customer self-service**: `/mybookings`, reschedule or cancel your own booking, reminders 24 h and 2 h before.
* **Production deployment**: webhooks + Docker, sessions and rate limits in Redis, so several instances can run behind a load balancer.
* **Several barbers**, each with their own calendar, hours, breaks and holidays.
* **Two-way handoff**: relay the owner's replies to the customer through the bot instead of a profile link.
* **Evaluation set for the LLM**: multilingual FAQ questions and injection attempts, run in CI against Gemini.
* **Smarter DEMO matching**: the offline assistant is deliberately simple keyword matching and misses paraphrases that Gemini handles.
* Localised admin messages, structured logs and metrics (bookings per day, unanswered questions).

## Notes and limitations

* The LIVE adapters are tested offline against the real SDKs (see [Tests](#tests)). DEMO with
  Gemini and the Telegram connection were also checked against the real services. What tests
  can't check is your Google Cloud setup (enabled APIs, sharing), so run LIVE mode once with
  your own service account.
* Gemini's free tier has per-minute and per-day limits. When they're hit, the offline
  assistant answers until the quota resets.
* Sessions live in memory: a restart drops a booking that is halfway typed (buttons still work).
* Slot times use wall-clock arithmetic, which is exact for Asia/Baku (no daylight saving time).
* Demo shop data, names and the address are fictional.
