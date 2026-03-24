import time
import requests
import os
import logging
import threading
from dotenv import load_dotenv
from finance import FinanceController
from ws_listener import PolymarketWSListener

load_dotenv()
from database import TradingDB
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

# Set up logging to both console and a file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "polymarket_bot.log")),
        logging.StreamHandler()
    ]
)

@dataclass
class Specialist:
    name: str
    wallet_address: str
    target_tags: list[str]
    tier: str
    is_active: bool = True

# Core Configuration Based on PRD
# We leave an empty list here since specialists are now loaded dynamically from DB
SPECIALISTS = []

DATA_API_URL = "https://data-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"

POLL_INTERVAL = 30  # HTTP polling fallback interval (seconds)

TAG_MAP = {
    "100381": "NBA", "100382": "NCAAM", "100101": "Soccer", "100102": "UCL",
    "100383": "MLB", "100384": "NHL", "100401": "Tennis",
    "100601": "Tech", "100701": "Politics", "100801": "Pop Culture"
}

# Cache for market tag lookups (event_slug -> list of tag IDs)
_tag_cache = {}


def lookup_market_tags(event_slug: str) -> list[str]:
    """Query the Gamma API to get actual category tags for a market."""
    if event_slug in _tag_cache:
        return _tag_cache[event_slug]
    
    try:
        resp = requests.get(f"{GAMMA_API_URL}/events?slug={event_slug}", timeout=5)
        if resp.status_code == 200:
            events = resp.json()
            if events and len(events) > 0:
                event = events[0]
                tags = []
                # Gamma API returns tags as a list of objects with "id" field
                for tag in event.get('tags', []):
                    tag_id = str(tag.get('id', '')) if isinstance(tag, dict) else str(tag)
                    if tag_id:
                        tags.append(tag_id)
                _tag_cache[event_slug] = tags
                return tags
    except Exception as e:
        logging.debug(f"Tag lookup failed for {event_slug}: {e}")
    
    # Return empty list on failure (caller uses fallback)
    _tag_cache[event_slug] = []
    return []


