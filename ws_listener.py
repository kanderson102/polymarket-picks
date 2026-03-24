"""
WebSocket listener for real-time Polymarket trade detection.
Monitors specialist wallets for new positions via the Polymarket CLOB WebSocket.

Falls back to HTTP polling if the WebSocket connection fails.
Auto-reconnects with exponential backoff + Telegram alerts.
"""
import json
import time
import logging
import threading

try:
    import websocket
except ImportError:
    websocket = None
    logging.getLogger(__name__).warning("websocket-client not installed. WebSocket features disabled. Install with: pip install websocket-client")

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PING_INTERVAL = 10  # Polymarket requires a PING every 10s
MAX_RECONNECT_ATTEMPTS = 5
BASE_RECONNECT_DELAY = 5  # seconds


class PolymarketWSListener:
    """
    Listens to the Polymarket CLOB WebSocket for real-time trade events.
    
    When a new trade is detected on a token we're monitoring, it calls
    the provided callback with the trade data.
    """
    
    def __init__(self, on_trade_callback=None, on_status_callback=None):
        """
        Args:
            on_trade_callback: Called with (asset_id, trade_data) when a new trade is detected
            on_status_callback: Called with (message) for status updates (connect/disconnect/error)
        """
        self.on_trade = on_trade_callback
        self.on_status = on_status_callback
        self.ws = None
        self.is_connected = False
        self.is_running = False
        self.monitored_assets = set()
        self._reconnect_count = 0
        self._thread = None
        self._ping_thread = None
        self._lock = threading.Lock()
    
    def start(self, asset_ids: list[str] = None):
        """Start the WebSocket listener in a background thread."""
        if websocket is None:
            logger.warning("🔌 WebSocket disabled (websocket-client not installed). Using HTTP polling only.")
            return
        
        self.is_running = True
        self._reconnect_count = 0
        if asset_ids:
            self.monitored_assets = set(asset_ids)
        
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("🔌 WebSocket listener thread started")
    
    def stop(self):
        """Stop the WebSocket listener."""
        self.is_running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        logger.info("🔌 WebSocket listener stopped")
    
    def update_monitored_assets(self, asset_ids: list[str]):
        """Update the set of asset IDs we're monitoring. Thread-safe."""
        with self._lock:
            new_assets = set(asset_ids) - self.monitored_assets
            self.monitored_assets = set(asset_ids)
        
        # Subscribe to new assets if connected
        if new_assets and self.is_connected and self.ws:
            self._subscribe(list(new_assets))
    
    def _run_loop(self):
        """Main reconnection loop. Runs in background thread."""
        while self.is_running:
            try:
                self._connect()
            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")
            
            if not self.is_running:
                break
            
            # Exponential backoff on reconnect
            self._reconnect_count += 1
            if self._reconnect_count > MAX_RECONNECT_ATTEMPTS:
                msg = f"🚨 WebSocket failed after {MAX_RECONNECT_ATTEMPTS} attempts. Falling back to HTTP polling."
                logger.error(msg)
                if self.on_status:
                    self.on_status(msg)
                # Wait longer before trying again (5 minutes)
                time.sleep(300)
                self._reconnect_count = 0
            else:
                delay = BASE_RECONNECT_DELAY * (2 ** (self._reconnect_count - 1))
                logger.info(f"🔄 WebSocket reconnecting in {delay}s (attempt {self._reconnect_count}/{MAX_RECONNECT_ATTEMPTS})")
                time.sleep(delay)
    
    def _connect(self):
        """Establish WebSocket connection."""
        self.ws = websocket.WebSocketApp(
            WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self.ws.run_forever()
    
    def _on_open(self, ws):
        """Called when WebSocket connection is established."""
        self.is_connected = True
        self._reconnect_count = 0
        
        msg = "✅ WebSocket connected to Polymarket CLOB"
        logger.info(msg)
        if self.on_status:
            self.on_status(msg)
        
        # Subscribe to monitored assets
        if self.monitored_assets:
            self._subscribe(list(self.monitored_assets))
        
        # Start ping thread to keep connection alive
        self._start_ping()
    
    def _on_message(self, ws, message):
        """Called when a message is received from the WebSocket."""
        try:
            data = json.loads(message)
            event_type = data.get('event_type', '')
            
            # We care about last_trade_price events (indicates a trade happened)
            if event_type == 'last_trade_price':
                asset_id = data.get('asset_id', '')
                if asset_id and self.on_trade:
                    self.on_trade(asset_id, data)
            
            # Also watch for market_resolved events
            elif event_type == 'market_resolved':
                if self.on_trade:
                    self.on_trade(data.get('asset_id', ''), data)
                    
        except json.JSONDecodeError:
            if message != 'PONG':
                logger.debug(f"Non-JSON WS message: {message}")
    
    def _on_error(self, ws, error):
        """Called when a WebSocket error occurs."""
        logger.error(f"WebSocket error: {error}")
        self.is_connected = False
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Called when WebSocket connection is closed."""
        self.is_connected = False
        logger.info(f"WebSocket closed (code={close_status_code})")
    
    def _subscribe(self, asset_ids: list[str]):
        """Subscribe to market data for specific assets."""
        if not self.ws or not self.is_connected:
            return
        
        try:
            subscribe_msg = {
                "type": "market",
                "assets_ids": asset_ids,
                "custom_feature_enabled": True  # Enable market_resolved events
            }
            self.ws.send(json.dumps(subscribe_msg))
            logger.info(f"📡 Subscribed to {len(asset_ids)} market assets via WebSocket")
        except Exception as e:
            logger.error(f"Failed to subscribe to WS channels: {e}")
    
    def _start_ping(self):
        """Start a background thread to send PINGs every 10 seconds."""
        def ping_loop():
            while self.is_connected and self.is_running:
                try:
                    if self.ws:
                        self.ws.send("PING")
                except Exception:
                    break
                time.sleep(PING_INTERVAL)
        
        self._ping_thread = threading.Thread(target=ping_loop, daemon=True)
        self._ping_thread.start()


def test_connection():
    """Quick test to verify WebSocket connectivity."""
    connected = threading.Event()
    messages_received = []
    
    def on_trade(asset_id, data):
        messages_received.append(data)
        print(f"  📨 Trade event: asset={asset_id[:20]}... price={data.get('price', '?')}")
    
    def on_status(msg):
        print(f"  Status: {msg}")
        if "connected" in msg.lower():
            connected.set()
    
    listener = PolymarketWSListener(on_trade_callback=on_trade, on_status_callback=on_status)
    listener.start()
    
    print("⏳ Waiting for WebSocket connection (10s timeout)...")
    if connected.wait(timeout=10):
        print("✅ WebSocket connection successful!")
        print("⏳ Listening for trade events (15s)...")
        time.sleep(15)
        print(f"📊 Received {len(messages_received)} trade events")
    else:
        print("❌ WebSocket connection timed out")
    
    listener.stop()
    print("🔌 Test complete")


if __name__ == "__main__":
    test_connection()
