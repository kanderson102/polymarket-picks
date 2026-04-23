"""CLOB order executor for the No-Bot.

Submits a limit GTC (Good-Till-Cancelled) No order to Polymarket's CLOB.
Uses py-clob-client for EIP-712 signing + HTTP submission.

Dry-run mode (default): logs what would be submitted without sending anything.
Controlled by the environment variable NO_BOT_DRY_RUN (default "true").
Set to "false" only when you're ready for real money.

Env vars required for live execution:
  BOT_PRIVATE_KEY         — 0x-prefixed hex private key
  CLOB_API_KEY            — Polymarket L2 API key
  CLOB_API_SECRET         — Polymarket L2 API secret
  CLOB_API_PASSPHRASE     — Polymarket L2 API passphrase

One-time setup before first live bet:
  1. Connect wallet to polymarket.com and accept TOS
  2. python -c "from no_bot.executor import approve_usdc; approve_usdc()"
  3. Fund the wallet with USDC on Polygon

CLOB price freshness:
  The scanner reads outcomePrices from Gamma API which can lag a few seconds.
  Before submitting, we re-check the live CLOB order book. If the current
  best ask differs from the scanner price by > MAX_PRICE_DRIFT, we skip and
  let the next scan cycle pick it up.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

log = logging.getLogger(__name__)

CLOB_URL = "https://clob.polymarket.com"
MAX_PRICE_DRIFT = 0.03   # skip if live price moved > 3¢ from scanner price
DRY_RUN = os.environ.get("NO_BOT_DRY_RUN", "true").lower() != "false"


def _get_live_no_ask(condition_id: str) -> Optional[float]:
    """Fetch the current best No ask from the CLOB order book."""
    try:
        resp = requests.get(f"{CLOB_URL}/book", params={"token_id": condition_id}, timeout=5)
        resp.raise_for_status()
        book = resp.json()
        asks = book.get("asks", [])
        if not asks:
            return None
        # asks are sorted ascending — first is best (lowest) ask
        return float(asks[0]["price"])
    except Exception as e:
        log.warning("CLOB book fetch failed for %s: %s", condition_id, e)
        return None


def _build_client():
    """Return an authenticated py-clob-client ClobClient."""
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
    except ImportError:
        raise RuntimeError(
            "py-clob-client not installed. Run: pip install py-clob-client"
        )

    private_key = os.environ.get("BOT_PRIVATE_KEY", "").strip("\"'")
    api_key = os.environ.get("CLOB_API_KEY", "").strip("\"'")
    api_secret = os.environ.get("CLOB_API_SECRET", "").strip("\"'")
    api_passphrase = os.environ.get("CLOB_API_PASSPHRASE", "").strip("\"'")

    if not all([private_key, api_key, api_secret, api_passphrase]):
        raise RuntimeError(
            "Missing CLOB credentials. Set BOT_PRIVATE_KEY, CLOB_API_KEY, "
            "CLOB_API_SECRET, CLOB_API_PASSPHRASE in .env"
        )

    creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
    return ClobClient(
        host=CLOB_URL,
        chain_id=137,  # Polygon mainnet
        key=private_key,
        creds=creds,
        signature_type=0,  # EOA
    )


def approve_usdc() -> None:
    """One-time: approve the CLOB proxy to spend USDC from the bot wallet.

    Run this once before the first live bet:
        python -c "from no_bot.executor import approve_usdc; approve_usdc()"
    """
    client = _build_client()
    resp = client.update_agent_address()
    log.info("USDC approval response: %s", resp)


def place_no_order(
    candidate: dict,
    bet_usd: float,
    rc,  # RuntimeConfig — used for logging only
) -> tuple[Optional[float], Optional[float]]:
    """Submit a limit No order. Returns (fill_price, filled_size_usd) or (None, None) on failure.

    The caller should only write to DB on a non-None return.
    """
    condition_id = candidate.get("condition_id")
    scanner_price = candidate["no_price"]
    question = candidate["question"][:60]

    # ── 1. Re-verify price freshness ─────────────────────────────────────────
    if condition_id:
        live_ask = _get_live_no_ask(condition_id)
        if live_ask is not None:
            drift = abs(live_ask - scanner_price)
            if drift > MAX_PRICE_DRIFT:
                log.info(
                    "SKIP (stale price) %s  scanner=%.3f live=%.3f drift=%.3f",
                    question, scanner_price, live_ask, drift,
                )
                return None, None
            # Use the live price for the order, not the (potentially stale) scanner price
            order_price = live_ask
        else:
            order_price = scanner_price
    else:
        order_price = scanner_price

    # ── 2. Compute share size ─────────────────────────────────────────────────
    # Polymarket orders are in shares, not USD.
    # shares = USD_to_spend / no_price
    shares = round(bet_usd / order_price, 2)
    if shares < 1.0:
        log.info("SKIP (too few shares) %s  bet=$%.2f price=%.3f shares=%.2f",
                 question, bet_usd, order_price, shares)
        return None, None

    # ── 3. Dry-run gate ───────────────────────────────────────────────────────
    if DRY_RUN:
        log.info(
            "[DRY RUN] Would submit order: %s | No=%.3f | shares=%.2f | bet=$%.2f | "
            "condition_id=%s",
            question, order_price, shares, bet_usd, condition_id,
        )
        # Return scanner price and intended bet so the caller can paper-record it
        return order_price, bet_usd

    # ── 4. Live submission ────────────────────────────────────────────────────
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
    except ImportError:
        raise RuntimeError("py-clob-client not installed. Run: pip install py-clob-client")

    client = _build_client()

    order_args = OrderArgs(
        token_id=condition_id,
        price=order_price,
        size=shares,
        side="BUY",
        order_type=OrderType.GTC,
    )
    signed_order = client.create_order(order_args)

    try:
        resp = client.post_order(signed_order, order_type=OrderType.GTC)
    except Exception as e:
        log.error("CLOB order submission failed for %s: %s", question, e)
        return None, None

    order_id = resp.get("orderID") or resp.get("id") or ""
    status = resp.get("status", "unknown")

    # Check for fills — resp may include matched fills immediately
    fills = resp.get("fills", []) or []
    if fills:
        total_filled_usd = sum(float(f.get("size", 0)) * float(f.get("price", order_price))
                               for f in fills)
        avg_price = total_filled_usd / max(sum(float(f.get("size", 0)) for f in fills), 1e-9)
        log.info(
            "✅ ORDER FILLED %s | orderID=%s | avg_price=%.3f | filled=$%.2f",
            question, order_id, avg_price, total_filled_usd,
        )
        return avg_price, total_filled_usd

    if status in ("matched", "filled"):
        log.info("✅ ORDER MATCHED %s | orderID=%s | status=%s", question, order_id, status)
        return order_price, bet_usd

    if status in ("live", "open"):
        # GTC order resting on the book — treat as entered at intended price.
        # It will fill when market moves. The position is open in our DB.
        log.info("📋 ORDER RESTING %s | orderID=%s | No=%.3f", question, order_id, order_price)
        return order_price, bet_usd

    log.warning("Unexpected order status for %s: %s | resp=%s", question, status, resp)
    return None, None
