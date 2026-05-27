import sqlite3
import random
from datetime import datetime, timedelta

def seed_mock_data(db_path: str):
    """
    Clears the database tables and populates them with 30 days of realistic mock data
    demonstrating the 2x Kelly Copy-trading and No-Bot strategies.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Clear existing dynamic tables
    cursor.execute("DELETE FROM trades")
    cursor.execute("DELETE FROM balance_history")
    cursor.execute("DELETE FROM performance")
    cursor.execute("DELETE FROM server_status")
    
    # Ensure No-Bot tables exist and clear them
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS no_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL, event_id TEXT, question TEXT, category TEXT,
            entry_no_price REAL, bet_size_usd REAL, fee_paid_usd REAL,
            placed_at TEXT, resolved_at TEXT, resolved_yes INTEGER,
            pnl_usd REAL, status TEXT, mock INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS no_bot_scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, events_seen INTEGER NOT NULL DEFAULT 0,
            candidates_found INTEGER NOT NULL DEFAULT 0,
            positions_entered INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0, error TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS no_bot_scan_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_ts TEXT NOT NULL, event_id TEXT, market_id TEXT,
            question TEXT, category TEXT, no_price REAL, volume_usd REAL,
            end_date TEXT, passed INTEGER NOT NULL, reject_reason TEXT
        )
    """)
    
    cursor.execute("DELETE FROM no_positions")
    cursor.execute("DELETE FROM no_bot_scan_log")
    cursor.execute("DELETE FROM no_bot_scan_candidates")
    
    # 2. Seed Server Heartbeat (Live)
    cursor.execute("INSERT OR REPLACE INTO server_status (id, last_heartbeat) VALUES (1, datetime('now'))")
    
    # 3. Seed Performance Baseline and Harvested
    # Start at $100 baseline, harvested $35.0 so far
    cursor.execute("INSERT OR REPLACE INTO performance (id, baseline, total_harvested) VALUES (1, 100.0, 35.0)")
    
    # 4. Generate 30 days of Balance History showing growth and harvesting
    # Start 30 days ago at $100.0
    start_date = datetime.now() - timedelta(days=30)
    current_balance = 100.0
    baseline = 100.0
    harvested = 0.0
    
    balance_history_rows = []
    
    # We will simulate a steady upward trend with some dips.
    # When balance >= 2x baseline, we harvest 50% of the profit.
    # Let's seed points daily.
    random.seed(42)  # For deterministic seeding
    
    for i in range(30):
        day_date = start_date + timedelta(days=i)
        date_str = day_date.strftime("%Y-%m-%d")
        
        # Daily change: average +4% with some noise
        daily_pct = random.normalvariate(0.04, 0.08)
        current_balance *= (1.0 + daily_pct)
        
        # Keep balance bounded and realistic
        if current_balance < 30.0:
            current_balance = 30.0
            
        # Check for harvest trigger (2x baseline)
        harvested_today = 0.0
        if current_balance >= baseline * 2.0:
            profit = current_balance - baseline
            harvested_today = profit * 0.50
            current_balance -= harvested_today
            harvested += harvested_today
            baseline = current_balance  # New baseline established
            
        balance_history_rows.append((date_str, round(current_balance, 2), round(harvested, 2)))
        
    cursor.executemany(
        "INSERT INTO balance_history (date, balance, harvested) VALUES (?, ?, ?)",
        balance_history_rows
    )
    
    # 5. Seed Specialists Trades
    # Let's create a list of mock specialists (must match those in roster)
    specs = [
        {"name": "S-Works", "tier": "SHARP", "tags": "64,102366,100639"},
        {"name": "CemeterySun", "tier": "SHARP", "tags": "745,28,1,100639"},
        {"name": "beachboy4", "tier": "SHARP", "tags": "745,1,100639"},
        {"name": "reachingthesky", "tier": "SHARP", "tags": "100350,100977,1"},
        {"name": "aenews", "tier": "WHALE", "tags": "2,100265"},
        {"name": "LlamaEnjoyer", "tier": "WHALE", "tags": "2,100265"}
    ]
    
    # Ensure specialists are seeded in specialists table (mark active for demo)
    for s in specs:
        cursor.execute("""
            INSERT OR REPLACE INTO specialists (name, wallet_address, target_tags, tier, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (s["name"], f"0xmock{s['name'].lower()}address1234567890", s["tags"], s["tier"]))
        
    # Generate mock resolved & pending trades
    mock_questions = [
        # (category, question, slug)
        ("Politics", "Will Joe Biden visit France in June?", "biden-france-visit-june"),
        ("Politics", "Will USA impose new tariffs on steel by July?", "us-steel-tariffs-july"),
        ("NBA", "Will Boston Celtics win their next match by 10+ points?", "celtics-win-10-points"),
        ("Sports", "Will Lakers make the playoffs?", "lakers-playoffs-2026"),
        ("Esports", "Will Team Liquid win the Valorant tournament?", "liquid-valorant-win"),
        ("Soccer", "Will Real Madrid win UCL Final?", "real-madrid-ucl-final"),
        ("Politics", "Will UK re-enter the EU single market in 2026?", "uk-eu-single-market-2026"),
        ("Tech-AI", "Will Apple announce Siri integration with ChatGPT?", "apple-siri-chatgpt"),
        ("Tech-AI", "Will NVIDIA launch H200 chips ahead of schedule?", "nvidia-h200-launch"),
        ("Games", "Will GTA 6 release date be delayed to 2027?", "gta-6-delayed-2027")
    ]
    
    trades_to_insert = []
    
    # Resolved trades: 30 trades over the last month
    for i in range(35):
        spec = random.choice(specs)
        q = random.choice(mock_questions)
        
        # Generate date in the last 30 days
        trade_time = datetime.now() - timedelta(days=random.randint(1, 28), hours=random.randint(0, 23))
        ts_str = trade_time.strftime("%Y-%m-%d %H:%M:%S")
        
        entry_price = round(random.uniform(0.40, 0.75), 2)
        bet_size = round(random.choice([2.5, 5.0, 7.5, 10.0]), 2)
        
        # Outcome resolve: SHARP win rate ~60%, WHALE ~45%
        win_chance = 0.60 if spec["tier"] == "SHARP" else 0.45
        result = "WON" if random.random() < win_chance else "LOST"
        
        # End date
        end_date = (trade_time + timedelta(days=random.randint(1, 5))).strftime("%Y-%m-%d")
        
        # Leader price is close to entry price, market price is slightly different (slippage test)
        leader_p = entry_price
        market_p = round(entry_price + random.uniform(-0.02, 0.02), 2)
        
        trades_to_insert.append((
            spec["name"], q[1], entry_price, ts_str, result, q[2],
            "Yes", bet_size, end_date, leader_p, market_p
        ))
        
    # Pending trades: 4 active pending trades
    for i in range(4):
        spec = random.choice(specs)
        q = random.choice(mock_questions)
        trade_time = datetime.now() - timedelta(hours=random.randint(2, 48))
        ts_str = trade_time.strftime("%Y-%m-%d %H:%M:%S")
        entry_price = round(random.uniform(0.40, 0.70), 2)
        bet_size = round(random.choice([5.0, 7.5]), 2)
        end_date = (trade_time + timedelta(days=random.randint(3, 15))).strftime("%Y-%m-%d")
        leader_p = entry_price
        market_p = round(entry_price + random.uniform(-0.01, 0.01), 2)
        
        trades_to_insert.append((
            spec["name"], q[1], entry_price, ts_str, "PENDING", q[2],
            "Yes", bet_size, end_date, leader_p, market_p
        ))
        
    cursor.executemany("""
        INSERT INTO trades (
            specialist, market, entry_price, timestamp, result, slug,
            outcome, bet_size, end_date, leader_price, market_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, trades_to_insert)
    
    # 6. Seed No-Bot Live Positions
    # 3 open, 12 resolved
    no_bot_questions = [
        ("Tech-AI", "Will OpenAI announce GPT-5 before June 1, 2026?", "openai-gpt5-june"),
        ("Politics", "Will US Senate pass the climate bill by August?", "senate-climate-bill-august"),
        ("Sports-Other", "Will the Tour de France winner be from France?", "tour-de-france-french-winner"),
        ("Tech-AI", "Will Google Gemini surpass 5M active developers in Q2?", "gemini-5m-devs"),
        ("Politics", "Will Germany hold snap federal elections in 2026?", "germany-snap-elections-2026"),
        ("Sports-Other", "Will any player hit 4 home runs in one game in May?", "four-home-runs-may"),
        ("Tech-AI", "Will Meta release an open-source 500B Llama model by July?", "llama-500b-july")
    ]
    
    no_positions_rows = []
    
    # Closed positions
    for i in range(12):
        q = random.choice(no_bot_questions)
        entry_price = round(random.uniform(0.45, 0.58), 3)
        bet_size = round(random.choice([10.0, 15.0, 25.0]), 2)
        fee = round(bet_size * 0.0075, 4)
        placed_at = (datetime.now() - timedelta(days=random.randint(5, 25))).isoformat()
        resolved_at = (datetime.fromisoformat(placed_at) + timedelta(days=random.randint(1, 4))).isoformat()
        
        # 75% win rate for "Nothing Ever Happens" No-bot!
        won = random.random() < 0.75
        resolved_yes = 0 if won else 1
        pnl = round(bet_size * ((1.0 / entry_price) - 1.0) - fee - 0.0015, 2) if won else -bet_size
        
        no_positions_rows.append((
            f"mock_m_{i}", f"mock_e_{i}", q[1], q[0], entry_price, bet_size, fee,
            placed_at, resolved_at, resolved_yes, pnl, "resolved"
        ))
        
    # Open positions
    for i in range(3):
        q = random.choice(no_bot_questions)
        entry_price = round(random.uniform(0.48, 0.55), 3)
        bet_size = round(random.choice([15.0, 20.0]), 2)
        fee = round(bet_size * 0.0075, 4)
        placed_at = (datetime.now() - timedelta(hours=random.randint(4, 48))).isoformat()
        
        no_positions_rows.append((
            f"mock_m_open_{i}", f"mock_e_open_{i}", q[1], q[0], entry_price, bet_size, fee,
            placed_at, None, None, None, "open"
        ))
        
    cursor.executemany("""
        INSERT INTO no_positions (
            market_id, event_id, question, category, entry_no_price,
            bet_size_usd, fee_paid_usd, placed_at, resolved_at, resolved_yes,
            pnl_usd, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, no_positions_rows)
    
    # 7. Seed No-Bot Scan Logs (Last few scans)
    scan_log_rows = []
    for i in range(5):
        scan_time = datetime.now() - timedelta(minutes=(i * 5))
        scan_log_rows.append((
            scan_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            random.randint(120, 250), # events seen
            random.randint(3, 8),     # candidates found
            1 if i == 4 else 0,       # positions entered (only entered in 1 scan to keep it realistic)
            random.randint(800, 1800), # duration ms
            None
        ))
    cursor.executemany("""
        INSERT INTO no_bot_scan_log (
            ts, events_seen, candidates_found, positions_entered, duration_ms, error
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, scan_log_rows)
    
    # 8. Seed No-Bot Scan Candidates (Latest scan)
    latest_candidates = [
        ("Will OpenAI release GPT-5 before June 1, 2026?", "Tech-AI", 0.520, 184500.0, "2026-06-01", 1, None),
        ("Will Donald Trump create a new social media site in June?", "Politics", 0.820, 54200.0, "2026-07-01", 0, "No price 0.820 exceeds Politics ceiling (0.550)"),
        ("Will France win the 2026 FIFA World Cup?", "Sports-Other", 0.910, 950000.0, "2026-07-15", 0, "No price 0.910 exceeds Sports ceiling (0.550)"),
        ("Will Apple release an AR glasses product in May?", "Tech-AI", 0.350, 4800.0, "2026-06-01", 0, "Volume $4,800 is below minimum threshold ($10,000)"),
        ("Will EU fine Meta over $500M in May?", "Tech-AI", 0.490, 89000.0, "2026-05-31", 1, None)
    ]
    
    candidate_rows = []
    scan_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    for cand in latest_candidates:
        candidate_rows.append((
            scan_ts, "event_mock", "market_mock", cand[0], cand[1], cand[2], cand[3], cand[4], cand[5], cand[6]
        ))
        
    cursor.executemany("""
        INSERT INTO no_bot_scan_candidates (
            scan_ts, event_id, market_id, question, category, no_price,
            volume_usd, end_date, passed, reject_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, candidate_rows)
    
    conn.commit()
    conn.close()
    print("Mock database seeding completed successfully.")

if __name__ == "__main__":
    import os
    db_file = os.path.join(os.path.dirname(__file__), "trading.db")
    seed_mock_data(db_file)
