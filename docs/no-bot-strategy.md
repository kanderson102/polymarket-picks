# No-Bot Strategy — "Nothing Ever Happens"

Parallel bot to the copy-bot. Buys **No** on a narrow slice of Polymarket binary matchups where the empirical base rate of No resolution reliably exceeds the market's No price.

## Thesis

1. Retail traders systematically overprice Yes on "Will X happen by date Y?" markets — deadlines outrun real-world event velocity.
2. For true binary questions (events containing a single market), the No base rate is measurable and stable: 70–77% across the categories we trade.
3. Buying No below that base rate gives a positive-EV bet.

## Scope: binary matchups only

The bot **only enters markets whose parent event contains exactly one market.** A bracket or multi-candidate event (e.g. "Who wins Worlds?" with 16 teams as 16 markets) has per-candidate prices arbitraged so their Yes probabilities sum to ~1.0. Any candidate priced cheap enough to cross our ceiling is the market's favorite — the base rate of No flips against us. There is no tradable edge there.

This filter is enforced in [`no_bot/scanner.py`](../no_bot/scanner.py): `if len(event["markets"]) != 1: continue`.

## Category config

Base rates measured on single-market events only, volume ≥ $5k, earliest available data through present.

| Category      | No Rate | Samples | Ceiling | Kelly | EV @ ceiling |
|---------------|---------|---------|---------|-------|--------------|
| Tech-AI       | 77.0%   | 87      | 0.60    | 20%   | +0.42 per $1 |
| Politics      | 70.5%   | 3,157   | 0.55    | 15%   | +0.41 per $1 |
| Sports-Other  | 70.1%   | 261     | 0.55    | 15%   | +0.41 per $1 |

### Time horizons (start → resolution, single-market binary matchups)

| Category      | p25   | Median | Mean  | p75    | Implied cycles/yr per slot |
|---------------|-------|--------|-------|--------|----------------------------|
| Sports-Other  | 3d    | 12d    | 36d   | 33d    | ~30                        |
| Politics      | 10d   | 33d    | 65d   | 85d    | ~11                        |
| Tech-AI       | 25d   | 75d    | 104d  | 140d   | ~5                         |

Sports-Other turns over fast (weekly averages of single-game or match-level questions). Politics is mixed between short-horizon news questions and longer election/policy deadlines. Tech-AI skews to long-dated "by end of year" deadline markets — expect capital to sit for 2–3 months per position. Bankroll sizing and concurrency limits need to accommodate the slow-rolling Tech-AI slots or they'll clog.

**Everything else is excluded.** Reasons, in brief:

| Category           | Why excluded |
|--------------------|--------------|
| Sports-Soccer      | 42.7% No rate — Yes is the base case (draws + favorites) |
| Sports-Esports     | 37.7% No rate in binary matchups |
| Sports-Basketball  | 62.0% — too close to breakeven at any reachable ceiling |
| Sports-Baseball    | 54.8% — same |
| Sports-Hockey      | Insufficient single-market samples (mostly bracketed) |
| Economics          | Insufficient single-market samples |
| Crypto             | Volatile pricing; entry slippage dominates edge |
| Recurring / UpOrDown | 50/50 by design |

## Sizing

Fractional Kelly with hard caps:

- Per-bet: `min(kelly_bet, 5% of bankroll)`, floor at $5 (Polymarket minimum)
- Per-category: no more than 40% of deployed capital in one category
- Global: halt new entries at −30% drawdown from starting capital

## Expected returns

At ~$500 starting capital, with the binary-matchup filter in place:

- Qualifying bets ≈ 150–300 per year (the filter rejects most of Polymarket)
- Per-bet EV ≈ 25–40% of stake at ceiling prices, less as price approaches breakeven
- Annualized ROI estimates require live price-series data we don't have yet; the historical simulation (`python backtest/deep_analysis.py`) gives a directional upper bound

## Risks

1. **2026 efficiency regression** — recent data shows 10–15pp lower No rates in some categories than 2025. Config uses the full-history rate; revisit quarterly.
2. **Selection bias** — we only enter markets where No was cheap enough. Those markets disproportionately had Yes-sentiment spikes; realized edge will be below nominal.
3. **Liquidity** — lifetime volume doesn't guarantee live order-book depth. Executor must check `getBook` before placing.
4. **Fee model** — parabolic taker fee peaking at 50¢ (0.75–1.0% of stake), matching [`finance.estimate_taker_fee`](../finance.py). Gas on Polygon is ~$0.0015/tx, immaterial above $1 bets.

## Entry timing

Baseline: enter at first observation where No ≤ ceiling. Refinement via WebSocket: watch the No price stream for 1–3 hours, compute a 30-minute rolling median, and enter on a 5–10% dip below median (Yes-sentiment pump that's about to revert). Fall back to naive entry 24h before resolution if no dip appears. See [no-bot-architecture.md](no-bot-architecture.md) for the signal pipeline.
