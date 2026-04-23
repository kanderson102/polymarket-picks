# 📈 Polymarket Bots: Strategy & SOP

Source of truth for the two bots' financial logic, risk rules, and vetting workflow. Read before touching `finance.py`, `bot.py`, `no_bot/`, or the Settings page.

---

## 0. Two-Bot Overview

Two independent strategies sharing one bankroll and one database (`trading.db`).

| | **Copy-Bot** (`bot.py`) | **No-Bot** (`no_bot/`) |
|---|---|---|
| **Thesis** | Mirror vetted specialist wallets on trades within their proven domain. | "Nothing Ever Happens": 73% of Polymarket binary-matchup markets resolve No. |
| **Entry signal** | Specialist opens a new position (via REST poll + WebSocket). | Scanner finds an open single-market event in an enabled category, No ask ≤ ceiling. |
| **Markets** | Whatever the specialist trades (binary or multi-leg). | **Binary matchups only** — events with exactly one market. Brackets are skipped. |
| **Categories** | Per-specialist tag filter. | Only Tech-AI / Sports-Other / Politics (the three with ≥60 samples and meaningful margin over breakeven). |
| **Sizing** | % of wallet balance, graduated by balance tier & tier (SHARP/WHALE). | Fractional Kelly per category, capped at `nb_max_bet_pct` of bankroll. Small-bankroll mode flips to flat $5 bets when bankroll < $250. |
| **Go-live gate** | Specialist toggles on **Specialists** tab + `COPY_BOT_LIVE=true`. | `nb_live_mode` toggle on **Settings → No-Bot** (executor is a TODO — paper-only today). |
| **Configurable from UI** | **Settings → Copy-Bot** | **Settings → No-Bot** |
| **Live positions** | **Dashboard** → Live Activity Log | **Dashboard** → No-Bot Live Positions |
| **Backtest** | **Copy-Bot Backtest** tab | **No-Bot Backtest** tab |

### Shared infrastructure

- **Telegram**: master switch + per-notification toggles on **Settings → System**. Defaults: buy / resolve / error = ON; hourly summary and skip messages = OFF.
- **Database**: `trading.db` (`trades` table for copy-bot, `no_positions` for no-bot, `bot_config` for UI-editable settings).
- **Historical data**: `backtest/markets.db` — 55MB snapshot of resolved markets, gitignored.

### Small-bankroll operating mode ($50 start)

At $50 bankroll, Kelly-sized bets round to well under Polymarket's $5 minimum, so `nb_small_bankroll=1` flips sizing to a flat $5 per entry. That's 10% of bankroll — aggressive by design; the alternative is zero trades. Fast-turnover mode (default ON) ranks candidates so fast-resolving categories (Sports-Other ≈12d, Politics ≈33d) fill before slow ones (Tech-AI ≈75d), recycling capital faster. Once bankroll > $250, flip `nb_small_bankroll=0` and Kelly sizing takes over.

---

## 1. Copy-Bot — Trader Tiers & Bet Sizing

All copied traders are classified into one of two tiers. Tier determines the base bet percentage and minimum win rate threshold.

### SHARP Tier — Consistent Grinders
Quant-style traders with high trade volume and tight, data-driven win rates.

| Balance Range | Base Bet % |
|---------------|-----------|
| < $200 | 5% |
| $200 – $999 | 3% |
| ≥ $1,000 | 1.5% |

- **Minimum Win Rate:** 55% (configurable in Settings)
- **Target profile:** 500+ lifetime positions, steady upward equity curve, win rate between 55–65%

### WHALE Tier — High-Variance Specialists
Traders operating at price extremes — either deep underdogs or near-certain outcomes.

| Balance Range | Base Bet % |
|---------------|-----------|
| < $200 | 3% |
| $200 – $999 | 2% |
| ≥ $1,000 | 1% |

- **Minimum Win Rate:** 40% (configurable in Settings — accounts for long-shot math)
- **Target profile:** Traders betting sub-0.20 or over-0.80 consistently with positive EV

### Dynamic Scaling (Win Rate Multiplier)
`finance.py → calculate_bet_size()`

Bet size is scaled by a live win rate multiplier: `actual_win_rate / 50`. A specialist with a 75% lifetime win rate gets a 1.5× bet multiplier. Traders with fewer than 5 resolved trades default to a 1.0× multiplier (neutral — no outsized bets on unproven history).

> All bet percentages and thresholds are configurable from the **Settings** page — no code changes required.

---

## 2. Risk Guardrails

### Slippage Guard (No-Chase Rule)
The bot compares the specialist's entry price (`avgPrice`) against the current CLOB best ask. If the market has moved more than **2.5%** above the specialist's price, the bot logs a `TEMPORARY_REJECT` and skips the trade rather than chasing. Configurable via `slippage_threshold_pct` in Settings.

### Value Caps by Category
To prevent overpaying on near-certain outcomes:

| Category | Max Entry Price |
|----------|----------------|
| Sports | 0.82 |
| Politics | 0.75 |

Configurable via `value_cap_sports` and `value_cap_politics` in Settings. Markets priced above these thresholds are skipped.

