#!/usr/bin/env bash
# Daily backup of trading.db. Run from cron on the Hetzner server.
#
# Cron line (every day at 03:30 UTC):
#   30 3 * * * /root/polymarket-picks/scripts/backup_db.sh >> /var/log/polymarket-backup.log 2>&1
#
# Uses `sqlite3 .backup` (the online-backup API) so it's safe to run while
# the bot is writing. Keeps the last 14 daily backups.

set -euo pipefail

REPO=/root/polymarket-picks
DB=$REPO/trading.db
DEST=/root/backups/polymarket
KEEP=14

mkdir -p "$DEST"

stamp=$(date -u +%Y%m%d-%H%M%S)
out="$DEST/trading-$stamp.db"

sqlite3 "$DB" ".backup '$out'"
gzip -9 "$out"

# Prune to KEEP newest
ls -1t "$DEST"/trading-*.db.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "[$(date -u +%FT%TZ)] backup ok: ${out}.gz"
