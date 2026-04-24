"""Telegram alerting for the no-bot.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the env. Silent no-op when
either is missing, so paper-trading runs without configured creds don't error.
"""
from __future__ import annotations

import logging
import os
import requests

log = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.environ.get("ENABLE_TELEGRAM", "true").lower() != "false"


def send(message: str) -> None:
    if not _enabled():
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip("\"'")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip("\"'")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=5,
        )
    except Exception as e:
        log.warning("Telegram send failed: %s", e)


def entry(*, question: str, category: str, no_price: float, bet_usd: float, mock: bool) -> None:
    tag = "📝 PAPER" if mock else "💰 LIVE"
    send(
        f"{tag} ENTRY [{category}]\n"
        f"{question[:120]}\n"
        f"No={no_price:.3f}  bet=${bet_usd:.2f}"
    )


def resolution(*, question: str, won: bool, pnl_usd: float, mock: bool) -> None:
    tag = "📝 paper" if mock else "💰 live"
    outcome = "✅ WIN" if won else "❌ LOSS"
    send(f"{outcome} ({tag})\n{question[:120]}\nP&L: ${pnl_usd:+.2f}")


def drawdown_halt(realized_loss: float, threshold_pct: float) -> None:
    send(
        f"🛑 DRAWDOWN HALT\n"
        f"Realized loss ${realized_loss:.2f} crossed -{threshold_pct:.0f}% of bankroll. "
        f"No new positions until manually resumed."
    )


def scanner_error(err: str) -> None:
    send(f"⚠️ Scanner error: {err[:300]}")
