"""Entrypoint: python -m no_bot

Minimal scaffolding: scans Gamma, prints candidate markets + sized bets.
Paper-mode only. Executor (CLOB order placement) and resolver are TODO.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from . import db
from .config import SCAN_INTERVAL_SEC
from .scanner import find_candidates
from .sizer import can_open, kelly_size

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("no_bot")


def run_once(bankroll: float, live: bool) -> None:
    conn = db.connect()
    open_pos = db.open_positions(conn)
    deployed = sum(p["bet_size_usd"] for p in open_pos)
    by_event: dict[str, int] = {}
    by_category: dict[str, float] = {}
    for p in open_pos:
        if p["event_id"]:
            by_event[p["event_id"]] = by_event.get(p["event_id"], 0) + 1
        by_category[p["category"]] = by_category.get(p["category"], 0.0) + p["bet_size_usd"]

    candidates = find_candidates()
    log.info("Bankroll=$%.2f deployed=$%.2f candidates=%d", bankroll, deployed, len(candidates))

    for c in candidates:
        if db.has_open_on_market(conn, c["market_id"]):
            continue
        ok, reason = can_open(
            bankroll=bankroll, deployed=deployed,
            category=c["category"], event_id=c["event_id"],
            open_positions_by_event=by_event,
            open_positions_by_category=by_category,
        )
        if not ok:
            log.debug("skip %s: %s", c["question"], reason)
            continue
        bet = kelly_size(bankroll, c["category"], c["no_price"])
        if bet <= 0 or bet > bankroll:
            continue

        log.info(
            "ENTER [%s] %s  No=%.3f  bet=$%.2f  (event=%s)",
            c["category"], c["question"][:60], c["no_price"], bet, c["event_id"],
        )

        if live:
            # TODO: executor.place_no_order(c, bet)
            log.warning("live mode not yet implemented — paper-recording only")

        db.insert_position(
            conn,
            market_id=c["market_id"], event_id=c["event_id"],
            question=c["question"], category=c["category"],
            entry_no_price=c["no_price"], bet_size_usd=bet,
            fee_paid_usd=0.0,
            placed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            mock=not live,
        )
        # Update local tracking so subsequent iterations respect caps
        bankroll -= bet
        deployed += bet
        if c["event_id"]:
            by_event[c["event_id"]] = by_event.get(c["event_id"], 0) + 1
        by_category[c["category"]] = by_category.get(c["category"], 0.0) + bet

    conn.close()


def main() -> None:
    live = os.getenv("NO_BOT_LIVE", "false").lower() == "true"
    bankroll = float(os.getenv("NO_BOT_BANKROLL", "500"))
    log.info("No-bot starting. live=%s bankroll=$%.2f", live, bankroll)
    while True:
        try:
            run_once(bankroll, live)
        except Exception:
            log.exception("scan iteration failed")
        time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    main()