### Date Filter (Liquidity Protection)
Prevents capital from being locked in long-duration markets:

| Category | Max Days to Close |
|----------|------------------|
| Sports (NBA, Soccer, MLB, NHL, etc.) | 60 days |
| Everything else | 90 days |

Configurable via `max_days_sports` and `max_days_default` in Settings.

### Collision Detection
Before placing any trade, the bot scans for existing `PENDING` positions in the same market. Duplicate or opposing positions are aborted immediately.

### Order Book Depth Check
The bot checks CLOB liquidity before executing. If the top 3 price levels don't cover at least **2× the bet size**, the trade is skipped. Configurable via `liquidity_multiple` in Settings.

### Win Rate Bootstrapping
New traders with fewer than 5 resolved trades are treated as 50% win rate (1.0× multiplier). The bot does not make outsized bets on unproven specialists.

---

## 3. Trade Detection Architecture

### Primary: WebSocket Listener (`ws_listener.py`)
- Connects to `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- Sub-second latency for detecting specialist trades
- Auto-reconnects with exponential backoff (5s → 10s → 20s...)
- Circuit breaker: after 50 rapid reconnect loops, backs off to 5-minute intervals
- Resets reconnect counter after 30+ seconds of stable connection
- Sends Telegram alert after 5 consecutive failed reconnection attempts

### Fallback: HTTP Polling
- Polls the Polymarket Data API every 30 seconds (configurable via `poll_interval` in Settings)
- Catches any trades missed during WebSocket gaps
- Also handles auto-resolution checks each cycle

### Tag Matching
The bot cross-references the Gamma API (`/events?slug=X`) to get actual market tags for each trade. If the market's tags don't match the specialist's allowed categories, the trade is rejected with a `TAG MISMATCH` log.

### Market Auto-Resolution
Each polling cycle, the bot checks all `PENDING` trades against the Gamma API. Resolved markets are marked `WON` or `LOST` with P&L calculated and a Telegram notification sent.

---

## 4. Harvest Logic

When the wallet balance hits **2×** the baseline (configurable via `harvest_trigger_multiplier`), the bot flags a harvest event. **50%** of profits above baseline are earmarked for transfer to the harvest wallet (configurable via `harvest_transfer_pct`). A minimum buffer (`min_wallet_buffer`, default $5) is always maintained so the bot never runs dry.

> Note: In the current paper-trading phase, harvest events are logged and Telegram-alerted but no on-chain transfer is triggered automatically.

---

## 5. Polymarket Fee Schedule

Polymarket uses a maker-taker model. As a taker, fees are dynamic based on share price — peaking around mid-market and tapering to zero near 0¢/100¢.

| Category | Peak Fee Rate |
|----------|--------------|
| Sports | ~0.75% |
| Politics | ~1.00% |
| Geopolitical | 0% (fee-free) |

At Phase 1 bet sizes ($1–3), fees are approximately $0.01–0.03 per trade.

---

## 6. Specialist Vetting SOP

### Step 1: Find Candidates
- Use [polymarketanalytics.com](https://polymarketanalytics.com) or [polytrack.net](https://polytrack.net)
- Sort by **30-Day PnL** or **Win Rate** — not all-time PnL (dominated by one-hit-wonder arbers)
- Look for traders with a steady upward equity curve, not a single spike

### Step 2: Category Verification (Critical)
Never add a trader based on global PnL alone.
1. Open their profile and filter by the specific category you want to copy (Sports, Politics, etc.)
2. Do they have a verified >55% win curve **in that category specifically**?
3. Confirm via API: `https://data-api.polymarket.com/positions?user={wallet}`

### Step 3: Get Their Wallet Address
- On Polymarket Analytics: click "Copy Address" next to their username
- On Polymarket native: check the URL or profile modal for their `0x...` address
- Address must be exactly 42 characters (0x + 40 hex). Truncated addresses fail silently.

### Step 4: Add via Dashboard
1. Open the Streamlit Dashboard
2. Click **➕ Add New Trader** in the Specialists section
3. Paste their Name and `0x...` wallet address
4. Select only the categories they passed verification for
5. Select `SHARP` or `WHALE` based on the criteria above
6. Check the vetting acknowledgement and click Add — the bot picks them up on the next polling cycle

---

## 7. Current Specialist Roster (Last Verified: March 2026)

| Trader | Tier | Domain Tags | Notes |
|--------|------|-------------|-------|
| S-Works | SHARP | Soccer, UCL, NBA | Generalist, ~75% Soccer |
| reachingthesky | SHARP | Soccer, UCL | Top-3 Sports monthly |
| HorizonSplendidView | SHARP | Soccer, UCL | Top-3 Sports monthly |
| CemeterySun | SHARP | NBA, Soccer, NHL | High volume, 100+ positions |
| LlamaEnjoyer | WHALE | Pop Culture | Novelty markets |
| beachboy4 | SHARP | NBA, Soccer, UCL | #1 Sports monthly |
| CERTuo | SHARP | NHL | 86% NHL specialist |
| majorexploiter | SHARP | Soccer, UCL | EPL specialist |
