"""Bet sizing for the No-bot: fractional Kelly with hard caps.

When `small_bankroll_mode` is True (bankroll < $250), sizing switches to a
flat `min_bet_usd` per entry instead of Kelly-scaled sizing — the Kelly
fraction of $50 × ~0.05 is below Polymarket's $5 minimum, so we'd emit zero
trades otherwise. Once bankroll exceeds $250 the caller flips the flag and
the normal Kelly path kicks back in.
"""
from __future__ import annotations

from .runtime import RuntimeConfig


def kelly_size(rc: RuntimeConfig, category: str, no_price: float) -> float:
    """Return the intended bet size in USD, or 0.0 if no edge."""
    rule = rc.categories.get(category)
    if rule is None:
        return 0.0
    if no_price > rule.ceiling:
        return 0.0

    if rc.small_bankroll_mode:
        if rc.bankroll < rc.min_bet_usd:
            return 0.0
        return rc.min_bet_usd

    win_payout = (1.0 / no_price) - 1.0
    edge = rule.no_rate * win_payout - (1 - rule.no_rate)
    if edge <= 0:
        return 0.0

    full_kelly = edge / win_payout
    raw_bet = rc.bankroll * full_kelly * rule.kelly_frac
    capped = min(raw_bet, rc.bankroll * rc.max_bet_frac)
    return max(rc.min_bet_usd, capped) if capped >= rc.min_bet_usd else 0.0


def can_open(
    rc: RuntimeConfig,
    deployed: float,
    category: str,
    event_id: str | None,
    open_positions_by_event: dict[str, int],
    open_positions_by_category: dict[str, float],
) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty when ok=True."""
    if rc.bankroll < rc.min_bet_usd:
        return False, "bankroll below minimum bet"

    if event_id and open_positions_by_event.get(event_id, 0) >= rc.max_per_event:
        return False, f"event {event_id} already has {rc.max_per_event} positions"

    total_capital = rc.bankroll + deployed
    if total_capital <= 0:
        return False, "no capital"
    cat_exposure = open_positions_by_category.get(category, 0.0) / total_capital
    if cat_exposure >= rc.max_category_exposure:
        return False, f"{category} exposure at {cat_exposure:.0%} (cap {rc.max_category_exposure:.0%})"

    return True, ""
