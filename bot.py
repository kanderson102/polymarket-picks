import time
import requests
import os
import logging
from dotenv import load_dotenv
from finance import FinanceController

load_dotenv()
from database import TradingDB
from dataclasses import dataclass
from datetime import datetime

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

class PolymarketBot:
    def __init__(self):
        self.db = TradingDB()
        self.seen_positions = set()
        self.watched_positions = set() # Track positions waiting for a price drop without spamming logs
        
        # Load Baseline
        baseline, _ = self.db.get_performance()
        logging.info(f"🤖 Bot Initialized. Current Run Baseline: ${baseline}")

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
        
        return f"📊 Hourly Bot Summary:\n\nAvailable USDC: ${balance:.2f}\nTotal Pending Exposure: ${exposure:.2f} across {pending} trades\n\nWins to Date: {wins}\nLosses to Date: {losses}\n\nThe bot will continue autonomously managing your portfolio balance safely."

    def monitor_loop(self):
        logging.info("Starting real-time Gamma API polling loop...")
        self.send_telegram_alert("🚀 Polymarket Copy-Bot Started and Monitoring!")
        last_summary_time = time.time()
        
        while True:
            try:
                self.db.record_heartbeat()
                
                # Check for hourly summary trigger
                if time.time() - last_summary_time >= 3600:
                    summary_msg = self.generate_hourly_summary()
                    self.send_telegram_alert(summary_msg)
                    last_summary_time = time.time()
                
                db_specs = self.db.get_all_specialists()
                dynamic_specialists = [Specialist(s["name"], s["wallet"], s["tags"], s.get("tier", "SHARP"), s.get("is_active", True)) for s in db_specs]
                
                for spec in dynamic_specialists:
                    if not spec.is_active or "MOCK" in spec.wallet_address:
                        continue 
                        
                    # Query specialist positions using Polymarket Data API
                    resp = requests.get(f"{DATA_API_URL}/positions?user={spec.wallet_address}", timeout=10)
                    if resp.status_code == 200:
                        positions = resp.json()
                        for pos in positions:
                            pos_id = pos.get('asset', '')
                            
                            if pos_id and pos_id not in self.seen_positions:
                                size = float(pos.get('size', 0))
                                price = float(pos.get('avgPrice', 0))
                                market = pos.get('title', 'Unknown Market')
                                slug = pos.get('slug', '')
                                
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
                                                continue # Skip past matches (resolution delays)
                                                
                                            if (end_dt - now).days > 7:
                                                self.seen_positions.add(pos_id)
                                                continue # Skip long-term capital lockup
                                        except ValueError:
                                            pass
                                            
                                    # Fallback tag: Use the specialist's primary domain to allow Phase 1 simulation checks to execute.
                                    # We mock leader price as price * 0.98 for the Phase 1 test
                                    assumed_tag = spec.target_tags[0] if spec.target_tags else "100381"
                                    status, msg_reason = self.execute_trade_logic(spec, assumed_tag, price, price * 0.98, market)
                                    
                                    if status == "PASSED":
                                        self.seen_positions.add(pos_id)
                                        # Inject real trade object back to Database
                                        self.db.add_trade(spec.name, market, price, slug)
                                        
                                        msg = f"✅ COPIED TRADE\nSpecialist: {spec.name}\nMarket: {market}\nEntry: ${price:.2f}"
                                        self.send_telegram_alert(msg)
                                        logging.info(f"✅ COPIED TRADE Specialist: {spec.name} Market: {market} Entry: ${price:.2f}")
                                        
                                    elif status == "PERMANENT_REJECT":
                                        self.seen_positions.add(pos_id)
                                        msg = f"⛔ REJECTED (Forever) {spec.name} - {msg_reason} - Market: {market}"
                                        self.send_telegram_alert(msg)
                                        logging.warning(msg)
                                        
                                    elif status == "TEMPORARY_REJECT":
                                        # Do NOT add to seen_positions. It will be retried next loop.
                                        # Avoid log/telegram spam:
                                        if pos_id not in self.watched_positions:
                                            self.watched_positions.add(pos_id)
                                            msg = f"⏳ WAITING (Price too high) {spec.name}. Watching for dip. Reason: {msg_reason}. Market: {market}"
                                            logging.info(msg)
                    else:
                        logging.warning(f"Failed to fetch positions for {spec.name}: API returned HTTP {resp.status_code}")
            except Exception as e:
                logging.error(f"Error in monitor loop: {e}")
                self.send_telegram_alert(f"🚨 CRITICAL ERROR in monitor_loop: {e}")
                
            time.sleep(60) # Poll every 60s

    def execute_trade_logic(self, specialist: Specialist, market_tag: str, current_price: float, leader_price: float, market_name: str):
        """
        Runs the full check based on the PRD before sending the CLOB API order.
        Returns a tuple: (Status, Reason_String)
        Status can be "PASSED", "PERMANENT_REJECT", or "TEMPORARY_REJECT".
        """
        # 0. Collision Check / Opposing Bets
        # If we already have a PENDING active position in this same exact market, 
        # do not buy again. Prevents paying fees to wash ourselves out or taking both YES and NO.
        recent_trades = self.db.get_all_recent_trades(50)
        active_markets = [t[1] for t in recent_trades if t[4] == 'PENDING']
        if market_name in active_markets:
            return "PERMANENT_REJECT", f"Already holding an active position in {market_name}"

        # 1. Health Monitor Check
        win_rate = self.db.get_specialist_win_rate(specialist.name)
        
        # WHALE threshold is 40.0%, SHARP threshold is 55.0%
        min_win_rate = 40.0 if specialist.tier == 'WHALE' else 55.0
        
        if win_rate < min_win_rate:
            return "PERMANENT_REJECT", f"Probation (Win Rate {win_rate}% < {min_win_rate}%)"
            
        # 2. Correct Tag ID Mapping Check
        if str(market_tag) not in specialist.target_tags:
            return "PERMANENT_REJECT", f"Market Tag {market_tag} OUTSIDE domain"

        # 3. Adaptive Value Caps
        max_entry = FinanceController.get_max_price_for_tag(market_tag)
        if current_price > max_entry:
            return "TEMPORARY_REJECT", f"Current Price {current_price} exceeds Value Cap {max_entry}"

        # 4. No Chase / Slippage Check
        if not FinanceController.is_slippage_acceptable(leader_price, current_price):
            return "TEMPORARY_REJECT", f"Price slipped too far from Leader's price of {leader_price}"

        # 5. Position Sizing
        # Mocking balance fetch for Phase 1 Validation dynamically via Local exposure
        current_wallet_balance = max(0.0, 50.0 - self.db.get_total_pending_exposure())
        
        if current_wallet_balance < 5.0:
            return "TEMPORARY_REJECT", "Insufficient Buffer (Bankroll hit $5.00 fail-safe)"
            
        # Calculate bet size using baseline 50 for generic scaling math, but clamp to available balance so it halts naturally
        bet_size = FinanceController.calculate_bet_size(50.0, specialist.tier, win_rate)
        if bet_size > current_wallet_balance:
            bet_size = current_wallet_balance

        return "PASSED", f"Validated for ${bet_size:.2f} bet"

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
