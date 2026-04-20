# No-Bot Data Audit

How the category base rates in [no-bot-strategy.md](no-bot-strategy.md) were measured, and why the strategy is narrower than the meme suggests.

## Method

Source: 162k resolved Polymarket markets fetched via Gamma `/events?closed=true` (see [`backtest/fetch_markets.py`](../backtest/fetch_markets.py)). Each market is tagged with its parent event_id, category (derived from Polymarket tags), resolution (Yes/No), start/end dates, and lifetime volume.

Base rate = `SUM(resolved_yes = 0) / COUNT(*)`, computed per category on the slice that matches our trading scope.

## Binary matchups vs. multi-market events

A Polymarket *event* can contain one or many *markets*. A single-market event is a true binary question ("Will X happen by date Y?"). A multi-market event is a set of mutually-exclusive outcomes, each represented as its own binary market (e.g. "Candidate A wins: Yes/No", "Candidate B wins: Yes/No", ...).

In a multi-market event of size N, per-candidate Yes prices are arbitraged to sum to ~1. Average No price across siblings is ~(N−1)/N. Any sibling cheap enough to meet our ceiling is the event's favorite — and the base rate of No wins for favorites is dominated by the fact that in each event, exactly one sibling wins Yes.

**This is why the bot only enters single-market events.** The base rate is only measurable and meaningful on binary matchups.

## Measured rates

Categories sorted by No rate on single-market events, volume ≥ $5k:

| Category           | Samples | No Rate | Included? |
|--------------------|---------|---------|-----------|
| Crypto             | 88      | 81.8%   | No — volatility risk |
| Tech-AI            | 87      | 77.0%   | **Yes** |
| Politics           | 3,157   | 70.5%   | **Yes** |
| Sports-Other       | 261     | 70.1%   | **Yes** |
| Sports-Basketball  | 100     | 62.0%   | No — thin edge |
| Sports-Baseball    | 73      | 54.8%   | No — near 50/50 |
| Sports-Soccer      | 1,317   | 42.7%   | No — inverse bet |
| Sports-Esports     | 162     | 37.7%   | No — inverse bet |

Categories with too few single-market samples to establish a rate: Sports-Hockey, Economics, Entertainment. These almost always appear inside bracket/candidate events and are outside scope.

## Why three categories

The strategy is narrower than "buy No on everything non-sports" because:

1. The No rate has to exceed the purchase price. At ceiling 0.60, we need No to resolve ≥60% of the time. Only Tech-AI clears that comfortably. Politics and Sports-Other clear 0.55 with margin.
2. Kelly sizing requires edge, not just positive EV. Thin edges (55–62% No) give Kelly fractions so small that slippage and gas eat the return.
3. Sample size matters for confidence. Politics (n=3,157) is the anchor; Tech-AI (n=87) and Sports-Other (n=261) are supported but watched for drift.

## Time horizons

Duration from market start to resolution, measured on the same single-market slice (volume ≥ $5k):

| Category      | p25   | Median | Mean  | p75    |
|---------------|-------|--------|-------|--------|
| Sports-Other  | 3d    | 12d    | 36d   | 33d    |
| Politics      | 10d   | 33d    | 65d   | 85d    |
| Tech-AI       | 25d   | 75d    | 104d  | 140d   |

Capital lock-up is category-dependent. A Sports-Other No position recycles ~30×/year; a Tech-AI No position recycles ~5×. This matters for position sizing and concurrency limits — allocating too many slots to Tech-AI ties up the bankroll and drops effective annualized return even when per-bet EV is highest.

## 2026 efficiency regression

Year-over-year No rates on volume-filtered markets show a softening in 2026:

| Category      | 2024  | 2025  | 2026  |
|---------------|-------|-------|-------|
| Tech-AI       | 78.9% | 84.8% | 71.2% |
| Politics      | 70.0% | 77.6% | 76.6% |
| Sports-Other  | 81.7% | 84.9% | 64.3% |

Politics is stable. Tech-AI and Sports-Other both dropped. Hypotheses: (a) the meme strategy got known and partly priced in; (b) 2026 is a partial year with resolution-time selection bias; (c) small-sample noise. The config uses full-history rates (which are below the 2025 peaks) as a safety margin. Re-measure quarterly.

## Open limitations

1. **No price time-series** — we can't verify that a market was actually enterable at our ceiling during its lifetime. Volume is the only proxy. Once the bot is live, we log every observed book and can tighten this retroactively.
2. **Selection bias in live trading** — a market whose No price dips below our ceiling is disproportionately one where Yes sentiment just spiked. Realized edge will be below nominal.
3. **Liquidity depth** — lifetime volume ≠ live order-book depth. The executor must check `getBook` before placing and abort on thin books.
4. **Fee model** — parabolic taker fee peaking at 50¢ (0.75–1.0% of stake) matches [`finance.estimate_taker_fee`](../finance.py). Fee drag stays under 1% of stake; confirmed not to materially affect the edge.
