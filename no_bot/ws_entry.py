"""WebSocket-driven entry timing for the No-bot.

The scanner answers "is this market in range?". This module answers
"is *now* the right moment to enter?". We subscribe to the live trade
price stream for each in-range market and wait for one of three triggers:

  1. Dip trigger (preferred) — current No price is at least DIP_FRAC below
     the rolling MEDIAN_WINDOW_SEC median, AND still under the category
     ceiling. Catches Yes-sentiment pumps just before they revert.

  2. Watch-time fallback — after WATCH_TIMEOUT_SEC of monitoring with no
     dip, enter at the next in-range tick. Avoids capital sitting idle on
     a market that drifts sideways for days.

  3. Deadline fallback — when end_date is within DEADLINE_FALLBACK_HOURS,
     enter at next in-range tick regardless of dip. Better to take the
     positive-EV bet than miss it because we were waiting for a perfect
     entry.

Short-fuse markets (≤ SHORT_FUSE_HOURS to resolution) skip the dip detector
entirely and enter immediately on first observation. There isn't enough
time-window to compute a meaningful rolling median.

Polymarket WebSocket: `wss://ws-subscriptions-clob.polymarket.com/ws/market`.
We subscribe to `last_trade_price` events, identified by `asset_id` (the
ERC-1155 token id of the No outcome).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    import websocket
except ImportError:
    websocket = None

log = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

MEDIAN_WINDOW_SEC = 30 * 60         # rolling window for the price median
DIP_FRAC = 0.05                     # require 5% below median to trigger
MIN_OBSERVATIONS = 6                # min ticks before dip trigger arms
WATCH_TIMEOUT_SEC = 24 * 3600       # after 24h of watching, enter naively
DEADLINE_FALLBACK_HOURS = 24        # within 24h of resolution, enter naively
SHORT_FUSE_HOURS = 48               # below 48h to resolution, skip dip detector
PING_INTERVAL_SEC = 10              # Polymarket requires PING every 10s


@dataclass
class _Watch:
    market_id: str
    no_token_id: str
    end_date: str          # ISO date "YYYY-MM-DD"
    ceiling: float         # category ceiling (for sanity re-check on entry)
    first_seen: float = field(default_factory=time.monotonic)
    last_price: Optional[float] = None
    # (monotonic_ts, price)
    buffer: deque = field(default_factory=lambda: deque(maxlen=2000))


class WSEntryGate:
    """Stateful gate between the scanner and the executor.

    Lifecycle, per market:
      scanner finds it in-range  →  gate.watch(candidate)
      gate.evaluate(candidates)  →  returns subset ready to enter NOW
      executor enters one        →  gate.unwatch(market_id)
      market closes / drops out  →  gate prunes on next evaluate()
    """

    def __init__(self):
        self._watches: dict[str, _Watch] = {}      # market_id -> watch
        self._token_to_market: dict[str, str] = {} # no_token_id -> market_id
        self._lock = threading.Lock()
        self._ws: Optional["websocket.WebSocketApp"] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ping_thread: Optional[threading.Thread] = None
        self._is_connected = False
        self._is_running = False

        if websocket is None:
            log.warning(
                "websocket-client not installed — WS entry gate disabled, "
                "falling back to naive entry on every scan."
            )

    # ── Public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        if websocket is None or self._is_running:
            return
        self._is_running = True
        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._ws_thread.start()

    def stop(self) -> None:
        self._is_running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def evaluate(self, candidates: list[dict]) -> list[dict]:
        """Update watchlist from current candidates and return any ready to enter.

        Called once per scan cycle from no_bot.__main__.run_scan.
        """
        # If WS isn't available, fall back to naive entry: every candidate
        # is "ready to enter" immediately. Preserves prior behavior.
        if websocket is None:
            return list(candidates)

        candidate_by_id = {c["market_id"]: c for c in candidates if c.get("no_token_id")}
        ready: list[dict] = []

        with self._lock:
            # Prune watches that are no longer in-range or have lost their token id
            stale = [mid for mid in self._watches if mid not in candidate_by_id]
            for mid in stale:
                self._drop_locked(mid)

            # Add any new candidates to the watchlist
            new_tokens: list[str] = []
            for mid, c in candidate_by_id.items():
                if mid in self._watches:
                    continue
                w = _Watch(
                    market_id=mid,
                    no_token_id=c["no_token_id"],
                    end_date=c.get("end_date", "") or "",
                    ceiling=_ceiling_for(c["category"]),
                )
                # Seed the buffer with the scanner's price snapshot so the
                # rolling median has something to chew on if WS is slow.
                w.buffer.append((time.monotonic(), float(c["no_price"])))
                w.last_price = float(c["no_price"])
                self._watches[mid] = w
                self._token_to_market[c["no_token_id"]] = mid
                new_tokens.append(c["no_token_id"])

            if new_tokens:
                self._subscribe(new_tokens)

            # Decide which ones are ready
            for mid, c in candidate_by_id.items():
                w = self._watches.get(mid)
                if w is None:
                    continue
                if self._should_enter(w):
                    ready.append(c)

        return ready

    def unwatch(self, market_id: str) -> None:
        """Caller's signal that we entered (or otherwise want to stop tracking)."""
        with self._lock:
            self._drop_locked(market_id)

    # ── Decision logic ────────────────────────────────────────────────────

    def _should_enter(self, w: _Watch) -> bool:
        if w.last_price is None:
            return False
        if w.last_price > w.ceiling:
            return False  # drifted out of range; wait for it to come back

        hours_to_end = _hours_until(w.end_date)

        # 3. Deadline fallback — getting close to resolution; just take it.
        if hours_to_end is not None and hours_to_end <= DEADLINE_FALLBACK_HOURS:
            log.info("WS entry [%s]: deadline fallback (%.1fh left)", w.market_id, hours_to_end)
            return True

        # Short-fuse: skip the dip detector entirely; enter on first obs.
        if hours_to_end is not None and hours_to_end <= SHORT_FUSE_HOURS:
            log.info("WS entry [%s]: short-fuse fallback (%.1fh left)", w.market_id, hours_to_end)
            return True

        # 2. Watch-time fallback
        watched_for = time.monotonic() - w.first_seen
        if watched_for >= WATCH_TIMEOUT_SEC:
            log.info("WS entry [%s]: watch-timeout fallback (%.0fh watched)",
                     w.market_id, watched_for / 3600)
            return True

        # 1. Dip trigger
        median = self._rolling_median(w)
        if median is None:
            return False
        threshold = median * (1 - DIP_FRAC)
        if w.last_price <= threshold:
            log.info(
                "WS entry [%s]: DIP trigger price=%.3f median=%.3f threshold=%.3f",
                w.market_id, w.last_price, median, threshold,
            )
            return True

        return False

    def _rolling_median(self, w: _Watch) -> Optional[float]:
        cutoff = time.monotonic() - MEDIAN_WINDOW_SEC
        prices = [p for ts, p in w.buffer if ts >= cutoff]
        if len(prices) < MIN_OBSERVATIONS:
            return None
        prices.sort()
        n = len(prices)
        return prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2

    def _drop_locked(self, market_id: str) -> None:
        w = self._watches.pop(market_id, None)
        if w:
            self._token_to_market.pop(w.no_token_id, None)
            # Polymarket WS has no per-asset unsubscribe; the asset just stops
            # mattering. Stale subscriptions are harmless other than bandwidth.

    # ── WebSocket plumbing ────────────────────────────────────────────────

    def _ws_loop(self) -> None:
        backoff = 5
        while self._is_running:
            try:
                self._ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_close=self._on_close,
                    on_error=self._on_error,
                )
                self._ws.run_forever()
            except Exception:
                log.exception("WS entry gate: run_forever crashed")
            if not self._is_running:
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)

    def _on_open(self, ws) -> None:
        self._is_connected = True
        log.info("✅ WS entry gate connected")
        # Re-subscribe to everything we're currently watching (covers reconnects)
        with self._lock:
            tokens = [w.no_token_id for w in self._watches.values()]
        if tokens:
            self._subscribe(tokens)
        # Start ping thread
        if self._ping_thread is None or not self._ping_thread.is_alive():
            self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
            self._ping_thread.start()

    def _on_close(self, ws, code, msg) -> None:
        self._is_connected = False
        log.info("WS entry gate closed (code=%s)", code)

    def _on_error(self, ws, err) -> None:
        log.warning("WS entry gate error: %s", err)

    def _on_message(self, ws, message) -> None:
        if message == "PONG":
            return
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        # Polymarket may send either a single dict or a list.
        events = data if isinstance(data, list) else [data]
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("event_type") != "last_trade_price":
                continue
            asset_id = str(ev.get("asset_id", ""))
            try:
                price = float(ev.get("price"))
            except (TypeError, ValueError):
                continue
            with self._lock:
                mid = self._token_to_market.get(asset_id)
                if not mid:
                    continue
                w = self._watches.get(mid)
                if not w:
                    continue
                w.last_price = price
                w.buffer.append((time.monotonic(), price))

    def _subscribe(self, token_ids: list[str]) -> None:
        if not self._ws or not self._is_connected:
            return
        try:
            self._ws.send(json.dumps({
                "type": "market",
                "assets_ids": token_ids,
                "custom_feature_enabled": True,
            }))
            log.info("📡 WS entry gate subscribed to %d markets", len(token_ids))
        except Exception:
            log.exception("WS subscribe failed")

    def _ping_loop(self) -> None:
        while self._is_running and self._is_connected:
            try:
                if self._ws:
                    self._ws.send("PING")
            except Exception:
                break
            time.sleep(PING_INTERVAL_SEC)


# ── Helpers ──────────────────────────────────────────────────────────────

def _ceiling_for(category: str) -> float:
    from .config import CATEGORY_CONFIG
    rule = CATEGORY_CONFIG.get(category)
    return rule.ceiling if rule else 1.0


def _hours_until(end_date_iso: str) -> Optional[float]:
    if not end_date_iso:
        return None
    try:
        end = datetime.strptime(end_date_iso[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return (end - datetime.now()).total_seconds() / 3600
