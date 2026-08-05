import logging
from typing import Callable

import upstox_client

logger = logging.getLogger(__name__)


class WebSocketMonitor:
    """Real-time LTP monitor using the Upstox SDK's MarketDataStreamerV3.

    The SDK handles protobuf decoding, the authorize-redirect handshake,
    and auto-reconnect internally.
    """

    def __init__(
        self,
        access_token: str,
        on_tick: Callable[[str, float], None],
        on_error: Callable[[object], None] | None = None,
        on_open: Callable[[], None] | None = None,
    ):
        cfg = upstox_client.Configuration()
        cfg.access_token = access_token
        api_client = upstox_client.ApiClient(cfg)
        self._streamer = upstox_client.MarketDataStreamerV3(
            api_client=api_client, instrumentKeys=[], mode="ltpc"
        )
        self._streamer.on("message", self._on_message)
        self._streamer.on("error", self._on_error)
        self._streamer.on("open", self._on_open)
        self._streamer.on("close", self._on_close)
        self._streamer.on("autoReconnectStopped", self._on_reconnect_stopped)
        self._on_tick = on_tick
        self._on_error_cb = on_error
        self._on_open_cb = on_open
        self._desired_keys: set[str] = set()
        self._subscribed_keys: set[str] = set()
        self._connected = False

    def start(self):
        # connect() returns before the socket handshake completes; _connected is
        # set by the "open" event so we never subscribe against a dead socket.
        self._streamer.connect()
        logger.info("WebSocket monitor started via SDK streamer.")

    def stop(self):
        try:
            self._streamer.disconnect()
        except Exception:
            pass
        self._connected = False
        logger.info("WebSocket monitor stopped.")

    def is_alive(self) -> bool:
        return self._connected

    def update_subscriptions(self, instrument_keys: set[str]):
        """Record the desired subscription set and apply it if the socket is up."""
        self._desired_keys = set(instrument_keys)
        if self._connected:
            self._apply_subscriptions()

    def _apply_subscriptions(self):
        added = self._desired_keys - self._subscribed_keys
        removed = self._subscribed_keys - self._desired_keys
        try:
            if removed:
                self._streamer.unsubscribe(list(removed))
            if added:
                self._streamer.subscribe(list(added), "ltpc")
            self._subscribed_keys = set(self._desired_keys)
        except Exception as e:
            # Leave _subscribed_keys stale so the next call/reconnect retries the diff.
            logger.error(f"Failed to update subscriptions: {e}")

    def _on_message(self, message: dict):
        feeds = message.get("feeds", {})
        for instrument_key, feed_data in feeds.items():
            ltpc = feed_data.get("ltpc", {})
            ltp = ltpc.get("ltp")
            if ltp is not None:
                self._on_tick(instrument_key, float(ltp))

    def _on_open(self):
        """Socket up (first connect or SDK auto-reconnect) — resubscribe from scratch."""
        self._connected = True
        self._subscribed_keys = set()
        logger.info("WebSocket connected.")
        self._apply_subscriptions()
        if self._on_open_cb is not None:
            try:
                self._on_open_cb()
            except Exception as e:
                logger.error(f"WebSocket on_open callback failed: {e}")

    def _on_close(self, close_status_code=None, close_msg=None):
        self._connected = False
        logger.warning(f"WebSocket closed (code={close_status_code}): {close_msg}")

    def _on_error(self, error):
        # Transient drops self-heal via the SDK's auto-reconnect; only log here.
        logger.warning(f"WebSocket error: {error}")

    def _on_reconnect_stopped(self, reason):
        """SDK exhausted its retries — this is the real 'we are offline' signal."""
        self._connected = False
        if self._on_error_cb is not None:
            try:
                self._on_error_cb(reason)
            except Exception as e:
                logger.error(f"WebSocket on_error callback failed: {e}")
