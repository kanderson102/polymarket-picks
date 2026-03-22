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
                    result TEXT DEFAULT 'PENDING'
                )
            """)
            
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
                    tier TEXT DEFAULT 'SHARP'
                )
            """)
            
            # Populate with defaults if empty
            cursor.execute("SELECT COUNT(*) FROM specialists")
            if cursor.fetchone()[0] == 0:
                defaults = [
                    ("S-Works", "0xee00ba338c59557141789b127927a55f5cc5cea1", "100383,100384,100401", "SHARP"),
                    ("1j59y6nk", "0x134240c2a99fa2a1cd9db6fc2caa65043259c997", "100101,100102,100381", "SHARP"),
                    ("reachingthesky", "0xefbc5fec8d7b0acdc8911bdd9a98d6964308f9a2", "100101,100102", "SHARP"),
                    ("HorizonSplendidView", "0x02227b8f5a9636e895607edd3185ed6ee5598ff7", "100383", "SHARP"),
                    ("CemeterySun", "0x37c1874a60d348903594a96703e0507c518fc53a", "100384,100401", "SHARP"),
                    ("aenews", "0x44c1dfe43260c94ed4f1d00de2e1f80fb113ebc1", "100701", "WHALE"),
                    ("LlamaEnjoyer", "0x9b979a065641e8cfde3022a30ed2d9415cf55e12", "100601", "WHALE")
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

    def add_trade(self, specialist: str, market: str, entry_price: float) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO trades (specialist, market, entry_price) VALUES (?, ?, ?)",
                (specialist, market, entry_price)
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
        """
        trades = self.get_specialist_recent_trades(specialist, 10)
        if not trades:
            return 100.0  # Default to 100% until proven otherwise
            
        wins = sum(1 for t in trades if t[0] == 'WON')
        return (wins / len(trades)) * 100

    def get_specialist_all_trades(self, specialist: str) -> List[Tuple]:
        """Fetch all historical trades placed by this bot for a specific specialist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT market, entry_price, timestamp, result 
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
                SELECT specialist, market, entry_price, timestamp, result 
                FROM trades 
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (limit,)
            )
            return cursor.fetchall()
            
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
            cursor.execute("SELECT name, wallet_address, target_tags, tier FROM specialists")
            rows = cursor.fetchall()
            return [{"name": r[0], "wallet": r[1], "tags": r[2].split(','), "tier": r[3]} for r in rows]
            
    def add_specialist(self, name: str, wallet: str, tags: str, tier: str = 'SHARP'):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
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
            cursor.execute("UPDATE specialists SET wallet_address = ? WHERE name = ?", (new_wallet, name))
            conn.commit()

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

