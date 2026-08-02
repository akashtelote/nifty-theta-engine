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
            patch("core.auth.get_centralized_token", return_value="tok"),
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
            patch("core.auth.get_centralized_token", return_value=None),
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
            patch("core.auth.get_centralized_token", return_value="tok"),
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
