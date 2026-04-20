"""No-bot strategy configuration.

Base rates here are measured on SINGLE-MARKET EVENTS ONLY (binary matchups:
"Will X happen by date Y?"). Multi-candidate events — tournament brackets,
elections with >2 candidates, etc. — are skipped by the scanner because
their per-sibling pricing bakes in the Yes probability by construction and
there is no tradable edge.

See docs/no-bot-strategy.md for the thesis.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryRule:
    no_rate: float        # binary-matchup base rate (single-market events)
    tier: int             # 1=strong edge, 2=moderate, 3=thin
    ceiling: float        # max No entry price
    kelly_frac: float     # fraction of full Kelly per bet


# Only categories with ≥60 single-market-event samples and meaningful margin
# over the no_rate = no_price breakeven line. Everything else lacks either
# data or edge.
CATEGORY_CONFIG: dict[str, CategoryRule] = {
    "Tech-AI":      CategoryRule(0.770, 1, 0.60, 0.20),
    "Sports-Other": CategoryRule(0.701, 2, 0.55, 0.15),
    "Politics":     CategoryRule(0.705, 2, 0.55, 0.15),
}

# Everything not in CATEGORY_CONFIG is implicitly excluded by the scanner.
# Categories listed here are explicitly named for docs / logging purposes:
#   - Sports-Soccer: 42.7% No rate → Yes is the base case, no edge
#   - Sports-Esports, Sports-Basketball, Sports-Baseball: <65% binary-matchup
#     No rate, too thin to trade
#   - Sports-Hockey, Economics: not enough single-market events in the data
#     to establish a base rate (almost always bundled in bracket events)
#   - Crypto: volatile pricing makes entry + slippage the dominant risk
#   - Recurring / UpOrDown: 50/50 by design
EXCLUDED_CATEGORIES: set[str] = {
    "Sports-Soccer", "Sports-Esports", "Sports-Basketball", "Sports-Baseball",
    "Sports-Hockey", "Economics", "Crypto", "Recurring", "UpOrDown",
    "Entertainment", "Other", "Stocks-Daily", "General",
}

# Hard operating limits
MIN_VOLUME_USD = 10_000     # skip markets with lifetime volume below this
MAX_PER_EVENT = 1           # binary matchups only; one position per event by construction
MIN_BET_USD = 5.0           # Polymarket minimum
MAX_BET_FRAC_BANKROLL = 0.05  # cap per-bet at 5% of bankroll
MAX_CATEGORY_EXPOSURE = 0.40  # cap 40% of deployed capital in one category
DRAWDOWN_HALT = 0.30        # stop taking positions at -30% from start

# Scanner cadence
SCAN_INTERVAL_SEC = 300     # every 5 minutes
RESOLVE_INTERVAL_SEC = 600  # every 10 minutes
