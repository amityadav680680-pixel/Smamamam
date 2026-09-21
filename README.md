# Remote SMS Monitor Bot

Forward SMS from **your own Android phone** to a small FastAPI server, then read
and search them from a **Telegram bot**.

> Use only on devices you own / are authorized to monitor. Unauthorized access
> to someone else's messages is illegal.

## Architecture

```
Android (SMS Forwarder / Tasker)
        │  HTTPS POST /webhook/sms
        ▼
FastAPI + SQLite
        │  push + commands
        ▼
Telegram bot (/latest, /search, …)
```

## Quick start

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure `.env`

| Variable | Purpose |
|----------|---------|
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_ALLOWED_USER_IDS` | Your Telegram user id (get from `@userinfobot`) |
| `WEBHOOK_API_KEY` | Secret key Android must send |
| `ADMIN_API_KEY` | Secret for `/api/sms` REST access |
| `TELEGRAM_PUSH_NEW_SMS` | `true` = instant Telegram alert on each SMS |

### 3. Run

```bash
python -m app.main
```

Server listens on `http://0.0.0.0:8000`. Open `/health` to verify.

### 4. Connect Android

See **[docs/android-setup.md](docs/android-setup.md)** — Tasker or an SMS
Forwarder app posts JSON to `/webhook/sms` with header `X-API-Key`.

### 5. Telegram commands

| Command | Action |
|---------|--------|
| `/start` | Help |
| `/latest [n]` | Last n messages (default 5) |
| `/search <text>` | Search body |
| `/from <sender>` | Filter by sender |
| `/devices` | Linked phones |
| `/stats` | Counts |

## API

### `POST /webhook/sms`

Headers: `X-API-Key: <WEBHOOK_API_KEY>` (or `Authorization: Bearer …`)

```json
{
  "sender": "+919876543210",
  "body": "Your OTP is 482910",
  "device_id": "my-android"
}
```

### `GET /api/sms?limit=20`

Headers: `X-Admin-Key: <ADMIN_API_KEY>`

### `GET /health`

Public health + counts.

## Smoke test

```bash
chmod +x scripts/test_webhook.sh
./scripts/test_webhook.sh http://127.0.0.1:8000
```

## Tests

```bash
pytest -q
```

## Deploy tip

Put the API behind HTTPS (Caddy/nginx) on a VPS, set strong keys, and point the
Android forwarder at `https://your-domain/webhook/sms`.
