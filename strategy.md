# 📈 Polymarket Copy-Bot: Master Strategy & SOP

This document is the "source of truth" for the Polymarket Copy-Bot's custom financial logic and tracking mechanisms. Any future AI agent or developer jumping into this project should read this document directly to understand how the bot scales, defends against risk, and categorizes traders.

---

## 1. Categorization & Sizing (The Fractional Kelly Model)

Applying a flat 5% bet size across the board is a guaranteed way to bleed capital. The bot solves this by segregating traders into two distinct Tiers:

### A. The SHARP Tier (Grinders)
These are data-driven quants. They aim for consistent profitability over thousands of trades.
*   **Base Allocation:** `5%` of the total portfolio (Phase 1-2). Scale to `1%` at Phase 3 ($1000+).
*   **Minimum Win Rate:** `55%`. (If they drop below this, they are instantly placed on Probation and skipped).
*   **Identification:** Look for traders with >500 positions placed, an equity curve that steadily marches up-and-to-the-right over time, and win rates rigidly locked between 55% - 65%.

### B. The WHALE Tier (Yield Farmers / High-Upside / Long-shots)
Whales fall into two extremes: 
1. The **Long-Shot Hunter** (bets $0.10 to win $1.00 on massive underdogs).
2. The **Clear-Win Farmer** (bets $0.90 to win $1.00 on near-guaranteed outcomes). 
Both have extreme variance. If a Long-Shot Hunter hits 40% of their trades, they are massively profitable. If a Clear-Win Farmer hits 90%, they are barely profitable.
*   **Base Allocation:** `3%` of the total portfolio (Phase 1-2). Scale to `2%` at Phase 3.
*   **Minimum Win Rate:** `40%`. (To accommodate Long-Shot math logic).

### 🌟 Dynamic Capital Re-Balancing
*Built into `finance.py -> calculate_bet_size()`*
If a trader logs a `75%` lifetime win rate in the database, the bot mathematically scales their future bet allocation up dynamically by `1.5x` (75/50).

---

## 2. Active Risk Guardrails

*   **The "No Chase" Limit (Slippage):** The bot calculates the exact price the target paid. If the current market price is more than **2.5%** higher, the bot triggers a `TEMPORARY_REJECT`. It puts the trade on a watch-list and waits for the price to dip back down before buying.
*   **Collision Detection:** The bot actively scans your SQL database for `PENDING` active positions. Overlapping/Opposing orders are aborted instantly.
*   **Adaptive Value Caps:** Certain categories are naturally priced higher. The bot enforces strict limits on how much it is willing to pay per share.
    *   `Tech:` Max $0.90 (Supports Clear-Win strategies natively found in Tech markets).
    *   `Pop Culture:` Max $0.60
    *   `Sports:` Max $0.65
    *   `Politics:` Max $0.55 (Due to extreme volatility and inaccurate polling).
*   **Order Book Depth Check:** Before executing any trade, the bot queries the CLOB order book to verify sufficient liquidity exists (at least 2× the bet size across top 3 price levels). This prevents slippage on larger positions.
*   **Auto-Resolution:** The bot automatically checks all PENDING trades each polling cycle against the Gamma API. When a market resolves, trades are marked WON or LOST with Telegram notifications including P&L.

---

## 3. Architecture: Trade Detection

The bot uses a **dual-layer detection system**:

### Primary: WebSocket Listener (`ws_listener.py`)
*   Connects to `wss://ws-subscriptions-clob.polymarket.com/ws/market`
*   Sub-second latency for detecting specialist trades
*   Auto-reconnects with exponential backoff (5s, 10s, 20s...)
*   Sends Telegram alert after 5 failed reconnection attempts
*   Falls back to HTTP polling when disconnected

### Fallback: HTTP Polling (30s)
*   Polls the Polymarket Data API every 30 seconds
*   Acts as safety net when WebSocket is disconnected
*   Also handles auto-resolution checks

### Tag Matching
The bot cross-references the Gamma API (`/events?slug=X`) to get real market tags instead of assuming the specialist only trades in their assigned domain. If the market's actual tags don't match the specialist's allowed tags, the trade is rejected with a `TAG MISMATCH` log.

---

## 4. Discovery & Vetting Protocol (SOP for the User & Future AI)

Finding *net-new* traders requires manual discovery. This is the exact step-by-step workflow:

**Step 1: Finding Talent on Analytical platforms (Polymarket Analytics or Native Polymarket Leaderboards)**
1. Navigate to Polymarket's native Leaderboard, or `polymarketanalytics.com` / `polytrack.net`. 
2. Change the sorting filter from "All-Time PnL" to **"30-Day PnL"** or **"Win Rate"**. (All-Time PnL is usually dominated by one-hit-wonder Crypto arbers).
3. If using Polymarket Analytics, look for the **Window Consistency Score**. You want traders with positive, steady window consistency, not a single massive spike on their chart.
4. **Filter by category** (Sports, Politics, etc.) to find domain-specific specialists.

**Step 2: Category Verification (CRITICAL)**
*Never* add a trader strictly because of their global PnL. 
1. Open the prospect's profile.
2. Filter their history or tags specifically by the Category you want to track (e.g., filter their positions exclusively to "Sports" or "Pop Culture").
3. Do they have a proven `>55%` win curve purely in that category? If they make $5M in Crypto but are negative in Sports, **DO NOT** assign them a Sports tag on your dashboard.
4. **Verify via API:** Query `https://data-api.polymarket.com/positions?user={wallet}` and categorize their actual trades to confirm.

**Step 3: Getting the Polymarket Address vs Proxy Address**
*   **Why did the AI mention Tracker sites for addresses?** On Polymarket Analytics, you can easily just click "Copy Address" next to a username to get their exact `0x` string. 
*   **Can you get it from Polymarket native?** Yes! If you click on a user's name on Polymarket (e.g., `polymarket.com/@Sharky6999`), look at the URL or their profile modal. It will display their `0x...` wallet address. Copy that.
*   **Address must be exactly 42 characters** (0x + 40 hex characters). Truncated addresses will fail silently.

**Step 4: Database Injection**
Once vetted:
1. Go to your Streamlit Dashboard.
2. Click **➕ Add New Trader**.
3. Paste their Name and `0x...` Wallet Address.
4. **Use the Dropdown Menu** to select ONLY the specific Sports/Categories they passed verification for.
5. Select `SHARP` or `WHALE` based on the definitions above.
6. Check the Vetting Acknowledgement box and hit Add! The bot will instantly pick them up.

---

## 5. Current Specialist Roster (Last Verified: March 2026)

| Trader | Tier | Domain Tags | Monthly PnL | Notes |
|--------|------|-------------|-------------|-------|
| S-Works | SHARP | Soccer, UCL, NBA | +$278K | Generalist, 75% Soccer |
| reachingthesky | SHARP | Soccer, UCL | +$3.7M | #3 Sports monthly |
| HorizonSplendidView | SHARP | Soccer, UCL | +$4.0M | #2 Sports monthly |
| CemeterySun | SHARP | NBA, Soccer, NHL | +$1.6M | #7 Sports, high volume (100+ positions) |
| LlamaEnjoyer | WHALE | Pop Culture | +$3.3K | Novelty markets (Elon, Fed rates) |
| beachboy4 | SHARP | NBA, Soccer, UCL | +$4.4M | #1 Sports monthly |
| CERTuo | SHARP | NHL | +$1.7M | 86% NHL specialist |
| majorexploiter | SHARP | Soccer, UCL | +$2.4M | #5 Sports, EPL specialist |
