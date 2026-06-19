import json
import logging
import threading
import time
from datetime import datetime

import pytz
import websockets.sync.client

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


class WebSocketMonitor:
    """Monitors active positions via Upstox WebSocket and triggers real-time exit checks."""

    FEED_URL = "wss://api.upstox.com/v2/feed/market-data-feed"

    def __init__(self, access_token: str, on_exit_trigger: callable):
        self.access_token = access_token
        self.on_exit_trigger = on_exit_trigger
        self._subscribed_keys: set[str] = set()
        self._ws = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def update_subscriptions(self, instrument_keys: set[str]):
        """Update the set of instrument keys to monitor."""
        added = instrument_keys - self._subscribed_keys
        removed = self._subscribed_keys - instrument_keys
        self._subscribed_keys = instrument_keys.copy()
        if self._ws and (added or removed):
            try:
                if added:
                    self._ws.send(json.dumps({
                        "guid": "sub",
                        "method": "sub",
                        "data": {"mode": "ltpc", "instrumentKeys": list(added)}
                    }))
                if removed:
                    self._ws.send(json.dumps({
                        "guid": "unsub",
                        "method": "unsub",
                        "data": {"instrumentKeys": list(removed)}
                    }))
            except Exception as e:
                logger.error(f"Failed to update WebSocket subscriptions: {e}")

    def start(self):
        """Start the WebSocket monitor in a background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ws-monitor")
        self._thread.start()
        logger.info("WebSocket monitor started.")

    def stop(self):
        """Stop the WebSocket monitor."""
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("WebSocket monitor stopped.")

    def _run(self):
        """Main WebSocket loop with automatic reconnection."""
        while not self._stop_event.is_set():
            try:
                now = datetime.now(IST)
                # Only run during market hours (9:00-15:30 IST, Mon-Fri)
                if now.weekday() >= 5 or now.hour < 9 or (now.hour >= 15 and now.minute > 30):
                    self._stop_event.wait(60)
                    continue

                headers = {"Authorization": f"Bearer {self.access_token}"}
                self._ws = websockets.sync.client.connect(
                    self.FEED_URL,
                    additional_headers=headers,
                    close_timeout=5,
                )
                logger.info("WebSocket connected to Upstox feed.")

                # Re-subscribe to current instruments
                if self._subscribed_keys:
                    self._ws.send(json.dumps({
                        "guid": "sub",
                        "method": "sub",
                        "data": {"mode": "ltpc", "instrumentKeys": list(self._subscribed_keys)}
                    }))

                for message in self._ws:
                    if self._stop_event.is_set():
                        break
                    self._handle_message(message)

            except Exception as e:
                if not self._stop_event.is_set():
                    logger.warning(f"WebSocket disconnected: {e}. Reconnecting in 5s...")
                    self._stop_event.wait(5)

    def _handle_message(self, raw_message):
        """Parse LTP updates and invoke exit trigger callback."""
        try:
            if isinstance(raw_message, bytes):
                # Upstox may send protobuf; skip binary for now, handle JSON
                return
            data = json.loads(raw_message)
            feeds = data.get("feeds", {})
            for instrument_key, feed_data in feeds.items():
                ltpc = feed_data.get("ff", {}).get("ltpc", {})
                ltp = ltpc.get("ltp")
                if ltp is not None and instrument_key in self._subscribed_keys:
                    self.on_exit_trigger(instrument_key, float(ltp))
        except Exception as e:
            logger.debug(f"Error parsing WebSocket message: {e}")
