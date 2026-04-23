"""Entrypoint: python -m no_bot

Scans Gamma, sizes No bets, writes paper positions to trading.db. Settings
are loaded from the dashboard on each scan so UI edits take effect without a
restart. Live execution (CLOB order placement) and resolver are TODO.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from . import db
from .config import SCAN_INTERVAL_SEC
from .runtime import load as load_runtime
from .scanner import find_candidates
from .sizer import can_open, kelly_size

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("no_bot")


def run_once() -> None:
    rc = load_runtime()

    conn = db.connect()
    open_pos = db.open_positions(conn)
    deployed = sum(p["bet_size_usd"] for p in open_pos)
    by_event: dict[str, int] = {}
    by_category: dict[str, float] = {}
    for p in open_pos:
        if p["event_id"]:
            by_event[p["event_id"]] = by_event.get(p["event_id"], 0) + 1
        by_category[p["category"]] = by_category.get(p["category"], 0.0) + p["bet_size_usd"]

    mode = "LIVE" if rc.live else "paper"
    log.info(
        "[%s] bankroll=$%.2f deployed=$%.2f small_bankroll=%s fast_turnover=%s",
        mode, rc.bankroll, deployed, rc.small_bankroll_mode, rc.fast_turnover,
    )

    candidates = find_candidates(rc=rc)
    log.info("candidates=%d", len(candidates))

    remaining = rc.bankroll
    for c in candidates:
        if db.has_open_on_market(conn, c["market_id"]):
            continue
        # Refresh rc.bankroll so can_open sees live capital
        rc_step = rc.__class__(
            live=rc.live, bankroll=remaining,
            small_bankroll_mode=rc.small_bankroll_mode,
            fast_turnover=rc.fast_turnover,
            min_bet_usd=rc.min_bet_usd, max_bet_frac=rc.max_bet_frac,
            max_category_exposure=rc.max_category_exposure,
            max_per_event=rc.max_per_event,
            min_volume_usd=rc.min_volume_usd,
            drawdown_halt=rc.drawdown_halt,
            categories=rc.categories,
        )
        ok, reason = can_open(
            rc_step, deployed=deployed,
            category=c["category"], event_id=c["event_id"],
            open_positions_by_event=by_event,
            open_positions_by_category=by_category,
        )
        if not ok:
            log.debug("skip %s: %s", c["question"], reason)
            continue
        bet = kelly_size(rc_step, c["category"], c["no_price"])
        if bet <= 0 or bet > remaining:
            continue

        log.info(
            "ENTER [%s] %s  No=%.3f  bet=$%.2f  (event=%s)",
            c["category"], c["question"][:60], c["no_price"], bet, c["event_id"],
        )

        if rc.live:
            # TODO: executor.place_no_order(c, bet)
            log.warning("live mode not yet implemented — paper-recording only")

        db.insert_position(
            conn,
            market_id=c["market_id"], event_id=c["event_id"],
            question=c["question"], category=c["category"],
            entry_no_price=c["no_price"], bet_size_usd=bet,
            fee_paid_usd=0.0,
            placed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            mock=not rc.live,
        )
        remaining -= bet
        deployed += bet
        if c["event_id"]:
            by_event[c["event_id"]] = by_event.get(c["event_id"], 0) + 1
        by_category[c["category"]] = by_category.get(c["category"], 0.0) + bet

    conn.close()


def main() -> None:
    log.info("No-bot starting. Config is loaded from trading.db on each scan.")
    while True:
        try:
            run_once()
        except Exception:
            log.exception("scan iteration failed")
        time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    main()
