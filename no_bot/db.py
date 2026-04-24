"""SQLite persistence for no-bot positions. Uses the shared trading.db."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "trading.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS no_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id       TEXT NOT NULL,
    event_id        TEXT,
    question        TEXT,
    category        TEXT,
    entry_no_price  REAL,
    bet_size_usd    REAL,
    fee_paid_usd    REAL,
    placed_at       TEXT,
    resolved_at     TEXT,
    resolved_yes    INTEGER,
    pnl_usd         REAL,
    status          TEXT,
    mock            INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_no_pos_status ON no_positions(status);
CREATE INDEX IF NOT EXISTS idx_no_pos_event  ON no_positions(event_id);
CREATE INDEX IF NOT EXISTS idx_no_pos_market ON no_positions(market_id);

-- Append-only log of each scanner cycle. Dashboard reads the latest row
-- for "is the scanner alive?" and the last N for trend visibility.
CREATE TABLE IF NOT EXISTS no_bot_scan_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  TEXT NOT NULL,
    events_seen         INTEGER NOT NULL DEFAULT 0,
    candidates_found    INTEGER NOT NULL DEFAULT 0,
    positions_entered   INTEGER NOT NULL DEFAULT 0,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    error               TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_log_ts ON no_bot_scan_log(ts);

-- Snapshot of the most recent scan's candidate evaluations (pass + fail).
-- Overwritten every cycle so the table size stays bounded (~a few hundred rows).
-- Dashboard uses this to render "what is the scanner seeing right now?"
CREATE TABLE IF NOT EXISTS no_bot_scan_candidates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_ts         TEXT NOT NULL,
    event_id        TEXT,
    market_id       TEXT,
    question        TEXT,
    category        TEXT,
    no_price        REAL,
    volume_usd      REAL,
    end_date        TEXT,
    passed          INTEGER NOT NULL,
    reject_reason   TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_cand_ts ON no_bot_scan_candidates(scan_ts);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # Idempotent migration: mark-to-market column added 2026-04-24 for the
    # unrealized-loss accounting in the drawdown halt.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(no_positions)").fetchall()}
    if "last_known_no_price" not in cols:
        conn.execute("ALTER TABLE no_positions ADD COLUMN last_known_no_price REAL")
    conn.commit()
    return conn


def open_positions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, market_id, event_id, category, entry_no_price, bet_size_usd "
        "FROM no_positions WHERE status='open'"
    ).fetchall()
    return [
        dict(id=r[0], market_id=r[1], event_id=r[2], category=r[3],
             entry_no_price=r[4], bet_size_usd=r[5])
        for r in rows
    ]


def all_open_positions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, market_id, event_id, question, category, entry_no_price, "
        "bet_size_usd, placed_at, mock "
        "FROM no_positions WHERE status='open'"
    ).fetchall()
    return [
        dict(id=r[0], market_id=r[1], event_id=r[2], question=r[3],
             category=r[4], entry_no_price=r[5], bet_size_usd=r[6],
             placed_at=r[7], mock=r[8])
        for r in rows
    ]


def update_last_known_price(conn: sqlite3.Connection, position_id: int, no_price: float) -> None:
    conn.execute(
        "UPDATE no_positions SET last_known_no_price=? WHERE id=?",
        (no_price, position_id),
    )
    conn.commit()


def update_position_fill(
    conn: sqlite3.Connection, position_id: int,
    fill_price: float, filled_size_usd: float,
) -> None:
    """Update a position with the actual fill price and size after CLOB confirmation."""
    conn.execute(
        "UPDATE no_positions SET entry_no_price=?, bet_size_usd=? WHERE id=?",
        (fill_price, filled_size_usd, position_id),
    )
    conn.commit()


def close_position(
    conn: sqlite3.Connection, position_id: int,
    resolved_yes: int, pnl_usd: float, resolved_at: str,
) -> None:
    conn.execute(
        "UPDATE no_positions SET status='closed', resolved_yes=?, pnl_usd=?, "
        "resolved_at=? WHERE id=?",
        (resolved_yes, pnl_usd, resolved_at, position_id),
    )
    conn.commit()


def expire_position(conn: sqlite3.Connection, position_id: int) -> None:
    conn.execute(
        "UPDATE no_positions SET status='expired' WHERE id=?",
        (position_id,),
    )
    conn.commit()


def has_open_on_market(conn: sqlite3.Connection, market_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM no_positions WHERE market_id=? AND status='open' LIMIT 1",
        (market_id,),
    ).fetchone()
    return row is not None


def record_scan(
    conn: sqlite3.Connection, *, ts: str, events_seen: int,
    candidates_found: int, positions_entered: int, duration_ms: int,
    error: Optional[str] = None,
) -> None:
    conn.execute(
        """INSERT INTO no_bot_scan_log
           (ts, events_seen, candidates_found, positions_entered, duration_ms, error)
           VALUES (?,?,?,?,?,?)""",
        (ts, events_seen, candidates_found, positions_entered, duration_ms, error),
    )
    # Bound the log at ~1000 rows (~3.5 days at 5-min cadence).
    conn.execute(
        "DELETE FROM no_bot_scan_log WHERE id NOT IN "
        "(SELECT id FROM no_bot_scan_log ORDER BY id DESC LIMIT 1000)"
    )
    conn.commit()


def replace_scan_candidates(
    conn: sqlite3.Connection, scan_ts: str, rows: list[dict],
) -> None:
    """Overwrite the candidate snapshot with this scan's evaluations."""
    conn.execute("DELETE FROM no_bot_scan_candidates")
    if rows:
        conn.executemany(
            """INSERT INTO no_bot_scan_candidates
               (scan_ts, event_id, market_id, question, category,
                no_price, volume_usd, end_date, passed, reject_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (scan_ts, r.get("event_id"), r.get("market_id"), r.get("question"),
                 r.get("category"), r.get("no_price"), r.get("volume_usd"),
                 r.get("end_date"), 1 if r.get("passed") else 0, r.get("reject_reason"))
                for r in rows
            ],
        )
    conn.commit()


def insert_position(
    conn: sqlite3.Connection, *, market_id: str, event_id: Optional[str],
    question: str, category: str, entry_no_price: float, bet_size_usd: float,
    fee_paid_usd: float, placed_at: str, mock: bool = True,
) -> int:
    cur = conn.execute(
        """INSERT INTO no_positions
           (market_id, event_id, question, category, entry_no_price,
            bet_size_usd, fee_paid_usd, placed_at, status, mock)
           VALUES (?,?,?,?,?,?,?,?,'open',?)""",
        (market_id, event_id, question, category, entry_no_price,
         bet_size_usd, fee_paid_usd, placed_at, 1 if mock else 0),
    )
    conn.commit()
    return cur.lastrowid
