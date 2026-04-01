# Polymarket Copy-Bot

An automated copy-trading bot for [Polymarket](https://polymarket.com) that mirrors the trades of hand-picked high-performing specialists. Built with Python, Streamlit, and Web3.

> **Status**: Research / paper-trading. The bot detects real positions and records them locally, but live order execution is not yet wired up. It's fully functional as a paper-trading simulator and strategy sandbox.

---

## Features

- **Specialist copy-trading** — monitor multiple wallet addresses and automatically replicate their positions
- **Dynamic position sizing** — graduated Kelly-style bet percentages that taper as the bankroll grows
- **Win-rate health monitor** — specialists with falling win rates are put on probation and skipped
- **Adaptive value caps** — reject entries above a configurable max price (e.g. 0.82 for sports, 0.75 for politics)
- **No-chase slippage guard** — skip any trade where the current price has drifted more than X% from the specialist's entry
- **2× harvest rule** — when the wallet doubles, sweep half the profit to a separate wallet automatically
- **Monte Carlo backtest** — simulate strategy performance over hundreds of runs with tunable parameters
- **Historical backtest** — replay actual Polymarket activity data for each specialist
- **Streamlit dashboard** — live trade log, specialist roster, balance charts, settings UI
- **Telegram alerts** — trade confirmations, resolutions, hourly summaries, error notifications
- **Fully configurable via UI** — every algorithm parameter is editable from the Settings page without touching code

---

## Screenshots

_Screenshots coming soon — see the [`docs/`](docs/) folder._

---

## How it Works

```
Polymarket Data API
      │
      ▼
 Bot polls each specialist wallet every N seconds
      │
      ├─► New position detected?
      │         │
      │         ├─► Health checks (win rate, value cap, slippage, liquidity)
      │         │
      │         └─► PASS → record trade, send Telegram alert
      │
      └─► Pending trade resolved? → update result, send alert
```

The bot never holds positions itself — in paper-trading mode it records them to a local SQLite database. Live execution would be added by wiring in the Polymarket CLOB API signing logic.

---

## Specialist Tiers

| Tier | Strategy | Default Bet % | Min Win Rate |
|------|----------|--------------|--------------|
| **SHARP** | Volume grinders, 55%+ win rate, hundreds of picks | 5% / 3% / 1.5% (by bankroll) | 55% |
| **WHALE** | Swing traders, high-conviction long shots | 3% / 2% / 1% (by bankroll) | 40% |

Bet percentages taper automatically as the bankroll grows to prevent oversized positions.

---

## Algorithm Parameters

All parameters are tunable from the **Settings** page in the dashboard — no code edits needed.

| Parameter | Default | Description |
|-----------|---------|-------------|
| SHARP bet % (< $200) | 5% | Bet size for SHARP specialists when balance is small |
| SHARP bet % ($200–$999) | 3% | Mid-tier bankroll sizing |
| SHARP bet % (≥ $1000) | 1.5% | High-bankroll sizing |
| WHALE bet % (< $200) | 3% | WHALE small bankroll |
| WHALE bet % ($200–$999) | 2% | WHALE mid bankroll |
| WHALE bet % (≥ $1000) | 1% | WHALE large bankroll |
| Win rate multiplier | win_rate / 50 | Scales bet size by specialist performance |
| SHARP min win rate | 55% | Below this → probation |
| WHALE min win rate | 40% | Below this → probation |
| Value cap — Sports | 0.82 | Max entry price for sports markets |
| Value cap — Politics | 0.75 | Max entry price for politics/elections |
| Slippage threshold | 2.5% | Max price drift from specialist's entry before skipping |
| Liquidity multiple | 2× | Required order book depth vs bet size |
| Harvest trigger | 2× baseline | When to sweep profits |
| Harvest transfer | 50% | % of profit to send to main wallet |
| Min wallet buffer | $5 | Always keep this much in reserve |
| Max days — Sports | 60 days | Skip markets expiring too far out |
| Max days — Non-sports | 90 days | |
| Poll interval | 30 s | Seconds between API checks |
| Enable tag filter | Off | Strict domain enforcement per specialist |

---

## Setup

### Prerequisites

- Python 3.10+
- A dedicated Polygon wallet (separate from your main wallet — never use your main wallet)
- (Optional) Alchemy API key for on-chain balance queries
- (Optional) Telegram bot token for alerts

### Local Development

```bash
git clone https://github.com/YOUR_USERNAME/polymarket-picks.git
cd polymarket-picks

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your values

streamlit run app.py            # Dashboard only
# python bot.py                 # Bot only (headless)
```

### Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```env
# Required for live balance display
ALCHEMY_POLYGON_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY
BOT_WALLET_ADDRESS=0xYOUR_BOT_WALLET_PUBLIC_ADDRESS

# Required for live trading (when CLOB execution is wired up)
BOT_PRIVATE_KEY=0xYOUR_BOT_WALLET_PRIVATE_KEY
HARVEST_WALLET_ADDRESS=0xYOUR_PERSONAL_WALLET

# Optional — Telegram notifications
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional — disable Telegram without touching the DB
ENABLE_TELEGRAM=true
```

### Cloud Deployment (Render / Railway)

1. Push to GitHub
2. Create a new Web Service, connect the repo
3. Set environment variables in the platform dashboard
4. The `Dockerfile` exposes port `8501` (Streamlit) and runs `bot.py` alongside it
5. Any `git push` to `main` triggers an automatic redeploy

---

## Project Structure

```
polymarket-picks/
├── app.py            # Streamlit dashboard (all pages)
├── bot.py            # Main polling loop and trade logic
├── database.py       # SQLite wrapper (trades, specialists, config)
├── finance.py        # Position sizing, harvest, value caps, slippage math
├── ws_listener.py    # WebSocket listener for real-time price monitoring
├── requirements.txt
├── Dockerfile
├── .env.example
└── docs/             # Screenshots and supporting docs
```

---

## Adding Specialists

From the **Dashboard → Specialist Roster**:

1. Click **Add New Trader**
2. Enter their Polymarket username and wallet address (visible on their profile URL)
3. Select the market categories they trade
4. Choose their tier (SHARP or WHALE)
5. Check the vetting box — only add traders with a verified track record

The bot will start monitoring their wallet on the next poll cycle.

---

## Backtesting

### Monte Carlo Simulator
Runs N simulations of the strategy with configurable parameters (win rate, trades/day, slippage, fees). Produces equity fan charts, percentile outcomes, ruin rates, and probability tables.

### Historical Backtest
Fetches real trade history from the Polymarket Data API for each specialist in your roster and replays it through the bot's exact filtering logic. Shows per-specialist EV analysis and overall win rate.

---

## Contributing

Pull requests are welcome. For major changes, open an issue first to discuss.

Key areas where contributions would be useful:
- CLOB order execution (signing and submitting actual orders)
- Conviction sizing based on specialist's relative bet size
- Additional alert channels (Discord, email)
- Position exit logic (take-profit triggers)

---

## Disclaimer

This software is for educational and research purposes. Prediction market trading involves substantial risk of loss. Past performance of any specialist wallet is not indicative of future results. Use at your own risk with money you can afford to lose entirely.
