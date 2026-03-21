import sqlite3
from typing import List, Tuple, Optional

class TradingDB:
    """
    SQLite database wrapper for tracking trades and performance metrics
    required by the 2x Growth-First Harvesting strategy.
    """
    
    def __init__(self, db_path: str = "trading.db"):
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

