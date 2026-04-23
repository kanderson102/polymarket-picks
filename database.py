import os
import sqlite3
from typing import List, Tuple

class TradingDB:
    """
    SQLite database wrapper for tracking trades and performance metrics
    required by the 2x Growth-First Harvesting strategy.
    """
    
    def __init__(self, db_path=None):
        if db_path is None:
            self.db_path = os.path.join(os.path.dirname(__file__), "trading.db")
        else:
            self.db_path = db_path
        self._init_db()
        
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Trades Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    specialist TEXT NOT NULL,
                    market TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    result TEXT DEFAULT 'PENDING',
                    slug TEXT DEFAULT ''
                )
            """)
            
            # Migration — each column independently so existing ones don't block new ones
            for migration in [
                "ALTER TABLE trades ADD COLUMN slug TEXT DEFAULT ''",
                "ALTER TABLE trades ADD COLUMN outcome TEXT DEFAULT 'Yes'",
                "ALTER TABLE trades ADD COLUMN bet_size REAL DEFAULT 0",
                "ALTER TABLE trades ADD COLUMN end_date TEXT DEFAULT ''",
                "ALTER TABLE trades ADD COLUMN leader_price REAL DEFAULT 0",
                "ALTER TABLE trades ADD COLUMN market_price REAL DEFAULT 0",
            ]:
                try:
                    cursor.execute(migration)
                except sqlite3.OperationalError:
                    pass
            
            # Performance Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performance (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    baseline REAL NOT NULL,
                    total_harvested REAL DEFAULT 0.0
                )
            """)
            
            # Initialize performance row if it doesn't exist (assuming Phase 1 starting at $50)
            cursor.execute("""
                INSERT OR IGNORE INTO performance (id, baseline, total_harvested)
                VALUES (1, 50.0, 0.0)
            """)
            
            # Specialists Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS specialists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    wallet_address TEXT NOT NULL,
                    target_tags TEXT NOT NULL,
                    tier TEXT DEFAULT 'SHARP',
                    is_active BOOLEAN DEFAULT 1
                )
            """)
            
            # Migration for existing DBs
            try:
                cursor.execute("ALTER TABLE specialists ADD COLUMN is_active BOOLEAN DEFAULT 1")
            except sqlite3.OperationalError:
                pass # Column already exists

            # Populate with defaults if empty
            cursor.execute("SELECT COUNT(*) FROM specialists")
            if cursor.fetchone()[0] == 0:
                defaults = [
                    ("S-Works", "0xee00ba338c59557141789b127927a55f5cc5cea1", "64,102366,100639", "SHARP"),
                    ("reachingthesky", "0xefbc5fec8d7b0acdc8911bdd9a98d6964308f9a2", "100350,100977,1", "SHARP"),
                    ("HorizonSplendidView", "0x02227b8f5a9636e895607edd3185ed6ee5598ff7", "100350,100977,1", "SHARP"),
                    ("CemeterySun", "0x37c1874a60d348903594a96703e0507c518fc53a", "745,28,1,100639", "SHARP"),
                    ("aenews", "0x44c1dfe43260c94ed4f1d00de2e1f80fb113ebc1", "2,100265", "WHALE"),
                    ("LlamaEnjoyer", "0x9b979a065641e8cfde3022a30ed2d9415cf55e12", "2,100265", "WHALE"),
                    ("beachboy4", "0xc2e7800b5af46e6093872b177b7a5e7f0563be51", "745,1,100639", "SHARP"),
                    ("CERTuo", "0xf195721ad850377c96cd634457c70cd9e8308057", "100381,678,1", "SHARP"),
                    ("majorexploiter", "0x019782cab5d844f02bafb71f512758be78579f3c", "100350,306,82,1", "SHARP"),
                ]
                # Seed defaults as INACTIVE by default — user explicitly enables from UI.
                cursor.executemany(
                    "INSERT INTO specialists (name, wallet_address, target_tags, tier, is_active) VALUES (?, ?, ?, ?, 0)",
                    defaults,
                )

            # One-shot: for existing installs, deactivate all specialists so go-live
            # is an explicit user action from the UI. Runs exactly once.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    key TEXT PRIMARY KEY,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("SELECT 1 FROM schema_migrations WHERE key = 'specialists_default_inactive'")
            if cursor.fetchone() is None:
                cursor.execute("UPDATE specialists SET is_active = 0")
                cursor.execute("INSERT INTO schema_migrations (key) VALUES ('specialists_default_inactive')")

            # Server Heartbeat Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS server_status (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_heartbeat DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("INSERT OR IGNORE INTO server_status (id) VALUES (1)")
            
            conn.commit()

            # Balance History Table to drive front-end chart
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS balance_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE DEFAULT CURRENT_DATE,
                    balance REAL NOT NULL,
                    harvested REAL DEFAULT 0.0
                )
            """)

            # Bot Config Table — all tunable algorithm parameters
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    description TEXT DEFAULT ''
                )
            """)
            config_defaults = [
                ("sharp_bet_pct_low",          "5.0",  "SHARP bet % when balance < $200"),
                ("sharp_bet_pct_mid",          "3.0",  "SHARP bet % when balance $200–$999"),
                ("sharp_bet_pct_high",         "1.5",  "SHARP bet % when balance ≥ $1000"),
                ("whale_bet_pct_low",          "3.0",  "WHALE bet % when balance < $200"),
                ("whale_bet_pct_mid",          "2.0",  "WHALE bet % when balance $200–$999"),
                ("whale_bet_pct_high",         "1.0",  "WHALE bet % when balance ≥ $1000"),
                ("harvest_trigger_multiplier", "2.0",  "Harvest when balance reaches N× baseline"),
                ("harvest_transfer_pct",       "50.0", "% of profit to transfer to main wallet on harvest"),
                ("value_cap_sports",           "0.82", "Max entry price for sports markets (0–1)"),
                ("value_cap_politics",         "0.75", "Max entry price for politics/elections markets (0–1)"),
                ("slippage_threshold_pct",     "2.5",  "Max % price slippage before skipping a trade"),
                ("min_wallet_buffer",          "5.0",  "USDC to always keep in reserve"),
                ("sharp_min_win_rate",         "55.0", "Minimum win rate % to copy a SHARP specialist"),
                ("whale_min_win_rate",         "40.0", "Minimum win rate % to copy a WHALE specialist"),
                ("max_days_sports",            "60",   "Max days-to-expiry allowed for sports markets"),
                ("max_days_default",           "90",   "Max days-to-expiry allowed for non-sports markets"),
                ("poll_interval",              "30",   "Seconds between polling cycles"),
                ("enable_tag_filter",          "0",    "1 = only copy within specialist's domain tags, 0 = copy all"),
                ("enable_telegram",            "1",    "1 = send Telegram alerts, 0 = silent mode"),
                ("liquidity_multiple",         "2.0",  "Required order book liquidity as a multiple of bet size"),
            ]
            cursor.executemany(
                "INSERT OR IGNORE INTO bot_config (key, value, description) VALUES (?, ?, ?)",
                config_defaults
            )
            conn.commit()

    def add_trade(self, specialist: str, market: str, entry_price: float, slug: str = "", outcome: str = "Yes", bet_size: float = 0.0, end_date: str = "", leader_price: float = 0.0, market_price: float = 0.0) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO trades (specialist, market, entry_price, slug, outcome, bet_size, end_date, leader_price, market_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (specialist, market, entry_price, slug, outcome, bet_size, end_date, leader_price, market_price)
            )
            conn.commit()
            return cursor.lastrowid

    def update_trade_result(self, trade_id: int, result: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE trades SET result = ? WHERE id = ?",
                (result, trade_id)
            )
            conn.commit()

    def get_specialist_recent_trades(self, specialist: str, limit: int = 10) -> List[Tuple]:
        """
        Fetch the last X trades for a specialist to assess health (win rate).
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT result 
                FROM trades 
                WHERE specialist = ? AND result IN ('WON', 'LOST')
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (specialist, limit)
            )
            return cursor.fetchall()

    def get_specialist_win_rate(self, specialist: str) -> float:
        """
        Calculates the win rate of the specialist over their last 10 RESOLVED trades.
        Returns 50% (neutral 1.0x multiplier) for traders with fewer than 5 resolved trades,
        preventing untested traders from getting outsized bet allocations.
        """
        trades = self.get_specialist_recent_trades(specialist, 10)
        if len(trades) < 5:
            return 50.0  # Neutral multiplier until proven with ≥5 resolved trades
            
        wins = sum(1 for t in trades if t[0] == 'WON')
        return (wins / len(trades)) * 100

    def get_specialist_all_trades(self, specialist: str) -> List[Tuple]:
        """Fetch all historical trades placed by this bot for a specific specialist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT market, entry_price, timestamp, result, slug, outcome, bet_size, end_date, leader_price, market_price 
                FROM trades 
                WHERE specialist = ? 
                ORDER BY timestamp DESC
                """,
                (specialist,)
            )
            return cursor.fetchall()

    def get_performance(self) -> Tuple[float, float]:
        """Returns (baseline, total_harvested)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT baseline, total_harvested FROM performance WHERE id = 1")
            return cursor.fetchone()

    def update_performance_post_harvest(self, new_baseline: float, harvested_amount: float):
        """Updates baseline and adds to total harvested."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE performance SET baseline = ?, total_harvested = total_harvested + ? WHERE id = 1",
                (new_baseline, harvested_amount)
            )
            conn.commit()

    def get_all_recent_trades(self, limit: int = 50) -> List[Tuple]:
        """Fetch the most recent trades across all specialists for global monitoring."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT specialist, market, entry_price, timestamp, result, slug, outcome, bet_size, end_date, leader_price, market_price 
                FROM trades 
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (limit,)
            )
            return cursor.fetchall()
            
    def clear_all_pending_trades(self):
        """Purge all pending trades from the simulation to free up paper capital."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trades WHERE result = 'PENDING'")
            conn.commit()
            
    def get_balance_history(self) -> List[Tuple]:
        """Fetch balance history points for the chart."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT date, balance, harvested FROM balance_history ORDER BY date ASC"
            )
            return cursor.fetchall()

    def add_balance_snapshot(self, current_balance: float, harvested_today: float = 0.0):
        """Add a daily balance point for the history chart."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO balance_history (date, balance, harvested) VALUES (CURRENT_DATE, ?, ?)",
                (current_balance, harvested_today)
            )
            conn.commit()

    def get_all_specialists(self) -> List[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, wallet_address, target_tags, tier, is_active FROM specialists")
            rows = cursor.fetchall()
            return [{"name": r[0], "wallet": r[1], "tags": r[2].split(','), "tier": r[3], "is_active": bool(r[4])} for r in rows]
            
    def add_specialist(self, name: str, wallet: str, tags: str, tier: str = 'SHARP'):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Wallet address deduplication — prevent adding the same wallet twice
            cursor.execute("SELECT name FROM specialists WHERE wallet_address = ?", (wallet,))
            existing = cursor.fetchone()
            if existing:
                raise ValueError(f"Wallet {wallet} is already assigned to specialist '{existing[0]}'")
            cursor.execute("INSERT INTO specialists (name, wallet_address, target_tags, tier) VALUES (?, ?, ?, ?)", (name, wallet, tags, tier))
            conn.commit()
            
    def delete_specialist(self, name: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM specialists WHERE name = ?", (name,))
            conn.commit()
            
    def update_specialist_wallet(self, name: str, new_wallet: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Wallet address deduplication — prevent reassigning to an existing wallet
            cursor.execute("SELECT name FROM specialists WHERE wallet_address = ? AND name != ?", (new_wallet, name))
            existing = cursor.fetchone()
            if existing:
                raise ValueError(f"Wallet {new_wallet} is already assigned to specialist '{existing[0]}'")
            cursor.execute("UPDATE specialists SET wallet_address = ? WHERE name = ?", (new_wallet, name))
            conn.commit()

    def update_specialist_tags(self, name: str, new_tags: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE specialists SET target_tags = ? WHERE name = ?", (new_tags, name))
            conn.commit()
            
    def set_specialist_active(self, name: str, is_active: bool):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE specialists SET is_active = ? WHERE name = ?", (int(is_active), name))
            conn.commit()
            
    def get_specialist_pending_count(self, specialist: str) -> int:
        """Count how many PENDING trades a specialist currently has open."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trades WHERE specialist = ? AND result = 'PENDING'", (specialist,))
            return cursor.fetchone()[0]

    def get_total_pending_exposure(self) -> float:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Use bet_size when available, fall back to entry_price for old trades
            cursor.execute("SELECT sum(CASE WHEN bet_size > 0 THEN bet_size ELSE entry_price END) FROM trades WHERE result = 'PENDING'")
            res = cursor.fetchone()[0]
            return float(res) if res else 0.0

    def record_heartbeat(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE server_status SET last_heartbeat = CURRENT_TIMESTAMP WHERE id = 1")
            conn.commit()
            
    def is_server_alive(self) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT (julianday('now') - julianday(last_heartbeat)) * 86400 FROM server_status WHERE id = 1")
            row = cursor.fetchone()
            if row:
                seconds_ago = row[0]
                return seconds_ago <= 120 # Alive if heartbeat was within 2 mins
            return False

    def get_stale_pending_trades(self, grace_days: int = 3, max_age_days: int = 45) -> list[dict]:
        """Fetch PENDING trades that are past their end_date + grace period,
        or older than max_age_days with no end_date. These are candidates for expiration."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, specialist, market, entry_price, slug, outcome, bet_size, end_date, timestamp
                FROM trades
                WHERE result = 'PENDING' AND (
                    (end_date != '' AND date(end_date, '+' || ? || ' days') < date('now'))
                    OR
                    (end_date = '' AND julianday('now') - julianday(timestamp) > ?)
                )
                ORDER BY timestamp ASC
            """, (grace_days, max_age_days))
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0], "specialist": r[1], "market": r[2],
                    "entry_price": r[3], "slug": r[4], "outcome": r[5],
                    "bet_size": r[6], "end_date": r[7], "timestamp": r[8],
                }
                for r in rows
            ]

    def get_pending_trades_for_resolution(self) -> list[dict]:
        """Fetch all PENDING trades with their slugs and outcomes for resolution checking."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, specialist, market, entry_price, slug, outcome, bet_size
                FROM trades
                WHERE result = 'PENDING' AND slug != ''
                ORDER BY timestamp ASC
            """)
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0], "specialist": r[1], "market": r[2],
                    "entry_price": r[3], "slug": r[4], "outcome": r[5],
                    "bet_size": r[6]
                }
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Bot Configuration
    # ------------------------------------------------------------------

    def get_config(self, key: str, default=None):
        """Return a single config value by key, or default if not found."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM bot_config WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    def get_all_config(self) -> dict:
        """Return all config rows as {key: {value, description}}."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value, description FROM bot_config ORDER BY key")
            return {r[0]: {"value": r[1], "description": r[2]} for r in cursor.fetchall()}

    def set_config(self, key: str, value) -> None:
        """Upsert a config value, preserving the existing description."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO bot_config (key, value, description)
                VALUES (?, ?, COALESCE((SELECT description FROM bot_config WHERE key = ?), ''))
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value), key)
            )
            conn.commit()

