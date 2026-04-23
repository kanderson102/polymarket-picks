import time
import requests
import os
import logging
import logging.handlers
import threading
from dotenv import load_dotenv
from finance import FinanceController
from ws_listener import PolymarketWSListener

load_dotenv()
from database import TradingDB
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from web3 import Web3

# Set up logging with rotation (5MB max, 3 backups = 15MB total)
log_path = os.path.join(os.path.dirname(__file__), "polymarket_bot.log")
rotating_handler = logging.handlers.RotatingFileHandler(
    log_path, maxBytes=5 * 1024 * 1024, backupCount=3
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        rotating_handler,
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
    "745": "NBA", "28": "Basketball", "100350": "Soccer", "100977": "UCL",
    "306": "EPL", "82": "Premier League",
    "100381": "MLB", "678": "baseball",
    "899": "NHL", "100088": "Hockey", "100089": "Stanley Cup",
    "64": "Esports", "102366": "Dota 2",
    "2": "Politics", "144": "Elections", "100265": "Geopolitics",
    "1": "Sports", "100639": "Games",
}

# Tag groups: tags in the same group are considered equivalent for matching.
TAG_GROUPS = [
    {"745", "28"},                              # NBA / Basketball
    {"100350", "306", "82", "100977", "101962"}, # Soccer / EPL / Premier League / UCL
    {"100381", "678"},                           # MLB / baseball
    {"899", "100088", "100089"},                 # NHL / Hockey / Stanley Cup
    {"64", "102366"},                            # Esports / Dota 2
    {"2", "144", "100265"},                      # Politics / Elections / Geopolitics
    {"1", "100639"},                             # Sports / Games (generic parents)
]


def expand_tags(tags: list[str]) -> set[str]:
    """Expand tags to include all related tags from the same groups."""
    expanded = set(tags)
    for group in TAG_GROUPS:
        if expanded & group:
            expanded |= group
    return expanded

# Strategy configuration — can be overridden via environment variables
ENABLE_TAG_FILTER = os.environ.get("ENABLE_TAG_FILTER", "false").lower() == "true"
MAX_DAYS_SPORTS = int(os.environ.get("MAX_DAYS_SPORTS", "60"))
MAX_DAYS_DEFAULT = int(os.environ.get("MAX_DAYS_DEFAULT", "90"))

# Sports tags for date filter categorization
SPORTS_TAGS = {"745", "28", "100350", "100977", "306", "82", "100381", "678", "899", "100088", "100089", "1", "100639", "64", "102366"}

# USDC contract on Polygon (PoS bridged)
USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
# Also check native USDC
USDCE_CONTRACT = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

# ERC-20 balanceOf ABI (minimal)
ERC20_ABI = [{
    "constant": True,
    "inputs": [{"name": "_owner", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "balance", "type": "uint256"}],
    "type": "function"
}]

# Cache for market tag lookups (event_slug -> list of tag IDs)
_tag_cache = {}

# Wallet balance cache (value, timestamp)
_balance_cache = {"value": None, "timestamp": 0}
BALANCE_CACHE_TTL = 60  # seconds


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


def get_wallet_balance() -> float:
    """Query the bot wallet's USDC balance on Polygon via Alchemy RPC.
    Returns balance in dollars. Caches for BALANCE_CACHE_TTL seconds."""
    now = time.time()
    if _balance_cache["value"] is not None and (now - _balance_cache["timestamp"]) < BALANCE_CACHE_TTL:
        return _balance_cache["value"]
    
    rpc_url = os.environ.get("ALCHEMY_POLYGON_URL", "")
    wallet = os.environ.get("BOT_WALLET_ADDRESS", "")
    
    if not rpc_url or not wallet:
        logging.warning("Missing ALCHEMY_POLYGON_URL or BOT_WALLET_ADDRESS — cannot query balance")
        return 0.0
    
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        wallet_addr = Web3.to_checksum_address(wallet)
        total = 0.0
        
        # Check both USDC variants on Polygon
        for contract_addr, decimals in [(USDC_CONTRACT, 6), (USDCE_CONTRACT, 6)]:
            try:
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(contract_addr),
                    abi=ERC20_ABI
                )
                raw_balance = contract.functions.balanceOf(wallet_addr).call()
                total += raw_balance / (10 ** decimals)
            except Exception:
                pass  # Contract may not exist or be different on this chain
        
        _balance_cache["value"] = total
        _balance_cache["timestamp"] = now
        logging.debug(f"💰 Wallet balance: ${total:.2f} USDC")
        return total
        
    except Exception as e:
        logging.error(f"Failed to query wallet balance: {e}")
        # Return cached value if available, else 0
        return _balance_cache["value"] if _balance_cache["value"] is not None else 0.0


