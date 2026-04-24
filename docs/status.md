# Project Status — living doc

**Owner:** Kyle · **Last updated:** 2026-04-24

This is the single source of truth for "where are we right now" on the Polymarket bots. Update it at the end of every working session — don't let it go stale. If something listed here is done or wrong, fix the entry in the same commit.

Sections:
1. [Current status](#current-status)
2. [Paper-trading health check](#paper-trading-health-check)
3. [TODO — before going live](#todo--before-going-live)
4. [TODO — nice-to-haves](#todo--nice-to-haves)
5. [Open questions](#open-questions)
6. [Changelog](#changelog)

---

## Current status

**Phase:** Paper trading / dry-run. Neither bot has executed real money.

**Deployment:** Hetzner VPS `135.181.80.177`, Docker, dashboard at `:8501`. Both `bot.py` (copy-bot) and `python -m no_bot` (no-bot) launched from `start.sh`.

**Copy-bot (`bot.py`)** — *disabled.* Process boots in heartbeat-only mode (no WebSocket, no specialist polling, no trade copying) to keep `server_status` fresh for the dashboard. Gated by `COPY_BOT_ENABLED` env var (default `false`). Re-enable by setting `COPY_BOT_ENABLED=true` in `.env`.

**No-bot (`python -m no_bot`)** — *this is the active bet.*
- `NO_BOT_DRY_RUN` defaults to `true`. In both dry-run and pure-paper mode the bot writes `mock=1` rows to `no_positions` at the scanner's No price — so we do get a paper equity curve.
- `nb_live_mode` config flag in DB: **0** (paper). Flip from Settings → No-Bot → "Live mode" to enable real CLOB submission (also requires `NO_BOT_DRY_RUN=false` in `.env`).
- Scan interval: 5 min · Resolve interval: 10 min.
- **No WebSocket.** The `ws_entry.py` in [no-bot-architecture.md](no-bot-architecture.md) is a design, not code — the no-bot currently does pure HTTP polling. Existing [ws_listener.py](../ws_listener.py) is copy-bot only.
- 0 `no_positions` rows in local `trading.db`. The production DB on the server is authoritative — the local copy is stale (heartbeat `2026-03-22`).

### How the scan actually works (clarification)

Every 5 min the scanner pulls `/events?closed=false` from Gamma (paginated, up to 500 events per cycle — see [scanner.py:104-163](../no_bot/scanner.py)). It re-evaluates **every currently-open event**, not just newly-listed ones. So a market sitting at No=0.80 today gets re-checked every scan; the moment it dips to ≤ ceiling (0.55–0.60), we enter on the next cycle. This is the "tracking everything live" behavior you wanted — just on a 5-min cadence rather than streaming.

**Why the ≥3-day-to-resolution filter:**
1. Need enough time for a limit order to actually fill at your price.
2. Base rates were measured on markets with typical horizons (Sports-Other ~12d median, Politics ~33d, Tech-AI ~75d). A market with hours left behaves differently (sentiment locked in, illiquid) — it's outside the distribution the edge was calibrated on.

**WebSocket vs 5-min polling — is it a blocker?** No, for our strategy. The edge is "be in-range at entry," not "catch a 90-second dip." Polling catches every multi-hour price state. Adding the WebSocket dip-detector (design in [no-bot-architecture.md](no-bot-architecture.md) "WebSocket entry signal") would slightly improve fills by waiting for intra-hour pumps to revert, but only marginally — it's an optimization, not a prerequisite.

**Known-stale artifacts in the repo root:** `bot.log`, `polymarket_bot.log` are empty 0-byte files from March. Real logs live inside the Docker container on the server (`docker logs -f <container>`).

---

## Paper-trading health check

> *"It's been a day since starting the bot — how do I know it's working?"*

The **dashboard alone cannot answer this today.** It shows positions once taken, but not what the scanner sees, so an idle scanner is indistinguishable from a broken one. Until we add a candidate feed (see TODO below), check these by SSHing to the server:

```bash
ssh root@135.181.80.177
docker logs --tail 200 <container> | grep no_bot
```

Expected healthy output, every 5 min:
```
no_bot: [paper] bankroll=$50.00 deployed=$0.00 open=0 …
no_bot.scanner: Scanner found N candidates from M events
no_bot: candidates=N
```

If `candidates=0` persistently, that is **consistent with the strategy**, not a bug:
- Binary-matchup filter (single-market events only) rejects most of Polymarket.
- No-price ceiling: Tech-AI ≤0.60, Politics ≤0.55, Sports-Other ≤0.55.
- Volume floor: $10k lifetime.
- ≥3 days to resolution.
- Estimated **~150–300 qualifying bets per year** at current config ([strategy.md](no-bot-strategy.md)). That's one every 1–2 days on average — one idle day is not evidence of failure.

If `Scanner found 0 candidates from 0 events` → Gamma API connection is broken. That's a real bug.

---

## TODO — before going live

Ordered rough-critical first. Tick (`[x]`) as we complete.

- [ ] **Dashboard: live candidate feed.** Show the last N markets the scanner *considered* (pass + fail + reason) for our 3 categories. Without this we can't verify "connected and working" at a glance. See open question 1.
- [ ] **Dashboard: scanner last-run timestamp + per-scan summary.** Distinguish "no candidates today" from "scanner hasn't run in 4 hours." Write a `no_bot_status` row each scan (last_run, events_seen, candidates_found) and surface it on the dashboard.
- [ ] **Wallet funding + key review.** Confirm `BOT_PRIVATE_KEY` on server is a dedicated wallet (not Kyle's personal), funded with the intended bankroll only, and `HARVEST_WALLET_ADDRESS` is correct. Document the funded amount here once confirmed.
- [ ] **First live no-bot bet plan.** Decide starting bankroll ($50? $500?) and what success/failure looks like over the first ~10 bets before scaling.
- [ ] **Verify executor pre-flight checks.** `no_bot/executor.py` should check `getBook` for liquidity and reject on stale price before signing. Confirm this is wired and tested against a live market.
- [ ] **Drawdown halt tested.** `_check_drawdown` in [__main__.py](../no_bot/__main__.py) only triggers on closed-position losses. Unrealized losses on open positions don't count. Decide whether that's correct.
- [ ] **Alerting.** Telegram/Discord webhook on: new bet entered, resolution booked, drawdown halt tripped, scanner exception loop. Currently errors only land in `docker logs`.
- [ ] **Backup of `trading.db`** on a cron from the server. Once real positions exist, losing this file = losing position history.

## TODO — nice-to-haves

- [ ] WebSocket-driven entry-timing refinement for no-bot — 30-min rolling median dip detector, design in [no-bot-architecture.md](no-bot-architecture.md). Would improve fill prices ~5-10% by catching Yes-sentiment pumps just before they revert. Not a blocker; 5-min polling is adequate for days-to-months-horizon markets.
- [ ] Revisit category base rates quarterly — strategy doc flags a possible 2026 efficiency regression.
- [ ] Consolidate logging: right now `bot.log` / `polymarket_bot.log` at repo root are empty and misleading; either wire them up or delete.

---

## Open questions

1. **Candidate feed UX.** Should the dashboard show a rolling log of every scan (scrolling by default) or just the most recent scan's full candidate set with pass/fail reasons? Latter is probably cleaner; former is better for debugging.
2. **Paper P&L tracking.** When `nb_live_mode=0`, no positions are written at all (pure paper mode skips the DB path — see `__main__.py` lines ~123-127). Do we want paper mode to still write `mock=1` rows so we can see a simulated equity curve on the dashboard? That would directly answer "is this working?"
3. **Go-live trigger.** What's the explicit criterion to flip `nb_live_mode` → 1? E.g. "≥30 days of paper trading and paper ROI within 20% of backtest expectation"? Right now it's undefined.
4. **Server observability.** Do we need a lightweight uptime check (e.g. cronitor, healthchecks.io) pinging the container, or is `docker logs` enough?
5. **Retire or keep copy-bot?** We're not investing in it. Keep it booting (harmless, heartbeat useful) or remove it from `start.sh` and delete dead code?

---

## Go-live

See [go-live-checklist.md](go-live-checklist.md) for the explicit flip criteria.

## Changelog

- **2026-04-24** — Doc created. Current phase: paper/dry-run, 0 positions taken, deployment on Hetzner verified via runbook. No-bot started ~24h ago per Kyle; no candidates-log visibility yet so can't confirm scanner health from the dashboard. Identified candidate-feed UI as the most valuable next build.
- **2026-04-24** — Clarified scanner behavior (re-evaluates all open events every 5 min, not just new listings); confirmed no-bot has no WebSocket wired up yet (ws_entry.py is a design doc). Deprioritized copy-bot — not shipping; no-bot is the active bet.
- **2026-04-24** — Major build pass landed:
  - Copy-bot put in heartbeat-only mode (`COPY_BOT_ENABLED=false`).
  - Scanner telemetry: `no_bot_scan_log` + `no_bot_scan_candidates` tables; dashboard now shows scanner heartbeat + last-pass candidate feed with pass/fail reasons.
  - WebSocket dip detector built ([no_bot/ws_entry.py](../no_bot/ws_entry.py)) — 5% dip below 30-min rolling median, 24h watch-time fallback, T-24h deadline fallback, ≤48h short-fuse direct entry.
  - Telegram alerts wired via [no_bot/alerts.py](../no_bot/alerts.py): entry, resolution (already in resolver), drawdown halt, scanner errors.
  - Drawdown halt now includes mark-to-market unrealized losses on open positions; resolver stashes `last_known_no_price` each pass.
  - DB backup script added: [scripts/backup_db.sh](../scripts/backup_db.sh) — see go-live checklist for cron setup.
  - Go-live checklist created: [go-live-checklist.md](go-live-checklist.md).
