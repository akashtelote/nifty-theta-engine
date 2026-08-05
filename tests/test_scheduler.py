"""Tests for scheduler WebSocket start gating and Discord fallback alerts."""

from unittest.mock import MagicMock, patch

import core.scheduler as scheduler


def _reset_ws_state():
    scheduler._ws_wheel = None
    scheduler._ws_monitor = None
    scheduler._ws_fallback_alerted = False


class TestStartWsMonitor:
    def setup_method(self):
        _reset_ws_state()

    def teardown_method(self):
        _reset_ws_state()

    def test_skips_when_mock_market(self):
        with (
            patch.object(scheduler.settings, "MOCK_MARKET", True),
            patch.object(scheduler.settings, "PAPER_TRADE", True),
            patch("core.scheduler.Notifier") as mock_notifier_cls,
        ):
            assert scheduler._start_ws_monitor() is False
            mock_notifier_cls.assert_not_called()

    def test_starts_in_paper_trade_when_token_present(self):
        mock_monitor = MagicMock()
        mock_wheel = MagicMock()
        mock_wheel.active_instrument_keys.return_value = set()

        with (
            patch.object(scheduler.settings, "MOCK_MARKET", False),
            patch.object(scheduler.settings, "PAPER_TRADE", True),
            patch("core.scheduler._live_access_token", return_value="tok"),
            patch("core.ws_monitor.WebSocketMonitor", return_value=mock_monitor) as mon_cls,
            patch("core.scheduler.WheelStateMachine", return_value=mock_wheel),
            patch("core.scheduler.Notifier") as mock_notifier_cls,
        ):
            assert scheduler._start_ws_monitor() is True
            mon_cls.assert_called_once()
            kwargs = mon_cls.call_args.kwargs
            assert kwargs["access_token"] == "tok"
            assert callable(kwargs["on_tick"])
            assert callable(kwargs["on_error"])
            mock_monitor.start.assert_called_once()
            mock_notifier_cls.assert_not_called()
            assert scheduler._ws_fallback_alerted is False

    def test_missing_token_alerts_once(self):
        mock_notifier = MagicMock()

        with (
            patch.object(scheduler.settings, "MOCK_MARKET", False),
            patch.object(scheduler.settings, "PAPER_TRADE", True),
            patch("core.scheduler._live_access_token", return_value=None),
            patch("core.scheduler.Notifier", return_value=mock_notifier),
        ):
            assert scheduler._start_ws_monitor() is False
            assert scheduler._start_ws_monitor() is False
            mock_notifier.send_notification.assert_called_once()
            call_kwargs = mock_notifier.send_notification.call_args.kwargs
            assert call_kwargs["level"] == "WARNING"
            assert "token" in call_kwargs["message"].lower()

    def test_start_exception_alerts_and_debounces(self):
        mock_notifier = MagicMock()

        with (
            patch.object(scheduler.settings, "MOCK_MARKET", False),
            patch.object(scheduler.settings, "PAPER_TRADE", False),
            patch("core.scheduler._live_access_token", return_value="tok"),
            patch("core.scheduler.WheelStateMachine", side_effect=RuntimeError("boom")),
            patch("core.scheduler.Notifier", return_value=mock_notifier),
        ):
            assert scheduler._start_ws_monitor() is False
            scheduler._notify_ws_fallback("Could not start WebSocket monitor: boom.")
            mock_notifier.send_notification.assert_called_once()
            assert scheduler._ws_fallback_alerted is True

    def test_runtime_error_callback_debounced(self):
        mock_notifier = MagicMock()

        with patch("core.scheduler.Notifier", return_value=mock_notifier):
            scheduler._on_ws_runtime_error("disconnect")
            scheduler._on_ws_runtime_error("disconnect again")
            mock_notifier.send_notification.assert_called_once()
            assert mock_notifier.send_notification.call_args.kwargs["level"] == "WARNING"


class TestLiveAccessToken:
    def test_returns_token_healed_by_rest_call_not_stale_cache(self):
        """Overnight-expired token must be refreshed before the WS handshake."""
        client = MagicMock()
        client.access_token = "stale-tok"

        def heal():
            client.access_token = "fresh-tok"  # mirrors UpstoxClient's 401 self-heal
            return 12.5

        client.get_india_vix.side_effect = heal

        with patch("core.client.UpstoxClient", return_value=client):
            assert scheduler._live_access_token() == "fresh-tok"

        client.get_india_vix.assert_called_once()


class TestRestartWsMonitor:
    def setup_method(self):
        _reset_ws_state()

    def teardown_method(self):
        _reset_ws_state()

    def test_stop_clears_monitor_and_wheel(self):
        mock_monitor = MagicMock()
        scheduler._ws_monitor = mock_monitor
        scheduler._ws_wheel = MagicMock()

        scheduler._stop_ws_monitor()

        mock_monitor.stop.assert_called_once()
        assert scheduler._ws_monitor is None
        assert scheduler._ws_wheel is None

    def test_restart_stops_old_and_starts(self):
        old_monitor = MagicMock()
        new_monitor = MagicMock()
        mock_wheel = MagicMock()
        mock_wheel.active_instrument_keys.return_value = {"NSE_INDEX|Nifty 50"}
        scheduler._ws_monitor = old_monitor
        scheduler._ws_wheel = MagicMock()
        scheduler._ws_fallback_alerted = True

        with (
            patch.object(scheduler.settings, "MOCK_MARKET", False),
            patch.object(scheduler.settings, "PAPER_TRADE", True),
            patch("core.scheduler._live_access_token", return_value="fresh-tok"),
            patch("core.ws_monitor.WebSocketMonitor", return_value=new_monitor) as mon_cls,
            patch("core.scheduler.WheelStateMachine", return_value=mock_wheel),
        ):
            assert scheduler._restart_ws_monitor() is True

        old_monitor.stop.assert_called_once()
        mon_cls.assert_called_once()
        assert mon_cls.call_args.kwargs["access_token"] == "fresh-tok"
        new_monitor.start.assert_called_once()
        new_monitor.update_subscriptions.assert_called_once_with({"NSE_INDEX|Nifty 50"})
        assert mon_cls.call_args.kwargs["on_open"] is scheduler._on_ws_connected
        assert scheduler._ws_monitor is new_monitor

    def test_connected_callback_clears_fallback_and_notifies(self):
        """Only a real socket open clears the flag — and tells Discord we're back."""
        mock_notifier = MagicMock()
        scheduler._ws_fallback_alerted = True

        with patch("core.scheduler.Notifier", return_value=mock_notifier):
            scheduler._on_ws_connected()
            scheduler._on_ws_connected()  # already clear — must stay quiet

        assert scheduler._ws_fallback_alerted is False
        mock_notifier.send_notification.assert_called_once()

    def test_failed_restart_while_alerted_does_not_respam(self):
        """Hourly re-arm retries must not fire a Discord alert per attempt."""
        mock_notifier = MagicMock()
        scheduler._ws_fallback_alerted = True
        scheduler._ws_monitor = MagicMock()

        with (
            patch.object(scheduler.settings, "MOCK_MARKET", False),
            patch("core.scheduler._live_access_token", return_value=None),
            patch("core.scheduler.Notifier", return_value=mock_notifier),
        ):
            assert scheduler._restart_ws_monitor() is False

        mock_notifier.send_notification.assert_not_called()
        assert scheduler._ws_fallback_alerted is True
