# Go-Live Checklist (No-Bot)

Don't flip `nb_live_mode=1` until every box below is ticked. Update this doc as we tick things off.

## Bankroll & wallet

- [ ] `BOT_PRIVATE_KEY` set on server (dedicated wallet, not personal)
- [ ] `BOT_WALLET_ADDRESS` matches the polypocket MetaMask address
- [ ] `HARVEST_WALLET_ADDRESS` set to your a-bun-dance wallet
- [ ] `ALCHEMY_POLYGON_URL` set
- [ ] $50 USDC.e + ~$0.50 POL deposited to polypocket on Polygon
- [ ] polypocket connected to polymarket.com and TOS accepted
- [ ] $50 deposited from polypocket MetaMask to Polymarket proxy
- [ ] CLOB API creds derived and added to `.env` (`CLOB_API_KEY`, `CLOB_API_SECRET`, `CLOB_API_PASSPHRASE`)
- [ ] `approve_usdc()` run once on the server
- [ ] `nb_bankroll` config in DB matches funded amount ($50.00)

## Paper-trading evidence (≥7 calendar days)

- [ ] Dashboard scanner-status strip has been 🟢 (green) >95% of the time
- [ ] At least **10 paper entries** logged in `no_positions` (mock=1)
- [ ] At least **3 paper resolutions** booked (so we've validated the resolver path end-to-end)
- [ ] No `scan iteration failed` exceptions in `docker logs` for 7 consecutive days
- [ ] Telegram alerts received for at least one entry and one resolution (proves the alert path is wired)
- [ ] Paper P&L not catastrophically off the backtest expectation (a few wins, a few losses, no obvious systemic bug)

## Operational

- [ ] `trading.db` backup cron installed on server (see `scripts/backup_db.sh` and runbook)
- [ ] Verified at least one backup file exists in `/root/backups/polymarket/`
- [ ] Server `unattended-upgrades` enabled with auto-reboot (already done 2026-04-24)

## Code & strategy

- [ ] Latest commit deployed (`docker compose down && docker compose up -d --build`)
- [ ] WS entry gate connected (look for `✅ WS entry gate connected` in logs)
- [ ] Drawdown halt threshold reviewed for $50 bankroll — at -30% that's a $15 loss before halt. Confirm that's what we want. If too aggressive at this size, raise to 50% temporarily.

## Day-of flip

When all above are ticked:

1. Set `NO_BOT_DRY_RUN=false` in `/root/polymarket-picks/.env` on server.
2. Restart container: `docker compose restart`.
3. Open dashboard → Settings → No-Bot → toggle "Live mode" ON (`nb_live_mode=1`).
4. Watch first live entry happen. Confirm Telegram fires with 💰 LIVE tag.
5. Verify the position appears on `polymarket.com/profile/<polypocket_address>`.

## Rollback

If anything looks wrong after going live:

1. Toggle `nb_live_mode` OFF on dashboard. New positions stop immediately.
2. Existing open positions stay open and resolve normally — they're already on the CLOB.
3. To halt resolution updates too: `docker compose down`.
