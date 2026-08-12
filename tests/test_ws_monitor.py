"""Tests for the real-time WebSocket exit monitor and debounced tick handler."""

import time
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

_FUTURE_EXPIRY = (date.today() + timedelta(days=30)).isoformat()


class TestWebSocketMonitor:
    """Tests for the SDK-backed WebSocketMonitor wrapper."""

    def _make_monitor(self):
        with patch("core.ws_monitor.upstox_client") as mock_upstox:
            mock_streamer = MagicMock()
            mock_upstox.MarketDataStreamerV3.return_value = mock_streamer
            from core.ws_monitor import WebSocketMonitor
            on_tick = MagicMock()
            monitor = WebSocketMonitor(access_token="test_token", on_tick=on_tick)
            return monitor, mock_streamer, on_tick

    def test_start_calls_streamer_connect(self):
        monitor, mock_streamer, _ = self._make_monitor()
        monitor.start()
        mock_streamer.connect.assert_called_once()

    def test_start_does_not_subscribe_before_open(self):
        """connect() is async — subscribing before the open event hits a dead socket."""
        monitor, mock_streamer, _ = self._make_monitor()
        monitor.start()
        monitor.update_subscriptions({"NSE_INDEX|Nifty 50"})
        mock_streamer.subscribe.assert_not_called()
        assert not monitor.is_alive()

    def test_open_event_applies_queued_subscriptions(self):
        monitor, mock_streamer, _ = self._make_monitor()
        monitor.start()
        monitor.update_subscriptions({"NSE_INDEX|Nifty 50"})
        monitor._on_open()
        assert set(mock_streamer.subscribe.call_args[0][0]) == {"NSE_INDEX|Nifty 50"}
        assert monitor.is_alive()

    def test_reconnect_resubscribes_after_close(self):
        monitor, mock_streamer, _ = self._make_monitor()
        monitor._on_open()
        monitor.update_subscriptions({"KEY_A"})
        monitor._on_close(1006, "lost")
        assert not monitor.is_alive()
        mock_streamer.subscribe.reset_mock()
        monitor._on_open()  # SDK auto-reconnect
        assert set(mock_streamer.subscribe.call_args[0][0]) == {"KEY_A"}

    def test_failed_subscribe_retries_on_next_update(self):
        monitor, mock_streamer, _ = self._make_monitor()
        monitor._on_open()
        mock_streamer.subscribe.side_effect = Exception("WebSocket is not open.")
        monitor.update_subscriptions({"KEY_A"})
        assert monitor._subscribed_keys == set()
        mock_streamer.subscribe.side_effect = None
        monitor.update_subscriptions({"KEY_A"})
        assert set(mock_streamer.subscribe.call_args[0][0]) == {"KEY_A"}

    def test_transient_error_does_not_alert(self):
        """Only autoReconnectStopped means we're actually offline."""
        monitor, _, _ = self._make_monitor()
        on_error = MagicMock()
        monitor._on_error_cb = on_error
        monitor._on_error("Connection to remote host was lost.")
        on_error.assert_not_called()
        monitor._on_reconnect_stopped("retryCount of 5 exhausted.")
        on_error.assert_called_once()
        assert not monitor.is_alive()

    def test_stop_calls_streamer_disconnect(self):
        monitor, mock_streamer, _ = self._make_monitor()
        monitor.start()
        monitor.stop()
        mock_streamer.disconnect.assert_called_once()

    def test_update_subscriptions_adds_new_keys(self):
        monitor, mock_streamer, _ = self._make_monitor()
        monitor._connected = True
        monitor.update_subscriptions({"NSE_INDEX|Nifty 50", "NSE_FO|NIFTY22000PE"})
        mock_streamer.subscribe.assert_called_once()
        call_args = mock_streamer.subscribe.call_args
        subscribed_keys = set(call_args[0][0])
        assert subscribed_keys == {"NSE_INDEX|Nifty 50", "NSE_FO|NIFTY22000PE"}

    def test_update_subscriptions_removes_old_keys(self):
        monitor, mock_streamer, _ = self._make_monitor()
        monitor._connected = True
        monitor._subscribed_keys = {"NSE_FO|OLD_KEY"}
        monitor.update_subscriptions({"NSE_FO|NEW_KEY"})
        mock_streamer.unsubscribe.assert_called_once()
        unsub_keys = set(mock_streamer.unsubscribe.call_args[0][0])
        assert unsub_keys == {"NSE_FO|OLD_KEY"}

    def test_update_subscriptions_diffs_correctly(self):
        monitor, mock_streamer, _ = self._make_monitor()
        monitor._connected = True
        monitor._subscribed_keys = {"KEY_A", "KEY_B"}
        monitor.update_subscriptions({"KEY_B", "KEY_C"})
        # Should add KEY_C, remove KEY_A, keep KEY_B
        sub_keys = set(mock_streamer.subscribe.call_args[0][0])
        unsub_keys = set(mock_streamer.unsubscribe.call_args[0][0])
        assert sub_keys == {"KEY_C"}
        assert unsub_keys == {"KEY_A"}
        assert monitor._subscribed_keys == {"KEY_B", "KEY_C"}

    def test_on_message_fires_on_tick_with_ltp(self):
        monitor, _, on_tick = self._make_monitor()
        message = {
            "feeds": {
                "NSE_INDEX|Nifty 50": {
                    "ltpc": {"ltp": 22150.0, "ltt": "1719900000000", "cp": 22100.0}
                }
            }
        }
        monitor._on_message(message)
        on_tick.assert_called_once_with("NSE_INDEX|Nifty 50", 22150.0)

    def test_on_message_ignores_empty_feeds(self):
        monitor, _, on_tick = self._make_monitor()
        monitor._on_message({"feeds": {}})
        on_tick.assert_not_called()

    def test_on_message_ignores_missing_ltp(self):
        monitor, _, on_tick = self._make_monitor()
        monitor._on_message({
            "feeds": {
                "NSE_INDEX|Nifty 50": {"ltpc": {"cp": 22100.0}}
            }
        })
        on_tick.assert_not_called()


