"""
Fetch all resolved Polymarket events from the Gamma API and store in markets.db.

Paginates through closed events, extracts Yes/No markets with clear outcomes,
maps tags to categories, and writes to SQLite for analysis.
"""

from __future__ import annotations

import json
import sqlite3
import time
import requests
from pathlib import Path
from typing import Optional

GAMMA_API = "https://gamma-api.polymarket.com"
DB_PATH = Path(__file__).parent / "markets.db"
BATCH_SIZE = 100
SLEEP_BETWEEN_BATCHES = 0.3  # seconds, polite rate limiting

# ──────────────────────────────────────────────────────────────────────────────
# Tag → Category mapping
# ──────────────────────────────────────────────────────────────────────────────

# Map tag IDs to broad category names. A market inherits the first matching
# category in priority order (more specific first).
CATEGORY_MAP = [
    # Exclude / low-signal (recurring automated markets)
    ({"101757"},                                        "Recurring"),
    ({"102127"},                                        "UpOrDown"),

    # Crypto
    ({"21", "1312", "235", "39", "818", "620"},         "Crypto"),

    # Sports
    ({"745", "28"},                                     "Sports-Basketball"),
    ({"100350", "306", "82", "100977", "1234"},         "Sports-Soccer"),
    ({"100381", "678"},                                  "Sports-Baseball"),
    ({"899", "100088", "100089"},                        "Sports-Hockey"),
    ({"64", "102366", "100639"},                        "Sports-Esports"),
    ({"1"},                                              "Sports-Other"),

    # Politics / Geopolitics
    ({"2", "144", "100265", "100344"},                  "Politics"),

    # Economics / Finance (stocks, rates, ETFs, IPOs, macro)
    ({"370", "131", "833", "600", "102000", "101247"}, "Economics"),

    # Equities / Stocks (daily price markets — different character than macro)
    ({"102516"},                                        "Stocks-Daily"),

    # Science / Tech / AI
    ({"537", "817", "267"},                             "Tech-AI"),

    # Pop Culture / Entertainment
    ({"1164", "330"},                                   "Entertainment"),

    # Catch-all
    ({"100215"},                                        "General"),
]

SPORTS_CATEGORIES = {
    "Sports-Basketball", "Sports-Soccer", "Sports-Baseball",
    "Sports-Hockey", "Sports-Esports", "Sports-Other"
}


def categorize(tag_ids: set[str]) -> str:
    for tag_set, category in CATEGORY_MAP:
        if tag_ids & tag_set:
            return category
    return "Other"


