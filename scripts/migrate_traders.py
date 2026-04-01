"""
One-time migration script to update the live database with corrected specialist data.
Idempotent — safe to run multiple times.

Run: python migrate_traders.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "trading.db")

UPDATES = [
    # (name, wallet, tags, tier) — update existing
    ("S-Works", "0xee00ba338c59557141789b127927a55f5cc5cea1", "100101,100102,100381", "SHARP"),
    ("HorizonSplendidView", "0x02227b8f5a9636e895607edd3185ed6ee5598ff7", "100101,100102", "SHARP"),
    ("CemeterySun", "0x37c1874a60d348903594a96703e0507c518fc53a", "100381,100101,100384", "SHARP"),
    ("LlamaEnjoyer", "0x9b979a065641e8cfde3022a30ed2d9415cf55e12", "100801", "WHALE"),
]

REMOVE = ["1j59y6nk", "aenews"]

NEW_TRADERS = [
    ("beachboy4", "0xc2e7800b5af46e6093872b177b7a5e7f0563be51", "100381,100101,100102", "SHARP"),
    ("CERTuo", "0xf195721ad850377c96cd634457c70cd9e8308057", "100384", "SHARP"),
    ("majorexploiter", "0x019782cab5d844f02bafb71f512758be78579f3c", "100101,100102", "SHARP"),
]


def migrate():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # 1. Update existing traders with corrected tags
        for name, wallet, tags, tier in UPDATES:
            cursor.execute(
                "UPDATE specialists SET target_tags = ?, tier = ? WHERE name = ?",
                (tags, tier, name)
            )
            if cursor.rowcount:
                print(f"  ✅ Updated {name} → tags={tags}, tier={tier}")
            else:
                print(f"  ⏭️  {name} not found in DB (skipped)")

        # 2. Remove dead/broken wallets
        for name in REMOVE:
            cursor.execute("DELETE FROM specialists WHERE name = ?", (name,))
            if cursor.rowcount:
                print(f"  🗑️  Removed {name}")
            else:
                print(f"  ⏭️  {name} not found (already removed)")

        # 3. Add new traders (skip if already exist)
        for name, wallet, tags, tier in NEW_TRADERS:
            try:
                cursor.execute(
                    "INSERT INTO specialists (name, wallet_address, target_tags, tier) VALUES (?, ?, ?, ?)",
                    (name, wallet, tags, tier)
                )
                print(f"  ➕ Added {name} ({tier}) → tags={tags}")
            except sqlite3.IntegrityError:
                print(f"  ⏭️  {name} already exists (skipped)")

        conn.commit()

    # Verify final state
    print("\n📋 Final specialist roster:")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, wallet_address, target_tags, tier, is_active FROM specialists ORDER BY name")
        for row in cursor.fetchall():
            status = "🟢" if row[4] else "🔴"
            print(f"  {status} {row[0]:25s} | {row[3]:6s} | tags={row[2]}")


if __name__ == "__main__":
    print("🔄 Running trader roster migration...\n")
    migrate()
    print("\n✅ Migration complete!")