class TestActiveInstrumentKeys:
    """Tests for WheelStateMachine.active_instrument_keys()."""

    def test_returns_keys_for_active_positions(self, wheel):
        wheel.state = {
            "Nifty 50": {
                "current_stage": "STAGE_1_CSP",
                "active_position": {"instrument_key": "NSE_FO|NIFTY22000PE"},
                "hedge_position": {"instrument_key": "NSE_FO|NIFTY21900PE"},
            }
        }
        keys = wheel.active_instrument_keys()
        assert "NSE_FO|NIFTY22000PE" in keys
        assert "NSE_FO|NIFTY21900PE" in keys

    def test_excludes_idle_positions(self, wheel):
        wheel.state = {
            "Nifty 50": {
                "current_stage": "IDLE",
                "active_position": None,
                "hedge_position": None,
            }
        }
        keys = wheel.active_instrument_keys()
        assert len(keys) == 0

    def test_includes_underlying_index_key(self, wheel):
        wheel.state = {
            "Nifty 50": {
                "current_stage": "STAGE_1_CSP",
                "active_position": {"instrument_key": "NSE_FO|NIFTY22000PE"},
                "hedge_position": {"instrument_key": "NSE_FO|NIFTY21900PE"},
            }
        }
        keys = wheel.active_instrument_keys()
        assert "NSE_INDEX|Nifty 50" in keys


class TestExitThresholdCache:
    """Tests for the in-memory exit threshold cache."""

    def test_refresh_populates_thresholds(self, wheel):
        wheel.state = {
            "Nifty 50": {
                "current_stage": "STAGE_1_CSP",
                "active_position": {
                    "instrument_key": "NSE_FO|NIFTY22000PE",
                    "strike": 22000.0,
                    "entry_price": 50.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                },
                "hedge_position": {
                    "instrument_key": "NSE_FO|NIFTY21900PE",
                    "strike": 21900.0,
                    "entry_price": 30.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                },
                "net_credit_received": 500.0,
                "lifetime_realized_pnl": 0.0,
            }
        }
        wheel.refresh_exit_thresholds()
        assert "Nifty 50" in wheel._exit_thresholds
        t = wheel._exit_thresholds["Nifty 50"]
        assert t["short_strike"] == 22000.0
        assert t["initial_credit"] == 20.0  # 50 - 30

    def test_empty_when_no_active_positions(self, wheel):
        wheel.state = {
            "Nifty 50": {
                "current_stage": "IDLE",
                "active_position": None,
                "hedge_position": None,
                "net_credit_received": 0.0,
                "lifetime_realized_pnl": 0.0,
            }
        }
        wheel.refresh_exit_thresholds()
        assert "Nifty 50" not in wheel._exit_thresholds


