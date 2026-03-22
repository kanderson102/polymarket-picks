# 📈 Polymarket Copy-Bot: Master Strategy & SOP

This document is the "source of truth" for the Polymarket Copy-Bot's custom financial logic and tracking mechanisms. Any future AI agent or developer jumping into this project should read this document directly to understand how the bot scales, defends against risk, and categorizes traders.

---

## 1. Categorization & Sizing (The Fractional Kelly Model)

Applying a flat 5% bet size across the board is a guaranteed way to bleed capital. The bot solves this by segregating traders into two distinct Tiers:

### A. The SHARP Tier (Grinders)
These are data-driven quants. They aim for consistent profitability over thousands of trades.
*   **Base Allocation:** `1%` of the total portfolio.
*   **Minimum Win Rate:** `55%`. (If they drop below this, they are instantly placed on Probation and skipped).
*   **Identification:** Look for traders with >500 positions placed, an equity curve that steadily marches up-and-to-the-right over time, and win rates rigidly locked between 55% - 65%.

### B. The WHALE Tier (Yield Farmers / High-Upside / Long-shots)
Whales fall into two extremes: 
1. The **Long-Shot Hunter** (bets $0.10 to win $1.00 on massive underdogs).
2. The **Clear-Win Farmer** (bets $0.90 to win $1.00 on near-guaranteed outcomes). 
Both have extreme variance. If a Long-Shot Hunter hits 40% of their trades, they are massively profitable. If a Clear-Win Farmer hits 90%, they are barely profitable.
*   **Base Allocation:** `2%` of the total portfolio. (Small enough to survive the Long-Shot's losing streaks, but large enough to generate profits that clear Polygon Gas Fees for the Clear-Win Farmer).
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

---

## 3. Discovery & Vetting Protocol (SOP for the User & Future AI)

Finding *net-new* traders requires manual discovery. This is the exact step-by-step workflow:

**Step 1: Finding Talent on Analytical platforms (Polymarket Analytics or Native Polymarket Leaderboards)**
1. Navigate to Polymarket's native Leaderboard, or `polymarketanalytics.com` / `polytrack.net`. 
2. Change the sorting filter from "All-Time PnL" to **"30-Day PnL"** or **"Win Rate"**. (All-Time PnL is usually dominated by one-hit-wonder Crypto arbers).
3. If using Polymarket Analytics, look for the **Window Consistency Score**. You want traders with positive, steady window consistency, not a single massive spike on their chart.

**Step 2: Category Verification (CRITICAL)**
*Never* add a trader strictly because of their global PnL. 
1. Open the prospect's profile.
2. Filter their history or tags specifically by the Category you want to track (e.g., filter their positions exclusively to "Sports" or "Pop Culture").
3. Do they have a proven `>55%` win curve purely in that category? If they make $5M in Crypto but are negative in Sports, **DO NOT** assign them a Sports tag on your dashboard.

**Step 3: Getting the Polymarket Address vs Proxy Address**
*   **Why did the AI mention Tracker sites for addresses?** On Polymarket Analytics, you can easily just click "Copy Address" next to a username to get their exact `0x` string. 
*   **Can you get it from Polymarket native?** Yes! If you click on a user's name on Polymarket (e.g., `polymarket.com/@Sharky6999`), look at the URL or their profile modal. It will display their `0x...` wallet address. Copy that.

**Step 4: Database Injection**
Once vetted:
1. Go to your Streamlit Dashboard.
2. Click **➕ Add New Trader**.
3. Paste their Name and `0x...` Wallet Address.
4. **Use the Dropdown Menu** to select ONLY the specific Sports/Categories they passed verification for.
5. Select `SHARP` or `WHALE` based on the definitions above.
6. Check the Vetting Acknowledgement box and hit Add! The bot will instantly pick them up.
