"""Bet sizing for the No-bot: fractional Kelly with hard caps."""
from __future__ import annotations

from .config import (
    CATEGORY_CONFIG, MIN_BET_USD, MAX_BET_FRAC_BANKROLL,
    MAX_CATEGORY_EXPOSURE, MAX_PER_EVENT,
)


def kelly_size(bankroll: float, category: str, no_price: float) -> float:
    """Return the intended bet size in USD, or 0.0 if no edge."""
    rule = CATEGORY_CONFIG.get(category)
    if rule is None:
        return 0.0
    if no_price > rule.ceiling:
        return 0.0

    win_payout = (1.0 / no_price) - 1.0
    edge = rule.no_rate * win_payout - (1 - rule.no_rate)
    if edge <= 0:
        return 0.0

    full_kelly = edge / win_payout
    raw_bet = bankroll * full_kelly * rule.kelly_frac
    capped = min(raw_bet, bankroll * MAX_BET_FRAC_BANKROLL)
    return max(MIN_BET_USD, capped) if capped >= MIN_BET_USD else 0.0


def can_open(
    bankroll: float,
    deployed: float,
    category: str,
    event_id: str | None,
    open_positions_by_event: dict[str, int],
    open_positions_by_category: dict[str, float],
) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty when ok=True."""
    if bankroll < MIN_BET_USD:
        return False, "bankroll below minimum bet"

    if event_id and open_positions_by_event.get(event_id, 0) >= MAX_PER_EVENT:
        return False, f"event {event_id} already has {MAX_PER_EVENT} positions"

    total_capital = bankroll + deployed
    if total_capital <= 0:
        return False, "no capital"
    cat_exposure = open_positions_by_category.get(category, 0.0) / total_capital
    if cat_exposure >= MAX_CATEGORY_EXPOSURE:
        return False, f"{category} exposure at {cat_exposure:.0%} (cap {MAX_CATEGORY_EXPOSURE:.0%})"

    return True, ""
