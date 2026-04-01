# 🏛️ Polymarket Copy-Bot: Architecture & Deployment

This document covers the system architecture, file structure, and deployment workflow.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Local Mac (Development)                                        │
│  ┌──────────┐  ┌──────────┐  ┌─────────────┐  ┌───────────┐  │
│  │  VS Code  │  │  app.py  │  │   bot.py    │  │ trading.db│  │
│  │  Editor   │  │Streamlit │  │  Bot Daemon │  │  SQLite   │  │
│  └──────────┘  └──────────┘  └─────────────┘  └───────────┘  │
│         │                                                       │
│         └──────────── git push ──────────────────────────▶     │
└─────────────────────────────────────────────────────────────────┘
                                    │
                          GitHub Repository
                                    │
                       GitHub Actions (deploy.yml)
                          triggers on push to main
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Hetzner VPS (Production)                                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Docker Container                                        │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │  │
│  │  │  app.py  │  │  bot.py  │  │ws_listen │  │  .env  │  │  │
│  │  │Streamlit │  │  Daemon  │  │  er.py   │  │ (keys) │  │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘  │  │
│  │              ↕ shared trading.db                        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                          │                │
                  Polymarket APIs      Telegram
               (Gamma + CLOB + Data)    Alerts
```

---

## Core Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit dashboard — all UI, charts, settings, controls |
| `bot.py` | Main bot daemon — polling loop, trade logic, order execution |
| `ws_listener.py` | WebSocket listener for real-time trade detection |
| `database.py` | SQLite ORM — specialists, trades, config, heartbeat |
| `finance.py` | Bet sizing, harvest logic, slippage/value/liquidity checks |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container definition for production |
| `docker-compose.yml` | Orchestrates app + bot services |
| `.env` | Secrets (never committed — see `.env.example`) |
| `.env.example` | Template for all required environment variables |

---

## Data Layer: SQLite (`trading.db`)

Four tables drive the system:

- **`specialists`** — tracked traders (name, wallet, tier, tags, win rate, status)
- **`trades`** — all trade records (pending, won, lost) with full price/size data
- **`bot_config`** — key-value store for all algorithm parameters (editable via Settings UI)
- **`bot_heartbeat`** — single-row table updated every poll cycle; used by the dashboard to display bot status

### Algorithm Configuration
All financial parameters live in `bot_config` and are editable from the **Settings** page in the dashboard — no code changes or server restarts required. Changes take effect on the next polling cycle. See `strategy.md` for the full parameter reference.

---

## Deployment Pipeline

### Automated (GitHub Actions)
Every push to `main` triggers `.github/workflows/deploy.yml`:
1. GitHub Actions SSH into the Hetzner server (credentials stored as GitHub Secrets — never hardcoded)
2. `git pull` fetches the latest code
3. Docker rebuilds and restarts the container

### Manual Server Access
SSH in directly for troubleshooting:
```bash
ssh user@your-hetzner-ip
cd ~/polymarket-picks
docker compose logs -f        # tail live logs
docker compose restart        # force restart
```

### Environment Variables (Production)
All secrets live in `.env` on the Hetzner server only. To update:
```bash
ssh user@your-hetzner-ip
nano ~/polymarket-picks/.env
docker compose restart
```

Never commit `.env`. Use `.env.example` as the template.

---

## Local Development Setup

```bash
# Clone and set up
git clone https://github.com/YOUR_USERNAME/polymarket-picks.git
cd polymarket-picks
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in your values

# Run the dashboard only (no live trading)
streamlit run app.py

# Run the full bot (paper trading by default)
python bot.py
```

> **Important:** Local and production environments are completely isolated. Your local `trading.db` is separate from the server's live database. Never point your local bot at the production database.

---

## Current Status: Paper Trading (Phase 1)

The bot is in **paper trading mode**. Trade logic, bet sizing, slippage checks, and auto-resolution all run as normal, but no real CLOB orders are submitted. Trades are recorded in the database as `MOCK_*` entries.

When you're ready to go live:
1. Add real specialist wallet addresses via the dashboard **Add New Trader** form (replaces any `MOCK_*` placeholders)
2. Set `BOT_PRIVATE_KEY` and `ALCHEMY_POLYGON_URL` in your `.env`
3. Enable live order execution in `bot.py` (the CLOB client is wired but gated behind the mock flag)
4. Deploy to Hetzner via `git push origin main`

---

## Adding or Updating Specialists

Specialists are managed entirely through the **Streamlit Dashboard** — no database migrations or code edits needed:

- **Add**: Click **➕ Add New Trader**, fill in name, wallet address, tier, and category tags
- **Update**: Edit win rate, status, or tags directly in the Specialists table
- **Remove**: Set status to `INACTIVE` — the bot skips inactive specialists automatically

Changes persist to `trading.db` immediately and are picked up on the next polling cycle.
