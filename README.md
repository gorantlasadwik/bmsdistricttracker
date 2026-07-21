# ShowPulser

**24×7 Movie Show Monitor for BookMyShow & District**

Never refresh BookMyShow or District manually again. ShowPulser watches your movie page and fires an instant Telegram (or Discord/WhatsApp/Email) notification the moment a new theatre is added, a new show time appears, a format like IMAX goes live, or booking opens.

---

## Quick Start (Local)

### 1. Clone & install dependencies

```bash
cd "bms show tracker"
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate    # Linux/macOS
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure your `.env`

```bash
copy .env.example .env
```

Open `.env` and fill in at minimum:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
ENABLED_NOTIFIERS=telegram
```

**Getting Telegram credentials:**
1. Open Telegram → search `@BotFather`
2. Send `/newbot` → follow prompts → copy the **token**
3. Send any message to your new bot
4. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` → find `chat.id`

### 3. Run the server

```bash
uvicorn app.api:app --reload --port 8000
```

### 4. Open the dashboard

```
http://localhost:8000/dashboard
```

### 5. Add a movie to monitor

In the dashboard, fill in the movie name and paste the BookMyShow/District URL, then click **Start Monitoring**.

Or via API:

```bash
curl -X POST http://localhost:8000/movies \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Spider-Man: Brand New Day",
    "city": "Chennai",
    "bms_url": "https://in.bookmyshow.com/...",
    "district_url": "https://www.district.in/...",
    "interval": 180
  }'
```

### 6. Trigger an immediate scan

```bash
curl -X POST http://localhost:8000/movies/1/scan
```

---

## Docker

```bash
copy .env.example .env
# Edit .env with your credentials

docker compose up --build -d
```

Access the dashboard at `http://localhost:8000/dashboard`.

Logs and database are persisted to `./logs` and `./data` on your host machine.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/status` | Scheduler status, last/next scan, stats |
| `GET` | `/movies` | List all monitored movies |
| `POST` | `/movies` | Add a movie |
| `DELETE` | `/movies/{id}` | Remove a movie |
| `POST` | `/movies/{id}/scan` | Trigger immediate scan |
| `GET` | `/movies/{id}/history` | Recent notification history |
| `GET` | `/dashboard` | Web dashboard |
| `GET` | `/docs` | Interactive API docs (Swagger UI) |

---

## Supported Notifications

| Channel | Status | Notes |
|---------|--------|-------|
| Telegram | ✅ Ready | Free, instant — recommended |
| Discord | ✅ Ready | Webhook-based, rich embeds |
| WhatsApp | ✅ Ready | Requires Twilio account |
| Email | ✅ Ready | SMTP (Gmail, etc.) |

---

## Change Detection

| Event | Description |
|-------|-------------|
| 🏛 New Theatre | A theatre not in the previous scan |
| 🕐 New Show | A new time slot at an existing theatre |
| 🎞 New Format | IMAX/4DX/3D added to a theatre |
| 🟢 Booking Open | Status changed from "Coming Soon" to "Book Tickets" |
| ❌ Show Removed | (Optional) A time slot disappeared |

**Deduplication:** Every notification is hashed and stored. The same change will never be notified twice within 24 hours.

---

## Deployment (Always-On)

### Fly.io (Recommended Free Option)

```bash
fly launch --no-deploy
fly secrets set TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy ENABLED_NOTIFIERS=telegram
fly deploy
```

### Oracle Cloud Always Free VPS

1. Create a free ARM VM instance
2. Install Docker
3. Clone repo, edit `.env`
4. `docker compose up -d`

---

## Project Structure

```
movie-monitor/
├── app/
│   ├── parsers/
│   │   ├── base.py          # Abstract base parser
│   │   ├── bms.py           # BookMyShow parser (XHR + DOM fallback)
│   │   └── district.py      # District parser (XHR + DOM fallback)
│   ├── notifier/
│   │   ├── base.py          # Abstract base notifier
│   │   ├── telegram.py      # Telegram Bot API
│   │   ├── discord.py       # Discord Webhook
│   │   ├── whatsapp.py      # Twilio WhatsApp
│   │   ├── email_notifier.py # Async SMTP
│   │   └── dispatcher.py    # Dedup + fan-out
│   ├── static/
│   │   └── dashboard.html   # Web dashboard
│   ├── api.py               # FastAPI app + routes
│   ├── browser.py           # Playwright browser pool (stealth)
│   ├── compare.py           # Change detection engine
│   ├── config.py            # Pydantic settings
│   ├── database.py          # Async SQLite layer
│   ├── models.py            # All Pydantic models
│   ├── retry.py             # Exponential backoff decorator
│   └── scheduler.py        # APScheduler + scan logic
├── tests/
│   ├── test_compare.py      # Change detection unit tests
│   └── test_notifier.py     # Formatter unit tests
├── config/
│   └── movies.json.example
├── .env.example
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

---

## Notes on Scraping

Both BookMyShow and District are JavaScript-heavy SPAs with anti-bot protections.

ShowPulser uses two strategies per source:

1. **XHR Interception (primary)** — Playwright intercepts the site's own internal API calls and parses the JSON directly. This is much more stable than DOM parsing.
2. **DOM Scraping (fallback)** — BeautifulSoup parses the rendered HTML if no API responses are captured.

The parsers (`app/parsers/bms.py` and `app/parsers/district.py`) are fully isolated. If a site changes its structure, only one file needs updating.

> ⚠️ **Personal use only.** Web scraping may conflict with the ToS of BookMyShow and District. This tool is intended for personal monitoring of public show data for a specific movie.