# ──────────────────────────────────────────────────────────────────────────────
# Database setup
# ──────────────────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS markets (
            id          TEXT PRIMARY KEY,
            question    TEXT,
            event_id    TEXT,
            event_title TEXT,
            tag_ids     TEXT,   -- JSON array of tag ID strings
            tag_labels  TEXT,   -- JSON array of tag label strings
            category    TEXT,
            resolved_yes INTEGER,  -- 1=Yes won, 0=No won
            start_date  TEXT,
            end_date    TEXT,
            volume      REAL,
            liquidity   REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON markets(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resolved ON markets(resolved_yes)")
    conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Outcome parsing
# ──────────────────────────────────────────────────────────────────────────────

def parse_yes_no_outcome(market: dict) -> Optional[int]:
    """
    Returns 1 if Yes won, 0 if No won, None if indeterminate/invalid.
    Only handles binary Yes/No markets with a clear winner (price > 0.9).
    """
    try:
        outcomes = json.loads(market.get("outcomes", "[]"))
        prices_raw = json.loads(market.get("outcomePrices", "[]"))
    except (json.JSONDecodeError, TypeError):
        return None

    if len(outcomes) != 2 or len(prices_raw) != 2:
        return None
    if outcomes[0].lower() not in ("yes",) or outcomes[1].lower() not in ("no",):
        return None

    try:
        yes_price = float(prices_raw[0])
        no_price = float(prices_raw[1])
    except (ValueError, TypeError):
        return None

    if yes_price > 0.9:
        return 1
    if no_price > 0.9:
        return 0
    return None  # voided / unresolved / multi-outcome


# ──────────────────────────────────────────────────────────────────────────────
# Fetching
# ──────────────────────────────────────────────────────────────────────────────

def fetch_events_page(offset: int, tag_id: Optional[str] = None) -> list[dict]:
    params: dict = {"closed": "true", "limit": BATCH_SIZE, "offset": offset,
                    "order": "startDate", "ascending": "false"}
    if tag_id:
        params["tag_id"] = tag_id
    resp = requests.get(f"{GAMMA_API}/events", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def process_event(event: dict, conn: sqlite3.Connection) -> "tuple[int, int]":
    """Process one event. Returns (markets_inserted, markets_skipped)."""
    event_id = str(event.get("id", ""))
    event_title = event.get("title", "")
    start_date = event.get("startDate", "")[:10]
    end_date = event.get("endDate", "")[:10]

    tag_ids = [str(t["id"]) for t in event.get("tags", []) if isinstance(t, dict)]
    tag_labels = [str(t.get("label", "")) for t in event.get("tags", []) if isinstance(t, dict)]
    category = categorize(set(tag_ids))

    inserted = skipped = 0
    for market in event.get("markets", []):
        market_id = str(market.get("id", ""))
        if not market_id:
            skipped += 1
            continue

        resolved_yes = parse_yes_no_outcome(market)
        if resolved_yes is None:
            skipped += 1
            continue

        try:
            conn.execute(
                """INSERT OR IGNORE INTO markets
                   (id, question, event_id, event_title, tag_ids, tag_labels,
                    category, resolved_yes, start_date, end_date, volume, liquidity)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    market_id,
                    market.get("question", ""),
                    event_id,
                    event_title,
                    json.dumps(tag_ids),
                    json.dumps(tag_labels),
                    category,
                    resolved_yes,
                    start_date,
                    end_date,
                    float(market.get("volumeNum", 0) or 0),
                    float(market.get("liquidityNum", 0) or 0),
                ),
            )
            inserted += 1
        except sqlite3.Error:
            skipped += 1

    return inserted, skipped


def fetch_by_tag(tag_id: str, label: str, conn: sqlite3.Connection,
                 max_events: int = 0) -> None:
    """Fetch all closed events for a specific tag ID."""
    total_inserted = total_skipped = 0
    offset = 0
    print(f"  Fetching tag={tag_id} ({label})...")

    while True:
        try:
            events = fetch_events_page(offset, tag_id=tag_id)
        except requests.RequestException as e:
            print(f"    Request error at offset {offset}: {e}. Retrying in 5s...")
            time.sleep(5)
            continue

        if not events:
            break

        for event in events:
            ins, skip = process_event(event, conn)
            total_inserted += ins
            total_skipped += skip

        conn.commit()
        offset += BATCH_SIZE

        if max_events and offset >= max_events:
            break

        time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"    → inserted {total_inserted:,}, skipped {total_skipped:,}")


def fetch_all(max_events: int = 0, tags_only: bool = False) -> None:
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    existing = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    print(f"Starting fetch. DB already has {existing:,} markets.")

    # Tag-targeted fetches for categories that matter most
    # (Crypto recurring markets flood unfiltered pagination, so we target explicitly)
    TARGET_TAGS = [
        # Politics / Government / Law
        ("2",      "Politics"),
        ("144",    "Elections"),
        ("100265", "Geopolitics"),
        ("100344", "House Races"),
        # Economics / Finance
        ("370",    "GDP"),
        ("131",    "Interest Rates"),
        ("833",    "ETF"),
        ("600",    "IPOs"),
        # Science / Tech / AI
        ("537",    "OpenAI"),
        ("817",    "AGI"),
        # Pop Culture / Entertainment
        ("1164",   "Hollywood"),
        # Sports (controlled fetch)
        ("745",    "NBA"),
        ("100350", "Soccer"),
        ("100381", "MLB"),
        ("899",    "NHL"),
        ("64",     "Esports"),
        ("1",      "Sports"),
    ]

    if tags_only:
        for tag_id, label in TARGET_TAGS:
            fetch_by_tag(tag_id, label, conn, max_events=max_events)
    else:
        # Also do an unfiltered pass (catches General/Other markets)
        total_inserted = total_skipped = 0
        offset = 0
        print("Fetching unfiltered...")
        while True:
            try:
                events = fetch_events_page(offset)
            except requests.RequestException as e:
                print(f"  Request error at offset {offset}: {e}. Retrying in 5s...")
                time.sleep(5)
                continue

            if not events:
                print("No more events. Done with unfiltered pass.")
                break

            for event in events:
                ins, skip = process_event(event, conn)
                total_inserted += ins
                total_skipped += skip

            conn.commit()
            offset += BATCH_SIZE

            if offset % 1000 == 0:
                total_in_db = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
                print(f"  offset={offset:>7,}  inserted={total_inserted:>6,}  "
                      f"skipped={total_skipped:>6,}  total_in_db={total_in_db:>7,}")

            if max_events and offset >= max_events:
                print(f"Reached max_events={max_events}. Stopping unfiltered pass.")
                break

            time.sleep(SLEEP_BETWEEN_BATCHES)

        print(f"\nDone unfiltered. Inserted {total_inserted:,}.")

        # Now do targeted tag fetches
        print("\nRunning targeted tag fetches...")
        for tag_id, label in TARGET_TAGS:
            fetch_by_tag(tag_id, label, conn)

    total_in_db = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    print(f"\nTotal in DB: {total_in_db:,}")

    print("\nMarkets by category:")
    for row in conn.execute(
        "SELECT category, COUNT(*) as n, SUM(resolved_yes) as yes_count "
        "FROM markets GROUP BY category ORDER BY n DESC"
    ):
        cat, n, yes_count = row
        no_rate = (n - yes_count) / n * 100 if n > 0 else 0
        print(f"  {cat:<25} {n:>8,} markets  No rate: {no_rate:.1f}%")

    conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch Polymarket resolved markets")
    parser.add_argument("--max-events", type=int, default=0,
                        help="Stop after this many events per tag (0=all)")
    parser.add_argument("--tags-only", action="store_true",
                        help="Only fetch tag-targeted events (skip unfiltered pass)")
    args = parser.parse_args()
    fetch_all(max_events=args.max_events, tags_only=args.tags_only)
