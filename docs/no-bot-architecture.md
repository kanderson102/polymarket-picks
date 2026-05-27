# No-Bot Architecture

The No-bot runs alongside the existing copy-bot. Shared infrastructure (API clients, DB, fee math, Telegram alerts), separate strategy logic and tables.

## Target layout (after modularization)

```
polymarket-picks/
├── shared/                    # cross-bot code
│   ├── __init__.py
│   ├── gamma_api.py           # Gamma events/markets fetch (extracted from bot.py)
│   ├── clob_api.py            # CLOB order placement (extracted from bot.py)
│   ├── data_api.py            # Data API trade feed
│   ├── fees.py                # estimate_taker_fee, slippage math (from finance.py)
│   ├── categories.py          # tag → category map (from fetch_markets.py + bot.py)
│   ├── db.py                  # base DB connection + migrations
│   └── telegram.py            # Telegram alert sender
│
├── copy_bot/
│   ├── __init__.py
│   ├── __main__.py            # entrypoint: python -m copy_bot
│   ├── loop.py                # main polling loop (from bot.py)
│   ├── trades.py              # trade/resolve logic
│   ├── ws_listener.py         # existing WebSocket
│   └── db.py                  # copy_trades, specialists, balance_history
│
├── no_bot/
│   ├── __init__.py
│   ├── __main__.py            # entrypoint: python -m no_bot
│   ├── config.py              # CATEGORY_CONFIG, MIN_VOLUME_USD, caps
│   ├── scanner.py             # Gamma scan — binary matchups only (single-market events)
│   ├── ws_entry.py            # WebSocket price-dip detector
│   ├── sizer.py               # Kelly + per-event cap
│   ├── executor.py            # place No order via CLOB
│   ├── resolver.py            # check resolutions, book P&L
│   ├── loop.py                # ties scanner + ws + executor + resolver
│   └── db.py                  # no_trades, no_positions tables
│
├── backtest/                  # unchanged
├── streamlit_app.py                     # dashboard (adds Backtest + No-bot tabs)
├── trading.db                 # shared SQLite (copy-bot tables + no-bot tables)
└── docs/
    ├── no-bot-strategy.md
    ├── no-bot-architecture.md  # (this file)
    └── no-bot-runbook.md
```

## Data flow

```
        ┌────────────────────────┐
        │  Gamma /events scan    │  (every 5 min)
        │  no_bot/scanner.py     │
        │  FILTER: single-market │
        │  events only; category │
        │  in CATEGORY_CONFIG    │
        └──────────┬─────────────┘
                   │ eligible markets
                   ▼
        ┌────────────────────────┐     ┌──────────────────────┐
        │  WebSocket price feed  │◀────│  CLOB market.getBook │
        │  no_bot/ws_entry.py    │     │  (fallback poll)     │
        └──────────┬─────────────┘     └──────────────────────┘
                   │ price dip trigger
                   ▼
        ┌────────────────────────┐
        │  Sizer: Kelly, 5% cap, │
        │  40% category cap      │
        │  no_bot/sizer.py       │
        └──────────┬─────────────┘
                   │ bet size
                   ▼
        ┌────────────────────────┐
        │  Executor: place CLOB  │
        │  No order, record DB   │
        │  no_bot/executor.py    │
        └──────────┬─────────────┘
                   │ open position
                   ▼
        ┌────────────────────────┐
        │  Resolver (every 10m)  │
        │  marks positions, P&L  │
        │  no_bot/resolver.py    │
        └────────────────────────┘
```

## DB schema additions (in `trading.db`)

```sql
CREATE TABLE no_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id       TEXT NOT NULL,
    event_id        TEXT,
    question        TEXT,
    category        TEXT,
    entry_no_price  REAL,
    bet_size_usd    REAL,
    fee_paid_usd    REAL,
    placed_at       TEXT,
    resolved_at     TEXT,
    resolved_yes    INTEGER,           -- NULL until resolution
    pnl_usd         REAL,
    status          TEXT,              -- 'open' | 'won' | 'lost' | 'voided'
    mock            INTEGER DEFAULT 1  -- 1=paper trade, 0=real
);

CREATE INDEX idx_no_pos_status  ON no_positions(status);
CREATE INDEX idx_no_pos_event   ON no_positions(event_id);
CREATE INDEX idx_no_pos_market  ON no_positions(market_id);
```

## WebSocket entry signal

Naive baseline: enter at first observation where No ≤ ceiling. This is fine if sentiment doesn't spike upward before close.

Refinement: watch the No price stream for 1–3 hours, compute a 30-minute rolling median, and enter when No dips ≥ 5% below that median (a Yes-sentiment pump that's about to revert). This typically happens around news blips. Fall back to naive entry at T-24h to resolution if no dip appears.

Signal source: Polymarket WebSocket `market` channel (already wired in `ws_listener.py` for copy-bot). Subscribe per-market as they become eligible; unsubscribe on entry or disqualification.

## Safety rails

- **Paper mode by default** — `NO_BOT_LIVE=false` in env gates real order placement. `mock=1` flag on every position row.
- **Global drawdown halt** — if no-bot P&L hits −30% of starting capital, stop taking new positions until manual resume.
- **Per-category exposure cap** — no more than 40% of deployed capital in one category at once.
- **Telegram on entry + resolution** — reuse existing alert infra.

## Dashboard tab (in `streamlit_app.py`)

New tab `"No-Bot"` with:
- **Live positions** table (open, won, lost)
- **P&L curve** (starting capital → equity over time)
- **Category exposure** pie
- **Backtest explorer**: sliders for entry price, min_volume, starting_capital; re-runs `backtest.deep_analysis.simulate` on the fly and shows the 6 charts.

## Revival checklist for old copy-bot server

1. SSH to Hetzner VPS, `cd` to repo, `git pull`
2. `.venv/bin/pip install -r requirements.txt`
3. Verify `.env` has wallet creds + `COPY_BOT_LIVE` / `NO_BOT_LIVE` flags
4. Restart Docker: `docker compose down && docker compose up -d`
5. Tail logs: `docker compose logs -f` — expect both bots to boot cleanly
6. Dashboard at `http://<vps-ip>:8501`