class PolymarketBot:
    def __init__(self):
        self.db = TradingDB()
        self.seen_positions = set()
        self.watched_positions = set()
        self.ws_listener = None
        
        # Load Baseline
        baseline, _ = self.db.get_performance()
        logging.info(f"🤖 Bot Initialized. Current Run Baseline: ${baseline}")
        
        # Pre-seed seen_positions so restarts don't re-trigger existing trades
        self._preseed_seen_positions()
        
        # Run initial resolution check on startup to backfill existing trades
        self.resolve_pending_trades()
    
    def _preseed_seen_positions(self):
        """On startup, scan specialist positions and mark any that already have
        PENDING trades in the DB as 'seen' so they aren't re-processed."""
        pending_trades = self.db.get_all_recent_trades(limit=500)
        active_markets = {t[1] for t in pending_trades if t[4] == 'PENDING'}  # market names
        
        if not active_markets:
            return
            
        db_specs = self.db.get_all_specialists()
        for spec in db_specs:
            if not spec.get('is_active', True) or 'MOCK' in spec['wallet']:
                continue
            try:
                resp = requests.get(f"{DATA_API_URL}/positions?user={spec['wallet']}", timeout=10)
                if resp.status_code == 200:
                    for pos in resp.json():
                        title = pos.get('title', '')
                        asset = pos.get('asset', '')
                        if asset and title in active_markets:
                            self.seen_positions.add(asset)
            except Exception:
                pass
        
        if self.seen_positions:
            logging.info(f"🔄 Pre-seeded {len(self.seen_positions)} positions from existing DB trades")

    def send_telegram_alert(self, message: str):
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip("\"'")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip("\"'")
        if not token or not chat_id:
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": message})
        except Exception as e:
            logging.error(f"Failed to send Telegram alert: {e}")

    def generate_hourly_summary(self):
        exposure = self.db.get_total_pending_exposure()
        balance = max(0.0, 50.0 - exposure)
        
        recent = self.db.get_all_recent_trades(limit=500)
        wins = sum(1 for t in recent if t[4] == 'WON')
        losses = sum(1 for t in recent if t[4] == 'LOST')
        pending = sum(1 for t in recent if t[4] == 'PENDING')
        total_resolved = wins + losses
        win_pct = f"{(wins/total_resolved*100):.0f}%" if total_resolved > 0 else "N/A"
        
        # Calculate P&L from resolved trades
        total_pnl = 0.0
        for t in recent:
            if t[4] == 'WON':
                bet_size = t[7] if t[7] and t[7] > 0 else t[2]
                entry_price = t[2]
                # Won: payout is bet_size / entry_price (shares * $1), profit = payout - bet_size
                if entry_price > 0:
                    total_pnl += (bet_size / entry_price) - bet_size
            elif t[4] == 'LOST':
                bet_size = t[7] if t[7] and t[7] > 0 else t[2]
                total_pnl -= bet_size
        
        ws_status = "🟢 WS" if (self.ws_listener and self.ws_listener.is_connected) else "🔴 WS"
        
        lines = [
            "📊 Hourly Summary",
            "",
            f"💰 Balance: ${balance:.2f}",
            f"📈 Exposure: ${exposure:.2f} across {pending} pending",
            f"💵 Realized P&L: ${total_pnl:+.2f}",
            "",
            f"✅ {wins} Wins / ❌ {losses} Losses ({win_pct})",
            "",
            f"{ws_status} | Bot is running."
        ]
        return "\n".join(lines)

    def resolve_pending_trades(self):
        """Check all PENDING trades and auto-resolve WON/LOST based on market status."""
        pending = self.db.get_pending_trades_for_resolution()
        if not pending:
            return
        
        resolved_count = 0
        for trade in pending:
            try:
                slug = trade['slug']
                our_outcome = trade['outcome']  # What we bet on (e.g., "Yes", "Spurs")
                
                # Query the Gamma API for market resolution status
                resp = requests.get(f"{GAMMA_API_URL}/events?slug={slug}", timeout=5)
                if resp.status_code != 200:
                    continue
                
                events = resp.json()
                if not events:
                    continue
                
                event = events[0]
                markets = event.get('markets', [])
                
                for market in markets:
                    market_question = market.get('question', '')
                    
                    # Match our trade to the right market within the event
                    if trade['market'] not in market_question and market_question not in trade['market']:
                        continue
                    
                    resolved = market.get('resolved', False)
                    if not resolved:
                        continue
                    
                    # Determine if we won or lost
                    winning_outcome = market.get('outcome', '')  # "Yes" or "No"
                    
                    if winning_outcome:
                        result = 'WON' if our_outcome == winning_outcome else 'LOST'
                        self.db.update_trade_result(trade['id'], result)
                        resolved_count += 1
                        
                        bet = trade['bet_size'] if trade['bet_size'] > 0 else trade['entry_price']
                        emoji = "🏆" if result == "WON" else "💀"
                        pnl = (bet / trade['entry_price'] - bet) if result == 'WON' and trade['entry_price'] > 0 else -bet
                        
                        msg = "\n".join([
                            f"{emoji} TRADE RESOLVED: {result}",
                            "",
                            f"📋 {trade['market']}",
                            f"👤 {trade['specialist']}",
                            f"🎯 {our_outcome} @ ${trade['entry_price']:.2f}",
                            f"💵 Bet: ${bet:.2f}",
                            f"💰 P&L: ${pnl:+.2f}",
                        ])
                        self.send_telegram_alert(msg)
                        logging.info(f"{emoji} RESOLVED {trade['specialist']} | {trade['market']} | {result} | P&L ${pnl:+.2f}")
                        break
                        
            except Exception as e:
                logging.debug(f"Resolution check failed for trade {trade['id']}: {e}")
        
        if resolved_count > 0:
            logging.info(f"📊 Auto-resolved {resolved_count} trades this cycle")

    def check_order_book_depth(self, asset_id: str, bet_size: float) -> tuple[bool, float]:
        """Check if there's enough liquidity in the order book for our bet size."""
        try:
            resp = requests.get(f"{CLOB_URL}/book?token_id={asset_id}", timeout=3)
            if resp.status_code == 200:
                book_data = resp.json()
                return FinanceController.check_liquidity(book_data, bet_size)
        except Exception as e:
            logging.debug(f"Order book check failed for {asset_id}: {e}")
        
        # If check fails, allow the trade (don't block on optional check)
        return True, 0.0

    def _start_websocket(self):
        """Start the WebSocket listener for real-time trade detection."""
        def on_ws_status(message):
            self.send_telegram_alert(f"🔌 {message}")
        
        self.ws_listener = PolymarketWSListener(
            on_trade_callback=None,  # We use polling + WS for detection, not pure WS
            on_status_callback=on_ws_status
        )
        self.ws_listener.start()
        logging.info("🔌 WebSocket listener started as background monitor")

    def monitor_loop(self):
        logging.info("Starting real-time polling loop with WebSocket fallback...")
        self.send_telegram_alert("🚀 Polymarket Copy-Bot Started and Monitoring!")
        EST = timezone(timedelta(hours=-5))
        SUMMARY_HOURS = {8, 12, 16, 20}  # 8am, 12pm, 4pm, 8pm EST
        sent_summary_for = set()  # Track which hours we already sent
        
        # Start WebSocket listener in background
        self._start_websocket()
        
        while True:
            try:
                self.db.record_heartbeat()
                
                # Send summary at 8am, 12pm, 4pm, 8pm EST
                now_est = datetime.now(EST)
                hour_key = (now_est.date(), now_est.hour)
                if now_est.hour in SUMMARY_HOURS and hour_key not in sent_summary_for:
                    summary_msg = self.generate_hourly_summary()
                    self.send_telegram_alert(summary_msg)
                    sent_summary_for.add(hour_key)
                    # Keep set small: clear entries older than today
                    sent_summary_for = {k for k in sent_summary_for if k[0] >= now_est.date()}
                
                # Auto-resolve any completed trades
                self.resolve_pending_trades()
                
                db_specs = self.db.get_all_specialists()
                dynamic_specialists = [Specialist(s["name"], s["wallet"], s["tags"], s.get("tier", "SHARP"), s.get("is_active", True)) for s in db_specs]
                
                for spec in dynamic_specialists:
                    if not spec.is_active or "MOCK" in spec.wallet_address:
                        continue 
                        
                    # Query specialist open positions using Polymarket Data API
                    resp = requests.get(f"{DATA_API_URL}/positions?user={spec.wallet_address}", timeout=10)
                    if resp.status_code == 200:
                        positions = resp.json()
                        for pos in positions:
                            pos_id = pos.get('asset', '')
                            
                            if pos_id and pos_id not in self.seen_positions:
                                size = float(pos.get('size', 0))
                                price = float(pos.get('avgPrice', 0))
                                market = pos.get('title', 'Unknown Market')
                                slug = pos.get('eventSlug', pos.get('slug', ''))  # eventSlug for /event/ URL path
                                outcome = pos.get('outcome', 'Yes')
                                
                                if size > 0:
                                    # Date constraint logic (Reject >7 days out, Reject past markets)
                                    endDate_str = pos.get('endDate', '')
                                    if endDate_str:
                                        try:
                                            date_part = endDate_str.split('T')[0] if 'T' in endDate_str else endDate_str
                                            end_dt = datetime.strptime(date_part, "%Y-%m-%d")
                                            now = datetime.now()
                                            
                                            if end_dt < now:
                                                self.seen_positions.add(pos_id)
                                                continue # Skip past matches (resolution delays prevent ghost trades)
                                                
                                            if (end_dt - now).days > 7:
                                                self.seen_positions.add(pos_id)
                                                continue # Skip long-term capital lockup
                                        except ValueError:
                                            pass
                                    
                                    # Real tag matching: look up actual market tags from Gamma API
                                    market_tags = lookup_market_tags(slug) if slug else []
                                    
                                    # Find the best matching tag between market and specialist
                                    matched_tag = None
                                    for tag in market_tags:
                                        if tag in spec.target_tags:
                                            matched_tag = tag
                                            break
                                    
                                    # Fallback: if no tags found from API, use specialist's primary domain
                                    if matched_tag is None and not market_tags:
                                        matched_tag = spec.target_tags[0] if spec.target_tags else "100381"
                                        logging.debug(f"Tag API unavailable for {slug}, using fallback tag {matched_tag}")
                                    elif matched_tag is None:
                                        # Market has tags but none match specialist's domain — skip
                                        self.seen_positions.add(pos_id)
                                        tag_names = [TAG_MAP.get(t, t) for t in market_tags[:3]]
                                        logging.info(f"⛔ TAG MISMATCH {spec.name} | {market} | Market tags: {tag_names}")
                                        continue
                                            
                                    # We mock leader price as price * 0.98 for the Phase 1 test
                                    status, msg_reason, bet_size = self.execute_trade_logic(spec, matched_tag, price, price * 0.98, market)
                                    
                                    if status == "PASSED":
                                        # Order book depth check before final execution
                                        has_liquidity, avail_liq = self.check_order_book_depth(pos_id, bet_size)
                                        if not has_liquidity and avail_liq > 0:
                                            logging.warning(f"⚠️ Low liquidity for {market}: ${avail_liq:.2f} available, need ${bet_size*2:.2f}")
                                            # Still proceed but note it — at Phase 1 sizes this is rarely an issue
                                        
                                        self.seen_positions.add(pos_id)
                                        # Inject real trade object back to Database
                                        self.db.add_trade(spec.name, market, price, slug, outcome, bet_size, endDate_str)
                                        
                                        remaining = max(0.0, 50.0 - self.db.get_total_pending_exposure())
                                        link = f"https://polymarket.com/event/{slug}" if slug else ""
                                        msg = "\n".join([
                                            "✅ COPIED TRADE",
                                            "",
                                            f"📋 {market}",
                                            f"👤 {spec.name} ({spec.tier})",
                                            f"🎯 {outcome} @ ${price:.2f}",
                                            f"💵 Bet: ${bet_size:.2f}",
                                            f"💰 Balance: ${remaining:.2f}",
                                            "",
                                            link
                                        ])
                                        self.send_telegram_alert(msg)
                                        logging.info(f"✅ COPIED TRADE {spec.name} | {market} | {outcome} @ ${price:.2f} | Bet ${bet_size:.2f} | Bal ${remaining:.2f}")
                                        
                                    elif status == "PERMANENT_REJECT":
                                        self.seen_positions.add(pos_id)
                                        # Only send Telegram for interesting rejects, not "already holding" noise
                                        if "Already holding" not in msg_reason:
                                            msg = f"⛔ SKIP {spec.name}\n{market}\n{msg_reason}"
                                            self.send_telegram_alert(msg)
                                        logging.warning(f"⛔ REJECT {spec.name} | {market} | {msg_reason}")
                                        
                                    elif status == "TEMPORARY_REJECT":
                                        # Do NOT add to seen_positions. It will be retried next loop.
                                        # Avoid log/telegram spam:
                                        if pos_id not in self.watched_positions:
                                            self.watched_positions.add(pos_id)
                                            logging.info(f"⏳ WATCH {spec.name} | {market} | {msg_reason}")
                    else:
                        logging.warning(f"Failed to fetch positions for {spec.name}: API returned HTTP {resp.status_code}")
            except Exception as e:
                logging.error(f"Error in monitor loop: {e}")
                self.send_telegram_alert(f"🚨 CRITICAL ERROR in monitor_loop: {e}")
                
            time.sleep(POLL_INTERVAL)

    def execute_trade_logic(self, specialist: Specialist, market_tag: str, current_price: float, leader_price: float, market_name: str):
        """
        Runs the full check based on the PRD before sending the CLOB API order.
        Returns a tuple: (Status, Reason_String, Bet_Size)
        Status can be "PASSED", "PERMANENT_REJECT", or "TEMPORARY_REJECT".
        """
        # 0. Collision Check / Opposing Bets
        # If we already have a PENDING active position in this same exact market, 
        # do not buy again. Prevents paying fees to wash ourselves out or taking both YES and NO.
        recent_trades = self.db.get_all_recent_trades(50)
        active_markets = [t[1] for t in recent_trades if t[4] == 'PENDING']
        if market_name in active_markets:
            return "PERMANENT_REJECT", f"Already holding an active position in {market_name}", 0.0

        # 1. Health Monitor Check
        win_rate = self.db.get_specialist_win_rate(specialist.name)
        
        # WHALE threshold is 40.0%, SHARP threshold is 55.0%
        min_win_rate = 40.0 if specialist.tier == 'WHALE' else 55.0
        
        if win_rate < min_win_rate:
            return "PERMANENT_REJECT", f"Probation (Win Rate {win_rate}% < {min_win_rate}%)", 0.0
            
        # 2. Correct Tag ID Mapping Check
        if str(market_tag) not in specialist.target_tags:
            tag_name = TAG_MAP.get(str(market_tag), market_tag)
            return "PERMANENT_REJECT", f"{tag_name} outside domain", 0.0

        # 3. Adaptive Value Caps
        max_entry = FinanceController.get_max_price_for_tag(market_tag)
        if current_price > max_entry:
            return "TEMPORARY_REJECT", f"Current Price {current_price} exceeds Value Cap {max_entry}", 0.0

        # 4. No Chase / Slippage Check
        if not FinanceController.is_slippage_acceptable(leader_price, current_price):
            return "TEMPORARY_REJECT", f"Price slipped too far from Leader's price of {leader_price}", 0.0

        # 5. Position Sizing
        # Mocking balance fetch for Phase 1 Validation dynamically via Local exposure
        current_wallet_balance = max(0.0, 50.0 - self.db.get_total_pending_exposure())
        
        if current_wallet_balance < 5.0:
            return "TEMPORARY_REJECT", "Insufficient Buffer (Bankroll hit $5.00 fail-safe)", 0.0
            
        # Calculate bet size using baseline 50 for generic scaling math, but clamp to available balance so it halts naturally
        bet_size = FinanceController.calculate_bet_size(50.0, specialist.tier, win_rate)
        if bet_size > current_wallet_balance:
            bet_size = current_wallet_balance

        return "PASSED", f"Validated for ${bet_size:.2f} bet", float(bet_size)

    def process_harvesting(self, current_balance: float):
        baseline, _ = self.db.get_performance()
        result = FinanceController.check_harvest(current_balance, baseline)
        if result.triggered:
            # Main Wallet Harvesting API Call goes here (Polygon transfer)
            self.db.update_performance_post_harvest(result.new_baseline, result.transfer_amount)
            logging.info(f"💸 HARVEST TRIGGERED: Sent ${result.transfer_amount:.2f} to personal wallet!")

if __name__ == "__main__":
    bot = PolymarketBot()
    bot.monitor_loop()
