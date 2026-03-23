"""
One-time fix: Update any trades with market-level slugs to use event-level slugs.
Run this on the server: python fix_slugs.py
"""
import sqlite3
import os

SLUG_FIXES = {
    # market slug -> correct event slug
    "us-x-iran-ceasefire-by-march-31": "us-x-iran-ceasefire-by",
}

def fix_slugs():
    db_path = os.path.join(os.path.dirname(__file__), "trading.db")
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        for old_slug, new_slug in SLUG_FIXES.items():
            cursor.execute(
                "UPDATE trades SET slug = ? WHERE slug = ?",
                (new_slug, old_slug)
            )
            if cursor.rowcount > 0:
                print(f"✅ Fixed {cursor.rowcount} trade(s): {old_slug} -> {new_slug}")
            else:
                print(f"ℹ️  No trades found with slug: {old_slug}")
        conn.commit()
    print("Done.")

if __name__ == "__main__":
    fix_slugs()
