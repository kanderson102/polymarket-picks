# Server Runbook

VPS: `135.181.80.177` (Hetzner)  
App runs in a single Docker container. Dashboard at `http://135.181.80.177:8501`.

---

## SSH in

```bash
ssh root@135.181.80.177
```

---

## Docker basics

```bash
# List running containers (get the container name)
docker ps

# Follow live logs (both bot + dashboard output)
docker logs -f <container>

# Open a shell inside the container
docker exec -it <container> bash

# Restart the container (redeploys current image)
docker restart <container>

# Full rebuild + restart (after code changes on the server)
cd /root/polymarket-picks
docker compose down && docker compose up -d --build
```

---

## Deploy latest code from GitHub

```bash
ssh root@135.181.80.177
cd /root/polymarket-picks
git pull
docker compose down && docker compose up -d --build
```

No need to restart if you only changed `.env` — restart is enough:
```bash
docker restart <container>
```

---

## Copy a file from Mac → container

`scp` lands on the host filesystem, not inside the container. Two steps:

```bash
# 1. Copy to host
scp localfile.txt root@135.181.80.177:/root/polymarket-picks/localfile.txt

# 2. Copy from host into container
ssh root@135.181.80.177 "docker cp /root/polymarket-picks/localfile.txt <container>:/app/localfile.txt"
```

**Shortcut — copy markets.db in one command from your Mac:**
```bash
CONTAINER=$(ssh root@135.181.80.177 "docker ps --format '{{.Names}}'")
ssh root@135.181.80.177 "docker cp /root/polymarket-picks/backtest/markets.db $CONTAINER:/app/backtest/markets.db"
```

---

## Verify a file exists inside the container

```bash
docker exec <container> ls -lh /app/backtest/markets.db
docker exec <container> ls -lh /app/trading.db
```

---

## Run a one-off script inside the container

```bash
# Re-fetch backtest market data (takes 10–30 min)
docker exec <container> python3 backtest/fetch_markets.py --tags-only

# Run the no-bot scanner once (paper mode)
docker exec <container> python3 -m no_bot

# Regenerate backtest charts
docker exec <container> python3 backtest/deep_analysis.py
```

---

## Check bot health

```bash
# Last 100 lines of logs
docker logs --tail 100 <container>

# Watch for errors only
docker logs -f <container> 2>&1 | grep -i "error\|critical\|exception"

# Check trading DB from host (needs sqlite3 installed on host)
docker exec <container> sqlite3 /app/trading.db "SELECT COUNT(*) FROM trades;"
```

---

## Edit .env on server

```bash
ssh root@135.181.80.177
nano /root/polymarket-picks/.env
docker restart <container>
```

---

## Stop / start

```bash
docker stop <container>    # graceful stop
docker start <container>   # start stopped container
docker restart <container> # stop + start
```

---

## Common gotchas

| Problem | Cause | Fix |
|---------|-------|-----|
| Dashboard shows stale data | `markets.db` on host, not in container | `docker cp` it in (see above) |
| Code changes not reflected | Image not rebuilt | `docker compose up -d --build` |
| Bot not trading | `COPY_BOT_LIVE=false` in `.env` | Edit `.env`, restart |
| No-bot not entering | `NO_BOT_LIVE=false` or bankroll env not set | Edit `.env`, restart |
| Port 8501 unreachable | Container stopped or firewall | `docker ps` to check, then `ufw allow 8501` if needed |
