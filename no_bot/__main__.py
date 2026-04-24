"""Entrypoint: python -m no_bot

Two loops share a single process:
  • Scan loop  — every SCAN_INTERVAL_SEC (5 min): find candidates, size bets, execute
  • Resolve loop — every RESOLVE_INTERVAL_SEC (10 min): settle open positions, book P&L

Settings are loaded from trading.db on each iteration so UI edits take effect
without a restart. NO_BOT_DRY_RUN=true (the default) logs what would be
submitted without touching real money.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from . import alerts, db
from .config import RESOLVE_INTERVAL_SEC, SCAN_INTERVAL_SEC
from .executor import DRY_RUN, place_no_order
from .resolver import resolve_all
from .runtime import load as load_runtime
from .scanner import find_candidates
from .sizer import can_open, kelly_size
from .ws_entry import WSEntryGate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("no_bot")


def _check_drawdown(conn, rc) -> bool:
    """Return True if trading should halt due to drawdown, False if ok to trade.

    Combines closed (realized) P&L with mark-to-market unrealized P&L on open
    live positions. Unrealized uses last_known_no_price stashed by the resolver
    on its 10-min pass; if absent, falls back to entry price (zero unrealized).
    """
    realized_pnl = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd), 0) FROM no_positions "
        "WHERE status='closed' AND mock=0"
    ).fetchone()[0]

    open_rows = conn.execute(
        "SELECT entry_no_price, bet_size_usd, last_known_no_price "
        "FROM no_positions WHERE status='open' AND mock=0"
    ).fetchall()
    unrealized = 0.0
    for entry, bet, last in open_rows:
        if not entry or not bet or last is None:
            continue
        # P&L = bet * (last/entry - 1). Negative when No price has dropped
        # below our entry — i.e. the market is now more bullish on Yes.
        unrealized += float(bet) * (float(last) / float(entry) - 1.0)

    total_loss = realized_pnl + unrealized
    if total_loss >= 0:
        return False

    loss_frac = abs(total_loss) / rc.bankroll
    if loss_frac >= rc.drawdown_halt:
        log.warning(
            "🛑 DRAWDOWN HALT: total loss $%.2f (realized $%.2f + unrealized $%.2f) = "
            "%.1f%% of bankroll (threshold %.0f%%) — no new positions until reviewed",
            abs(total_loss), realized_pnl, unrealized, loss_frac * 100, rc.drawdown_halt * 100,
        )
        alerts.drawdown_halt(abs(total_loss), rc.drawdown_halt * 100)
        return True
    return False


_GATE = WSEntryGate()


def run_scan() -> None:
    scan_start = time.monotonic()
    scan_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rc = load_runtime()
    conn = db.connect()

    # ── Drawdown check ────────────────────────────────────────────────────────
    if rc.live and _check_drawdown(conn, rc):
        db.record_scan(
            conn, ts=scan_ts, events_seen=0, candidates_found=0,
            positions_entered=0, duration_ms=int((time.monotonic() - scan_start) * 1000),
            error="drawdown halt",
        )
        conn.close()
        return

    # ── Load open position state ──────────────────────────────────────────────
    open_pos = db.open_positions(conn)
    deployed = sum(p["bet_size_usd"] for p in open_pos)
    by_event: dict[str, int] = {}
    by_category: dict[str, float] = {}
    for p in open_pos:
        if p["event_id"]:
            by_event[p["event_id"]] = by_event.get(p["event_id"], 0) + 1
        by_category[p["category"]] = by_category.get(p["category"], 0.0) + p["bet_size_usd"]

    mode = "[DRY RUN]" if DRY_RUN else ("LIVE" if rc.live else "paper")
    log.info(
        "[%s] bankroll=$%.2f deployed=$%.2f open=%d small_bankroll=%s fast_turnover=%s",
        mode, rc.bankroll, deployed, len(open_pos),
        rc.small_bankroll_mode, rc.fast_turnover,
    )

    evaluations: list[dict] = []
    candidates = find_candidates(rc=rc, evaluations=evaluations)

    # WS gate decides which in-range candidates are ready to enter NOW
    # (dip detected, watch-time exceeded, or deadline approaching).
    # Markets that aren't ready stay on the watchlist and are re-checked
    # next cycle. See no_bot/ws_entry.py for the trigger logic.
    ready = _GATE.evaluate(candidates)
    log.info("candidates=%d ready=%d", len(candidates), len(ready))

    positions_entered = 0
    remaining = rc.bankroll
    for c in ready:
        if db.has_open_on_market(conn, c["market_id"]):
            continue

        rc_step = rc.__class__(
            live=rc.live, bankroll=remaining,
            small_bankroll_mode=rc.small_bankroll_mode and remaining < 250.0,
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
            log.debug("skip %s: %s", c["question"][:50], reason)
            continue

        bet = kelly_size(rc_step, c["category"], c["no_price"])
        if bet <= 0 or bet > remaining:
            continue

        placed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if rc.live or DRY_RUN:
            # Executor handles stale-price check, signing, and submission.
            # Returns (fill_price, filled_size) or (None, None) on failure.
            fill_price, filled_size = place_no_order(c, bet, rc)
            if fill_price is None:
                continue  # order rejected or stale — do NOT write to DB; retry next scan
            actual_price = fill_price
            actual_bet = filled_size
            is_mock = DRY_RUN  # dry-run positions are flagged mock=1
        else:
            # Pure paper mode: record at scanner price with no CLOB interaction
            actual_price = c["no_price"]
            actual_bet = bet
            is_mock = True

        log.info(
            "ENTER [%s] %s  No=%.3f  bet=$%.2f  (event=%s)",
            c["category"], c["question"][:60], actual_price, actual_bet, c["event_id"],
        )

        db.insert_position(
            conn,
            market_id=c["market_id"], event_id=c["event_id"],
            question=c["question"], category=c["category"],
            entry_no_price=actual_price, bet_size_usd=actual_bet,
            fee_paid_usd=0.0,
            placed_at=placed_at,
            mock=is_mock,
        )

        alerts.entry(
            question=c["question"], category=c["category"],
            no_price=actual_price, bet_usd=actual_bet, mock=is_mock,
        )
        _GATE.unwatch(c["market_id"])
        remaining -= actual_bet
        deployed += actual_bet
        positions_entered += 1
        if c["event_id"]:
            by_event[c["event_id"]] = by_event.get(c["event_id"], 0) + 1
        by_category[c["category"]] = by_category.get(c["category"], 0.0) + actual_bet

    # Record telemetry so the dashboard can show "scanner is alive"
    events_seen = len({e.get("event_id") for e in evaluations if e.get("event_id")})
    db.record_scan(
        conn, ts=scan_ts, events_seen=events_seen,
        candidates_found=len(candidates), positions_entered=positions_entered,
        duration_ms=int((time.monotonic() - scan_start) * 1000),
    )
    db.replace_scan_candidates(conn, scan_ts, evaluations)

    conn.close()


def run_resolve() -> None:
    conn = db.connect()
    try:
        resolve_all(conn)
    finally:
        conn.close()


def main() -> None:
    log.info(
        "No-bot starting. DRY_RUN=%s  Config loaded from trading.db each scan.",
        DRY_RUN,
    )
    _GATE.start()
    if DRY_RUN:
        log.info(
            "Set NO_BOT_DRY_RUN=false in .env to submit real orders. "
            "Also set nb_live_mode=1 from the Settings → No-Bot dashboard tab."
        )

    last_resolve = 0.0

    while True:
        try:
            run_scan()
        except Exception as e:
            log.exception("scan iteration failed")
            err_text = f"{type(e).__name__}: {e}"
            # Record the failure so the dashboard can flag a dead scanner.
            try:
                err_conn = db.connect()
                db.record_scan(
                    err_conn,
                    ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    events_seen=0, candidates_found=0, positions_entered=0,
                    duration_ms=0, error=err_text[:200],
                )
                err_conn.close()
            except Exception:
                log.exception("failed to record scan error")
            alerts.scanner_error(err_text)

        now = time.time()
        if now - last_resolve >= RESOLVE_INTERVAL_SEC:
            try:
                run_resolve()
            except Exception:
                log.exception("resolve iteration failed")
            last_resolve = now

        time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    main()