class TestDebouncedRealtimeTick:
    """Tests for on_realtime_tick with debounce logic."""

    def test_no_exit_when_spot_above_strike(self, wheel, mock_client):
        wheel.state = {
            "Nifty 50": {
                "current_stage": "STAGE_1_CSP",
                "active_position": {
                    "instrument_key": "NSE_FO|NIFTY22000PE",
                    "strike": 22000.0,
                    "entry_price": 50.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                    "order_id": "ORD1",
                },
                "hedge_position": {
                    "instrument_key": "NSE_FO|NIFTY21900PE",
                    "strike": 21900.0,
                    "entry_price": 30.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                    "order_id": "ORD2",
                },
                "net_credit_received": 500.0,
                "lifetime_realized_pnl": 0.0,
            }
        }
        wheel.refresh_exit_thresholds()
        wheel.on_realtime_tick("NSE_INDEX|Nifty 50", 23000.0)
        mock_client.place_order_by_key.assert_not_called()

    def test_single_breach_tick_does_not_exit_immediately(self, wheel, mock_client):
        """Debounce: a single breach tick should NOT trigger exit."""
        wheel.state = {
            "Nifty 50": {
                "current_stage": "STAGE_1_CSP",
                "active_position": {
                    "instrument_key": "NSE_FO|NIFTY22000PE",
                    "strike": 22000.0,
                    "entry_price": 50.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                    "order_id": "ORD1",
                },
                "hedge_position": {
                    "instrument_key": "NSE_FO|NIFTY21900PE",
                    "strike": 21900.0,
                    "entry_price": 30.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                    "order_id": "ORD2",
                },
                "net_credit_received": 500.0,
                "lifetime_realized_pnl": 0.0,
            }
        }
        wheel.refresh_exit_thresholds()
        # Spot breaches short strike (22000) but only one tick
        wheel.on_realtime_tick("NSE_INDEX|Nifty 50", 21950.0)
        mock_client.place_order_by_key.assert_not_called()

    def test_no_exit_when_touch_stop_disabled(self, wheel, mock_client, monkeypatch):
        """STOP_ON_STRIKE_TOUCH=False must make the real-time monitor inert, debounce included."""
        from config import settings as settings_mod
        wheel.state = {
            "Nifty 50": {
                "current_stage": "STAGE_1_CSP",
                "active_position": {
                    "instrument_key": "NSE_FO|NIFTY22000PE",
                    "strike": 22000.0,
                    "entry_price": 50.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                    "order_id": "ORD1",
                },
                "hedge_position": {
                    "instrument_key": "NSE_FO|NIFTY21900PE",
                    "strike": 21900.0,
                    "entry_price": 30.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                    "order_id": "ORD2",
                },
                "net_credit_received": 500.0,
                "lifetime_realized_pnl": 0.0,
            }
        }
        wheel.refresh_exit_thresholds()
        # Pre-load a breach old enough that the debounce window has already elapsed,
        # so the only thing standing between this tick and an exit is the flag.
        wheel._breach_first_seen["Nifty 50"] = time.monotonic() - wheel.DEBOUNCE_SECONDS - 1
        monkeypatch.setattr(settings_mod.settings, "STOP_ON_STRIKE_TOUCH", False)
        wheel.on_realtime_tick("NSE_INDEX|Nifty 50", 21950.0)
        mock_client.place_order_by_key.assert_not_called()
        assert wheel._breach_first_seen == {}

    def test_ignores_unknown_instrument_key(self, wheel):
        wheel._exit_thresholds = {}
        wheel.on_realtime_tick("NSE_INDEX|Unknown", 100.0)
        # Should not raise or trigger anything

    def test_ignores_tick_when_exit_in_progress(self, wheel, mock_client):
        """If exit is already running for a symbol, skip further ticks."""
        wheel.state = {
            "Nifty 50": {
                "current_stage": "STAGE_1_CSP",
                "active_position": {
                    "instrument_key": "NSE_FO|NIFTY22000PE",
                    "strike": 22000.0,
                    "entry_price": 50.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                    "order_id": "ORD1",
                },
                "hedge_position": {
                    "instrument_key": "NSE_FO|NIFTY21900PE",
                    "strike": 21900.0,
                    "entry_price": 30.0,
                    "expiry": _FUTURE_EXPIRY,
                    "quantity": 25,
                    "order_id": "ORD2",
                },
                "net_credit_received": 500.0,
                "lifetime_realized_pnl": 0.0,
            }
        }
        wheel.refresh_exit_thresholds()
        wheel._exit_in_progress.add("Nifty 50")
        wheel.on_realtime_tick("NSE_INDEX|Nifty 50", 21950.0)
        mock_client.place_order_by_key.assert_not_called()
