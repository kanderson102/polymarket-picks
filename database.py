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
                    ("S-Works", "0xee00ba338c59557141789b127927a55f5cc5cea1", "100101,100102,100381", "SHARP"),
                    ("reachingthesky", "0xefbc5fec8d7b0acdc8911bdd9a98d6964308f9a2", "100101,100102", "SHARP"),
                    ("HorizonSplendidView", "0x02227b8f5a9636e895607edd3185ed6ee5598ff7", "100383", "SHARP"),
                    ("CemeterySun", "0x37c1874a60d348903594a96703e0507c518fc53a", "100384,100401", "SHARP"),
                    ("aenews", "0x44c1dfe43260c94ed4f1d00de2e1f80fb113ebc1", "100701", "WHALE"),
                    ("LlamaEnjoyer", "0x9b979a065641e8cfde3022a30ed2d9415cf55e12", "100801", "WHALE"),
                    ("beachboy4", "0xc2e7800b5af46e6093872b177b7a5e7f0563be51", "100381,100101,100102", "SHARP"),
                    ("CERTuo", "0xf195721ad850377c96cd634457c70cd9e8308057", "100384", "SHARP"),
                    ("majorexploiter", "0x019782cab5d844f02bafb71f512758be78579f3c", "100101,100102", "SHARP"),
                ]
                cursor.executemany("INSERT INTO specialists (name, wallet_address, target_tags, tier) VALUES (?, ?, ?, ?)", defaults)
                
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
                WHERE specialist = ? AND result != 'PENDING'
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

