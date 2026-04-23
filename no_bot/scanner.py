"""Scan Gamma API for markets eligible for No entry.

Eligibility:
  - category in CATEGORY_CONFIG (not EXCLUDED)
  - lifetime volume >= MIN_VOLUME_USD
  - current No ask price <= category ceiling
  - market still active (not closed/resolved)
  - not already open in no_positions
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Optional

import requests

from datetime import datetime

from .config import EXCLUDED_CATEGORIES
from .runtime import RuntimeConfig, load as load_runtime

# Fast-turnover ordering: ascending by median resolution horizon so we prefer
# categories that recycle capital faster. Sports-Other ≈12d, Politics ≈33d,
# Tech-AI ≈75d. (Reindex when adding new categories.)
_FAST_TURNOVER_RANK = {"Sports-Other": 0, "Politics": 1, "Tech-AI": 2}

log = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"


# Tag ID -> category mapping. Kept in sync with backtest/fetch_markets.py.
# Fall through list: first matching set wins.
_CATEGORY_MAP = [
    ({"101757"}, "Recurring"),
    ({"102127"}, "UpOrDown"),
    ({"21", "1312", "235", "39", "818", "620"}, "Crypto"),
    ({"745", "28"}, "Sports-Basketball"),
    ({"100350", "306", "82", "100977", "1234"}, "Sports-Soccer"),
    ({"100381", "678"}, "Sports-Baseball"),
    ({"899", "100088", "100089"}, "Sports-Hockey"),
    ({"64", "102366", "100639"}, "Sports-Esports"),
    ({"1"}, "Sports-Other"),
    ({"2", "144", "100265", "100344"}, "Politics"),
    ({"370", "131", "833", "600", "102000", "101247"}, "Economics"),
    ({"102516"}, "Stocks-Daily"),
    ({"537", "817", "267"}, "Tech-AI"),
    ({"1164", "330"}, "Entertainment"),
    ({"100215"}, "General"),
]


def categorize(tag_ids: Iterable[str]) -> str:
    tag_set = set(tag_ids)
    for tags, cat in _CATEGORY_MAP:
        if tag_set & tags:
            return cat
    return "Other"


def fetch_open_events(limit: int = 100, offset: int = 0) -> list[dict]:
    resp = requests.get(
        f"{GAMMA_API}/events",
        params={"closed": "false", "limit": limit, "offset": offset,
                "order": "startDate", "ascending": "false"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_no_ask(market: dict) -> Optional[float]:
    """Return the current No ask price from market.outcomePrices.

    Gamma returns outcomePrices as a JSON-encoded string. We only handle binary
    Yes/No markets.
    """
    try:
        outcomes = json.loads(market.get("outcomes", "[]"))
        prices = json.loads(market.get("outcomePrices", "[]"))
    except (json.JSONDecodeError, TypeError):
        return None
    if len(outcomes) != 2 or len(prices) != 2:
        return None
    lowered = [o.lower() for o in outcomes]
    if "no" not in lowered:
        return None
    no_idx = lowered.index("no")
    try:
        return float(prices[no_idx])
    except (ValueError, TypeError):
        return None


def find_candidates(max_events: int = 500, rc: RuntimeConfig | None = None) -> list[dict]:
    """Return a list of candidate-market dicts ready for sizing & execution."""
    if rc is None:
        rc = load_runtime()
    candidates: list[dict] = []
    seen_events = 0
    offset = 0

    while seen_events < max_events:
        try:
            events = fetch_open_events(offset=offset)
        except requests.RequestException as e:
            log.warning("Gamma fetch failed at offset %d: %s", offset, e)
            break
        if not events:
            break

        for event in events:
            seen_events += 1
            tags = [str(t["id"]) for t in event.get("tags", []) if isinstance(t, dict)]
            category = categorize(tags)
            if category in EXCLUDED_CATEGORIES or category not in rc.categories:
                continue

            # Binary-matchup-only rule. Our base rates are measured on events
            # containing exactly one market ("Will X happen by date Y?"). A
            # bracket event with N candidates has each sibling priced such
            # that Yes probabilities sum to ~1 — any candidate cheap enough
            # to meet our ceiling is the market's *favorite*, which flips
            # the base rate against us. Skip multi-market events entirely.
            event_markets = event.get("markets", [])
            if len(event_markets) != 1:
                continue

            rule = rc.categories[category]
            event_id = str(event.get("id", ""))
            for market in event_markets:
                volume = float(market.get("volumeNum", 0) or 0)
                if volume < rc.min_volume_usd:
                    continue
                no_price = _parse_no_ask(market)
                if no_price is None or no_price > rule.ceiling:
                    continue
                # Skip markets already resolved or marked closed
                if market.get("closed") or market.get("archived"):
                    continue
                # Skip short-fuse markets — need ≥3 days for the order to fill
                # and to match the time horizon the base rates were measured on.
                end_date_str = (event.get("endDate") or "")[:10]
                if end_date_str:
                    try:
                        days_left = (datetime.strptime(end_date_str, "%Y-%m-%d") - datetime.now()).days
                        if days_left < 3:
                            continue
                    except ValueError:
                        pass

                candidates.append({
                    "market_id": str(market.get("id", "")),
                    "condition_id": market.get("conditionId"),
                    "event_id": event_id,
                    "question": market.get("question", ""),
                    "category": category,
                    "no_price": no_price,
                    "volume": volume,
                    "end_date": (event.get("endDate") or "")[:10],
                })
        offset += len(events)
        if len(events) < 100:
            break

    if rc.fast_turnover:
        candidates.sort(key=lambda c: _FAST_TURNOVER_RANK.get(c["category"], 99))

    log.info("Scanner found %d candidates from %d events", len(candidates), seen_events)
    return candidates