def get_best_ask(asset_id: str) -> float:
    """Get the current best ask price from the CLOB order book.
    Returns 0.0 if the order book is unavailable."""
    try:
        resp = requests.get(f"{CLOB_URL}/book?token_id={asset_id}", timeout=3)
        if resp.status_code == 200:
            book = resp.json()
            asks = book.get('asks', [])
            if asks:
                return float(asks[0].get('price', 0))
    except Exception as e:
        logging.debug(f"Best ask lookup failed for {asset_id}: {e}")
    return 0.0


def get_max_days_for_tags(market_tags: list[str], cfg: dict = None) -> int:
    """Return the max allowed days-to-expiry based on market category tags."""
    max_sports = int(cfg.get('max_days_sports', MAX_DAYS_SPORTS)) if cfg else MAX_DAYS_SPORTS
    max_default = int(cfg.get('max_days_default', MAX_DAYS_DEFAULT)) if cfg else MAX_DAYS_DEFAULT
    for tag in market_tags:
        if tag in SPORTS_TAGS:
            return max_sports
    return max_default


class PolymarketBot:
    def __init__(self):
        self.db = TradingDB()
        self.seen_positions = set()
        self.watched_positions = set()
        self.ws_listener = None
        
        # Query real wallet balance on startup
        wallet_balance = get_wallet_balance()
        baseline, _ = self.db.get_performance()
        logging.info(f"🤖 Bot Initialized. Wallet: ${wallet_balance:.2f} USDC | Baseline: ${baseline}")
        
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

    def send_telegram_alert(self, message: str, category: str = "general"):
        # Check DB config first; fall back to env var ENABLE_TELEGRAM (default on)
        db_enabled = self.db.get_config("enable_telegram", "1")
        env_enabled = os.environ.get("ENABLE_TELEGRAM", "true").lower()
        if db_enabled == "0" or env_enabled == "false":
            return

        # Per-category toggles. Defaults: buy/resolve/error ON; summary/skip OFF.
        category_defaults = {
            "buy": "1",
            "resolve": "1",
            "error": "1",
            "summary": "0",
            "skip": "0",
            "general": "1",
        }
        default = category_defaults.get(category, "1")
        if self.db.get_config(f"notify_{category}", default) == "0":
            return

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
        wallet_balance = get_wallet_balance()

        recent = self.db.get_all_recent_trades(limit=500)
        wins = sum(1 for t in recent if t[4] == 'WON')
        losses = sum(1 for t in recent if t[4] == 'LOST')
        pending = sum(1 for t in recent if t[4] == 'PENDING')
        total_resolved = wins + losses
        win_pct = f"{(wins/total_resolved*100):.0f}%" if total_resolved > 0 else "N/A"

        # Calculate P&L and Slippage from recent trades
        total_pnl = 0.0
        slippages = []
        for t in recent:
            # P&L
            if t[4] == 'WON':
                bet_size = t[7] if t[7] and t[7] > 0 else t[2]
                entry_price = t[2]
                if entry_price > 0:
                    total_pnl += (bet_size / entry_price) - bet_size
            elif t[4] == 'LOST':
                bet_size = t[7] if t[7] and t[7] > 0 else t[2]
                total_pnl -= bet_size

            # Slippage (t[9]=leader_price, t[10]=market_price)
            if len(t) > 10 and t[9] > 0 and t[10] > 0:
                slippages.append(FinanceController.calculate_slippage_pct(t[9], t[10]))

        avg_slippage = sum(slippages) / len(slippages) if slippages else 0.0
        ws_status = "🟢 WS" if (self.ws_listener and self.ws_listener.is_connected) else "🔴 WS"

        lines = [
            "📊 Hourly Summary",
            "",
            f"💰 Wallet: ${wallet_balance:.2f} USDC",
            f"🎯 Open Positions: {pending}",
            f"💵 Realized P&L: ${total_pnl:+.2f}",
            f"📉 Avg Slippage: {avg_slippage:+.2f}%",
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
                        self.send_telegram_alert(msg, category="resolve")
                        logging.info(f"{emoji} RESOLVED {trade['specialist']} | {trade['market']} | {result} | P&L ${pnl:+.2f}")
                        break
                        
            except Exception as e:
                logging.debug(f"Resolution check failed for trade {trade['id']}: {e}")
        
        if resolved_count > 0:
            logging.info(f"📊 Auto-resolved {resolved_count} trades this cycle")

        # Expire stale trades: past end_date + 3 day grace, or >45 days old with no end_date
        stale = self.db.get_stale_pending_trades(grace_days=3, max_age_days=45)
        expired_count = 0
        for trade in stale:
            self.db.update_trade_result(trade['id'], 'EXPIRED')
            expired_count += 1
            bet = trade['bet_size'] if trade['bet_size'] > 0 else trade['entry_price']
            end_info = f"end_date {trade['end_date']}" if trade['end_date'] else f"opened {trade['timestamp']}"
            msg = "\n".join([
                "⏰ TRADE EXPIRED",
                "",
                f"📋 {trade['market']}",
                f"👤 {trade['specialist']}",
                f"💵 ${bet:.2f} freed up ({end_info})",
            ])
            self.send_telegram_alert(msg, category="resolve")
            logging.info(f"⏰ EXPIRED {trade['specialist']} | {trade['market']} | {end_info}")

        if expired_count > 0:
            logging.info(f"⏰ Expired {expired_count} stale trades this cycle")

    def check_order_book_depth(self, asset_id: str, bet_size: float, cfg: dict = None) -> tuple[bool, float]:
        """Check if there's enough liquidity in the order book for our bet size."""
        try:
            resp = requests.get(f"{CLOB_URL}/book?token_id={asset_id}", timeout=3)
            if resp.status_code == 200:
                book_data = resp.json()
                return FinanceController.check_liquidity(book_data, bet_size, cfg)
        except Exception as e:
            logging.debug(f"Order book check failed for {asset_id}: {e}")

        # If check fails, allow the trade (don't block on optional check)
        return True, 0.0

    def _start_websocket(self):
        """Start the WebSocket listener for real-time trade detection."""
        def on_ws_status(message):
            pass  # server status notifications temporarily disabled
        
        self.ws_listener = PolymarketWSListener(
            on_trade_callback=None,  # We use polling + WS for detection, not pure WS
            on_status_callback=on_ws_status
        )
        self.ws_listener.start()
        logging.info("🔌 WebSocket listener started as background monitor")

    def monitor_loop(self):
        logging.info("Starting real-time polling loop with WebSocket fallback...")
        # self.send_telegram_alert("🚀 Polymarket Copy-Bot Started and Monitoring!")  # server status notifications temporarily disabled
        EST = timezone(timedelta(hours=-5))
        SUMMARY_HOURS = {8, 12, 16, 20}  # 8am, 12pm, 4pm, 8pm EST
        sent_summary_for = set()  # Track which hours we already sent

        # Start WebSocket listener in background
        self._start_websocket()

        cfg = {}
        while True:
            try:
                self.db.record_heartbeat()

                # Load tunable config from DB on every cycle so UI changes take effect live
                cfg_rows = self.db.get_all_config()
                cfg = {k: v["value"] for k, v in cfg_rows.items()}
                
                # Send summary at 8am, 12pm, 4pm, 8pm EST
                now_est = datetime.now(EST)
                hour_key = (now_est.date(), now_est.hour)
                if now_est.hour in SUMMARY_HOURS and hour_key not in sent_summary_for:
                    summary_msg = self.generate_hourly_summary()
                    self.send_telegram_alert(summary_msg, category="summary")
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
                                    # Real tag matching: look up actual market tags from Gamma API
                                    # (do this FIRST so we can use tags for date filter)
                                    market_tags = lookup_market_tags(slug) if slug else []
                                    
                                    # Smart date filter — tiered by category
                                    endDate_str = pos.get('endDate', '')
                                    if endDate_str:
                                        try:
                                            date_part = endDate_str.split('T')[0] if 'T' in endDate_str else endDate_str
                                            end_dt = datetime.strptime(date_part, "%Y-%m-%d")
                                            now = datetime.now()
                                            
                                            if end_dt < now:
                                                self.seen_positions.add(pos_id)
                                                continue  # Skip past markets
                                            
                                            max_days = get_max_days_for_tags(market_tags, cfg)
                                            days_out = (end_dt - now).days
                                            if days_out > max_days:
                                                self.seen_positions.add(pos_id)
                                                logging.info(f"⏰ SKIP {spec.name} | {market} | {days_out}d out (max {max_days}d for category)")
                                                continue
                                        except ValueError:
                                            pass
                                    
                                    # Find the best matching tag for fee estimation and value caps.
                                    # Tag filtering is OFF by default — copy everything the specialist trades.
                                    # Set ENABLE_TAG_FILTER=true to only copy within assigned categories.
                                    expanded_spec_tags = expand_tags(spec.target_tags)
                                    matched_tag = None
                                    for tag in market_tags:
                                        if tag in expanded_spec_tags:
                                            matched_tag = tag
                                            break

                                    if matched_tag is None and not market_tags:
                                        matched_tag = spec.target_tags[0] if spec.target_tags else "1"
                                        logging.debug(f"Tag API unavailable for {slug}, using fallback tag {matched_tag}")
                                    elif matched_tag is None:
                                        if ENABLE_TAG_FILTER:
                                            # Strict mode: skip trades outside specialist's domain
                                            self.seen_positions.add(pos_id)
                                            tag_names = [TAG_MAP.get(t, t) for t in market_tags[:3]]
                                            logging.info(f"⛔ TAG MISMATCH {spec.name} | {market} | Market tags: {tag_names}")
                                            continue
                                        else:
                                            # Copy-all mode: use first market tag for sizing/fees
                                            matched_tag = market_tags[0] if market_tags else "1"
                                            logging.debug(f"Tag mismatch but copying anyway: {spec.name} | {market}")
                                    
                                    # Get real market price from CLOB for slippage check
                                    # leader_price = specialist's avgPrice (what they paid)
                                    # current_market_price = best ask on the order book (what we'd pay)
                                    current_market_price = get_best_ask(pos_id)
                                    if current_market_price <= 0:
                                        current_market_price = price  # Fallback to avgPrice if CLOB unavailable
                                    
                                    status, msg_reason, bet_size = self.execute_trade_logic(spec, matched_tag, current_market_price, price, market, slug, outcome, cfg)
                                    
                                    if status == "PASSED":
                                        # Order book depth check before final execution
                                        has_liquidity, avail_liq = self.check_order_book_depth(pos_id, bet_size, cfg)
                                        if not has_liquidity and avail_liq > 0:
                                            logging.warning(f"⚠️ Low liquidity for {market}: ${avail_liq:.2f} available, need ${bet_size*2:.2f}")
                                            # Still proceed but note it — at Phase 1 sizes this is rarely an issue
                                        
                                        self.seen_positions.add(pos_id)
                                        # Inject real trade object back to Database with slippage info
                                        # price = leader_price (specialist's avgPrice)
                                        # current_market_price = our detection price
                                        self.db.add_trade(spec.name, market, current_market_price, slug, outcome, bet_size, endDate_str, price, current_market_price)
                                        
                                        wallet_bal = get_wallet_balance()
                                        remaining = wallet_bal  # Wallet already reflects spent USDC
                                        est_fee = FinanceController.estimate_taker_fee(current_market_price, matched_tag) * bet_size
                                        slippage = FinanceController.calculate_slippage_pct(price, current_market_price)
                                        
                                        link = f"https://polymarket.com/event/{slug}" if slug else ""
                                        msg = "\n".join([
                                            "✅ COPIED TRADE",
                                            "",
                                            f"📋 {market}",
                                            f"👤 {spec.name} ({spec.tier})",
                                            f"🎯 {outcome} @ ${current_market_price:.2f}",
                                            f"💵 Bet: ${bet_size:.2f} (est. fee: ${est_fee:.3f})",
                                            f"📉 Slippage: {slippage:+.2f}%",
                                            f"💰 Balance: ${remaining:.2f}",
                                            "",
                                            link
                                        ])
                                        self.send_telegram_alert(msg, category="buy")
                                        logging.info(f"✅ COPIED TRADE {spec.name} | {market} | {outcome} @ ${current_market_price:.2f} | Bet ${bet_size:.2f} | Slippage {slippage:+.2f}% | Bal ${remaining:.2f}")
                                        
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

            time.sleep(int(cfg.get('poll_interval', POLL_INTERVAL)))

    def execute_trade_logic(self, specialist: Specialist, market_tag: str, current_price: float, leader_price: float, market_name: str, slug: str = "", outcome: str = "", cfg: dict = None):
        """
        Runs the full check before entering a trade.
        Returns a tuple: (Status, Reason_String, Bet_Size)
        Status can be "PASSED", "PERMANENT_REJECT", or "TEMPORARY_REJECT".
        cfg is the bot_config dict loaded from the DB (all values as strings).
        """
        # 0. Collision Check / Opposing Bets
        recent_trades = self.db.get_all_recent_trades(50)
        for t in recent_trades:
            if t[4] != 'PENDING':
                continue
            trade_slug = t[5] if len(t) > 5 else ''
            trade_outcome = t[6] if len(t) > 6 else ''
            if slug and trade_slug and slug == trade_slug and outcome == trade_outcome:
                return "PERMANENT_REJECT", f"Already holding {outcome} on {market_name}", 0.0
            if not slug or not trade_slug:
                if t[1] == market_name:
                    return "PERMANENT_REJECT", f"Already holding an active position in {market_name}", 0.0

        # 1. Health Monitor Check
        win_rate = self.db.get_specialist_win_rate(specialist.name)
        sharp_min = float(cfg.get('sharp_min_win_rate', 55.0)) if cfg else 55.0
        whale_min = float(cfg.get('whale_min_win_rate', 40.0)) if cfg else 40.0
        min_win_rate = whale_min if specialist.tier == 'WHALE' else sharp_min

        if win_rate < min_win_rate:
            return "PERMANENT_REJECT", f"Probation (Win Rate {win_rate}% < {min_win_rate}%)", 0.0

        # 2. Correct Tag ID Mapping Check
        if str(market_tag) not in specialist.target_tags:
            tag_name = TAG_MAP.get(str(market_tag), market_tag)
            return "PERMANENT_REJECT", f"{tag_name} outside domain", 0.0

        # 3. Adaptive Value Caps
        max_entry = FinanceController.get_max_price_for_tag(market_tag, cfg)
        if current_price > max_entry:
            return "TEMPORARY_REJECT", f"Current Price {current_price} exceeds Value Cap {max_entry}", 0.0

        # 4. No Chase / Slippage Check
        threshold = float(cfg.get('slippage_threshold_pct', 2.5)) if cfg else 2.5
        if not FinanceController.is_slippage_acceptable(leader_price, current_price, cfg):
            return "TEMPORARY_REJECT", f"Price slipped to ${current_price:.3f} vs specialist's ${leader_price:.3f} (>{threshold}% gap)", 0.0

        # 5. Position Sizing
        wallet_balance = get_wallet_balance()
        min_buffer = float(cfg.get('min_wallet_buffer', 5.0)) if cfg else 5.0

        if wallet_balance < min_buffer:
            return "TEMPORARY_REJECT", f"Insufficient Balance (${wallet_balance:.2f} USDC, ${min_buffer:.2f} minimum)", 0.0

        bet_size = FinanceController.calculate_bet_size(wallet_balance, specialist.tier, win_rate, cfg)
        if bet_size > wallet_balance - min_buffer:
            bet_size = wallet_balance - min_buffer

        return "PASSED", f"Validated for ${bet_size:.2f} bet", float(bet_size)

    def process_harvesting(self, current_balance: float, cfg: dict = None):
        baseline, _ = self.db.get_performance()
        result = FinanceController.check_harvest(current_balance, baseline, cfg)
        if result.triggered:
            # Main Wallet Harvesting API Call goes here (Polygon transfer)
            self.db.update_performance_post_harvest(result.new_baseline, result.transfer_amount)
            logging.info(f"💸 HARVEST TRIGGERED: Sent ${result.transfer_amount:.2f} to personal wallet!")

if __name__ == "__main__":
    bot = PolymarketBot()
    bot.monitor_loop()
