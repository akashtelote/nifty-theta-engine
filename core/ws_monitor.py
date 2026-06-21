import logging
from typing import Callable

import upstox_client

logger = logging.getLogger(__name__)


class WebSocketMonitor:
    """Real-time LTP monitor using the Upstox SDK's MarketDataStreamerV3.

    The SDK handles protobuf decoding, the authorize-redirect handshake,
    and auto-reconnect internally.
    """

    def __init__(self, access_token: str, on_tick: Callable[[str, float], None]):
        cfg = upstox_client.Configuration()
        cfg.access_token = access_token
        api_client = upstox_client.ApiClient(cfg)
        self._streamer = upstox_client.MarketDataStreamerV3(
            api_client=api_client, instrumentKeys=[], mode="ltpc"
        )
        self._streamer.on("message", self._on_message)
        self._streamer.on("error", self._on_error)
        self._on_tick = on_tick
        self._subscribed_keys: set[str] = set()
        self._connected = False

    def start(self):
        self._streamer.connect()
        self._connected = True
        logger.info("WebSocket monitor started via SDK streamer.")

    def stop(self):
        try:
            self._streamer.disconnect()
        except Exception:
            pass
        self._connected = False
        logger.info("WebSocket monitor stopped.")

    def update_subscriptions(self, instrument_keys: set[str]):
        added = instrument_keys - self._subscribed_keys
        removed = self._subscribed_keys - instrument_keys

        if self._connected:
            try:
                if removed:
                    self._streamer.unsubscribe(list(removed))
                if added:
                    self._streamer.subscribe(list(added), "ltpc")
            except Exception as e:
                logger.error(f"Failed to update subscriptions: {e}")

        self._subscribed_keys = instrument_keys.copy()

    def _on_message(self, message: dict):
        feeds = message.get("feeds", {})
        for instrument_key, feed_data in feeds.items():
            ltpc = feed_data.get("ltpc", {})
            ltp = ltpc.get("ltp")
            if ltp is not None:
                self._on_tick(instrument_key, float(ltp))

    def _on_error(self, error):
        logger.warning(f"WebSocket error: {error}")
