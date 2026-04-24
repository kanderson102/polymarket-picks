"""Resolve open No-Bot positions against the Gamma API.

Runs on RESOLVE_INTERVAL_SEC cadence (every 10 minutes). For each open
position, checks if the underlying market has resolved and books P&L.

P&L accounting:
  WIN  (No resolved): pnl = bet_size * (1/entry_no_price - 1)
  LOSS (Yes resolved): pnl = -bet_size
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from . import db

log = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
GRACE_DAYS = 3   # days past end_date before we expire an unresolved position
MAX_AGE_DAYS = 60  # hard cap — expire anything this old regardless


def resolve_all(conn) -> None:
    positions = db.all_open_positions(conn)
    if not positions:
        return

    resolved_n = 0
    expired_n = 0
    now = datetime.now(timezone.utc)

    for pos in positions:
        try:
            _resolve_one(conn, pos, now, resolved_n, expired_n)
        except Exception as e:
            log.debug("Resolution check failed for position %d: %s", pos["id"], e)

    # Re-fetch counts after updates for logging
    resolved_n = conn.execute(
        "SELECT COUNT(*) FROM no_positions WHERE status='closed'"
    ).fetchone()[0]
    log.info("Resolver: %d positions checked, %d total closed", len(positions), resolved_n)


def _resolve_one(conn, pos: dict, now: datetime, resolved_n: int, expired_n: int) -> None:
    market_id = pos["market_id"]
    resp = requests.get(
        f"{GAMMA_API}/markets/{market_id}",
        timeout=10,
    )
    if resp.status_code == 404:
        log.warning("Market %s not found — leaving open", market_id)
        return
    resp.raise_for_status()
    market = resp.json()

    # Stash current No price for mark-to-market drawdown accounting.
    import json as _json
    try:
        outs = _json.loads(market.get("outcomes", "[]"))
        prs = _json.loads(market.get("outcomePrices", "[]"))
        if len(outs) == 2 and len(prs) == 2 and "no" in [o.lower() for o in outs]:
            no_idx = [o.lower() for o in outs].index("no")
            db.update_last_known_price(conn, pos["id"], float(prs[no_idx]))
    except (ValueError, TypeError):
        pass

    resolved = market.get("resolved", False)
    archived = market.get("archived", False)

    if resolved or archived:
        # Determine winner: outcomes are ["Yes","No"], outcomePrices shows [1.0,0.0] or [0.0,1.0]
        import json
        try:
            outcomes = json.loads(market.get("outcomes", "[]"))
            prices = json.loads(market.get("outcomePrices", "[]"))
        except (ValueError, TypeError):
            outcomes, prices = [], []

        winning_outcome = None
        if outcomes and prices and len(outcomes) == len(prices):
            for o, p in zip(outcomes, prices):
                if float(p) >= 0.99:
                    winning_outcome = o.lower()
                    break
        # Fallback: check market.outcome field
        if winning_outcome is None:
            winning_outcome = (market.get("outcome") or "").lower()

        if not winning_outcome:
            log.debug("Market %s resolved but winner unclear — skipping", market_id)
            return

        resolved_yes = 1 if winning_outcome == "yes" else 0
        entry = pos["entry_no_price"]
        bet = pos["bet_size_usd"]
        if resolved_yes == 0:
            # No won — collect payout minus stake already out
            pnl = bet * ((1.0 / entry) - 1.0) if entry > 0 else 0.0
        else:
            pnl = -bet

        resolved_at = now.isoformat(timespec="seconds")
        db.close_position(conn, pos["id"], resolved_yes, pnl, resolved_at)

        emoji = "🏆" if resolved_yes == 0 else "💀"
        log.info(
            "%s RESOLVED pos=%d [%s] %s  No=%.3f  bet=$%.2f  pnl=$%+.2f",
            emoji, pos["id"], pos["category"], pos["question"][:50],
            entry, bet, pnl,
        )
        _send_telegram(pos, resolved_yes, pnl)
        return

    # Not resolved yet — check if it's past expiry
    end_date_str = (market.get("endDate") or "")[:10]
    if end_date_str:
        try:
            end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            days_past = (now - end_dt).days
            if days_past >= GRACE_DAYS:
                db.expire_position(conn, pos["id"])
                log.warning(
                    "⏰ EXPIRED pos=%d [%s] %s  (end_date %s, %dd past grace)",
                    pos["id"], pos["category"], pos["question"][:50], end_date_str, days_past,
                )
                return
        except ValueError:
            pass

    # Hard cap by age
    try:
        placed = datetime.fromisoformat(pos["placed_at"].replace("Z", "+00:00"))
        if (now - placed).days >= MAX_AGE_DAYS:
            db.expire_position(conn, pos["id"])
            log.warning("⏰ EXPIRED pos=%d — %d days old", pos["id"], (now - placed).days)
    except (ValueError, TypeError):
        pass


def _send_telegram(pos: dict, resolved_yes: int, pnl: float) -> None:
    """Fire a Telegram notification if the shared DB config says to."""
    import os
    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).resolve().parent.parent / "trading.db"
    try:
        cfg_conn = sqlite3.connect(db_path)
        rows = dict(cfg_conn.execute("SELECT key, value FROM bot_config").fetchall())
        cfg_conn.close()
    except Exception:
        return

    if rows.get("enable_telegram", "1") != "1":
        return
    if rows.get("notify_nb_resolve", "1") != "1":
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip("\"'")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip("\"'")
    if not token or not chat_id:
        return

    emoji = "🏆" if resolved_yes == 0 else "💀"
    result = "WON (No resolved)" if resolved_yes == 0 else "LOST (Yes resolved)"
    msg = "\n".join([
        f"{emoji} NO-BOT RESOLVED: {result}",
        "",
        f"📋 {pos['question'][:80]}",
        f"🏷️ {pos['category']}",
        f"🎯 No @ ${pos['entry_no_price']:.2f}",
        f"💵 Bet: ${pos['bet_size_usd']:.2f}",
        f"💰 P&L: ${pnl:+.2f}",
    ])
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=5,
        )
    except Exception:
        pass
