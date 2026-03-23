"""
One-time fix: 
1. Update any trades with market-level slugs to use event-level slugs.
2. Backfill missing bet_size for old trades using the same formula bot used.

Run this on the server: python fix_slugs.py
"""
import sqlite3
import os

SLUG_FIXES = {
    # market slug -> correct event slug
    "us-x-iran-ceasefire-by-march-31": "us-x-iran-ceasefire-by",
}

# Same formula from finance.py: calculate_bet_size
# base_percent: SHARP=0.01, WHALE=0.02
# win_rate_multiplier: (win_rate / 50.0), default 100% for new traders = 2.0
# bet_size = balance * base_percent * win_rate_multiplier

SPECIALIST_TIERS = {
    "aenews": "WHALE",
    "LlamaEnjoyer": "WHALE",
    "S-Works": "SHARP",
    "1j59y6nk": "SHARP",
    "reachingthesky": "SHARP",
    "HorizonSplendidView": "SHARP",
    "CemeterySun": "SHARP",
}

def fix_slugs(cursor):
    for old_slug, new_slug in SLUG_FIXES.items():
        cursor.execute(
            "UPDATE trades SET slug = ? WHERE slug = ?",
            (new_slug, old_slug)
        )
        if cursor.rowcount > 0:
            print(f"✅ Fixed {cursor.rowcount} slug(s): {old_slug} -> {new_slug}")
        else:
            print(f"ℹ️  No trades found with slug: {old_slug}")

def backfill_bet_sizes(cursor):
    """Recalculate bet_size for trades where it's 0, replaying in chronological order."""
    cursor.execute(
        "SELECT id, specialist, entry_price FROM trades WHERE (bet_size IS NULL OR bet_size = 0) ORDER BY timestamp ASC"
    )
    trades_to_fix = cursor.fetchall()
    
    if not trades_to_fix:
        print("ℹ️  No trades need bet_size backfill.")
        return
    
    baseline = 50.0
    # Track running exposure to simulate what balance was at each trade
    running_exposure = 0.0
    
    for trade_id, specialist, entry_price in trades_to_fix:
        tier = SPECIALIST_TIERS.get(specialist, "SHARP")
        base_percent = 0.01 if tier == "SHARP" else 0.02
        win_rate = 100.0  # Default for new traders
        win_rate_multiplier = win_rate / 50.0
        
        available_balance = max(0.0, baseline - running_exposure)
        bet_size = available_balance * base_percent * win_rate_multiplier
        
        # Clamp to available balance
        if bet_size > available_balance:
            bet_size = available_balance
        
        cursor.execute("UPDATE trades SET bet_size = ? WHERE id = ?", (bet_size, trade_id))
        running_exposure += bet_size
        print(f"✅ Trade #{trade_id} ({specialist}): bet_size = ${bet_size:.2f} (balance was ${available_balance:.2f})")
    
    print(f"\n📊 Total backfilled: {len(trades_to_fix)} trades")

def main():
    db_path = os.path.join(os.path.dirname(__file__), "trading.db")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        print("=== Fixing Slugs ===")
        fix_slugs(cursor)
        
        print("\n=== Backfilling Bet Sizes ===")
        backfill_bet_sizes(cursor)
        
        conn.commit()
    print("\n✅ All done.")

if __name__ == "__main__":
    main()
