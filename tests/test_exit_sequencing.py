"""Tests for sequenced exit legs (cover-first) and real-fill P&L accuracy.

Exit order must be: buy-to-close short FIRST → verify → sell-to-close hedge SECOND.
This mirrors the hedge-first entry and prevents a naked-short window.
"""

from datetime import date, timedelta

import polars as pl
from unittest.mock import MagicMock, patch

from config.settings import round_trip_fees

_FUTURE_EXPIRY = (date.today() + timedelta(days=30)).isoformat()


def _make_active_state():
    """Standard STAGE_1_CSP state for exit tests."""
    return {
        "Nifty 50": {
            "current_stage": "STAGE_1_CSP",
            "active_position": {
                "instrument_key": "NSE_FO|NIFTY22000PE",
                "strike": 22000.0,
                "expiry": _FUTURE_EXPIRY,
                "entry_price": 50.0,
                "order_id": "ORD_SHORT",
                "quantity": 25,
            },
            "hedge_position": {
                "instrument_key": "NSE_FO|NIFTY21900PE",
                "strike": 21900.0,
                "expiry": _FUTURE_EXPIRY,
                "entry_price": 30.0,
                "order_id": "ORD_LONG",
                "quantity": 25,
            },
            "net_credit_received": 500.0,  # (50-30)*25
            "lifetime_realized_pnl": 0.0,
        }
    }


def _make_tp_chain():
    """Option chain where cost-to-close triggers take-profit (<=20% of initial credit)."""
    # initial_credit = 50 - 30 = 20 per unit
    # cost_to_close = short_ask - long_bid = 2.0 - 1.0 = 1.0 (<= 20% * 20 = 4.0) → TP
    return pl.DataFrame([
        {"instrument_key": "NSE_FO|NIFTY22000PE", "type": "PE", "strike": 22000.0,
         "expiry": _FUTURE_EXPIRY, "bid": 1.5, "ask": 2.0, "last_price": 1.75},
        {"instrument_key": "NSE_FO|NIFTY21900PE", "type": "PE", "strike": 21900.0,
         "expiry": _FUTURE_EXPIRY, "bid": 1.0, "ask": 1.5, "last_price": 1.25},
    ])


class TestExitLegSequencing:
    """Verify exits place BTC (buy short) first, then STC (sell hedge)."""

    @patch("time.sleep", return_value=None)
    def test_btc_placed_before_stc(self, mock_sleep, wheel, mock_client):
        """The first place_order_by_key call must be BUY on the short leg."""
        wheel.state = _make_active_state()
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = _make_tp_chain()
        mock_client.get_order_status.return_value = "complete"
        mock_client.place_order_by_key.return_value = "PAPER_exit1"
        mock_client.get_order_fill_price.return_value = 2.04

        wheel.check_exits()

        calls = mock_client.place_order_by_key.call_args_list
        assert len(calls) == 2

        # First call: BUY the short leg (buy-to-close)
        first_call = calls[0]
        assert first_call.kwargs.get("instrument_key", first_call.args[0] if first_call.args else None) == "NSE_FO|NIFTY22000PE" or \
               first_call[1].get("instrument_key") == "NSE_FO|NIFTY22000PE" or \
               (len(first_call.args) > 0 and first_call.args[0] == "NSE_FO|NIFTY22000PE")
        # Side must be BUY
        first_side = first_call.kwargs.get("side", first_call.args[1] if len(first_call.args) > 1 else None)
        assert first_side == "BUY"

        # Second call: SELL the hedge leg (sell-to-close)
        second_call = calls[1]
        second_key = second_call.kwargs.get("instrument_key", second_call.args[0] if second_call.args else None)
        assert second_key == "NSE_FO|NIFTY21900PE"
        second_side = second_call.kwargs.get("side", second_call.args[1] if len(second_call.args) > 1 else None)
        assert second_side == "SELL"


class TestBtcFailureLeavesSpreadIntact:
    """When buy-to-close fails, the intact spread must remain (no naked short)."""

    @patch("time.sleep", return_value=None)
    def test_btc_place_fails_no_stc_attempted(self, mock_sleep, wheel, mock_client, mock_notifier):
        """If BTC order placement returns None, STC must NOT be placed."""
        wheel.state = _make_active_state()
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = _make_tp_chain()
        mock_client.place_order_by_key.return_value = None  # BTC fails to place

        wheel.check_exits()

        # Only one call attempted (BTC), no STC
        assert mock_client.place_order_by_key.call_count == 1
        # State stays STAGE_1_CSP
        assert wheel.state["Nifty 50"]["current_stage"] == "STAGE_1_CSP"
        assert wheel.state["Nifty 50"]["active_position"] is not None
        assert wheel.state["Nifty 50"]["hedge_position"] is not None

    @patch("time.sleep", return_value=None)
    def test_btc_timeout_cancels_and_keeps_spread(self, mock_sleep, wheel, mock_client, mock_notifier):
        """If BTC order times out (stays pending), cancel it and keep the spread."""
        wheel.state = _make_active_state()
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = _make_tp_chain()
        mock_client.place_order_by_key.return_value = "ORD_BTC_1"
        mock_client.get_order_status.return_value = "pending"  # Never fills

        wheel.check_exits()

        mock_client.cancel_order.assert_called_with("ORD_BTC_1")
        assert mock_client.place_order_by_key.call_count == 1  # No STC attempted
        assert wheel.state["Nifty 50"]["current_stage"] == "STAGE_1_CSP"

    @patch("time.sleep", return_value=None)
    def test_btc_rejected_keeps_spread(self, mock_sleep, wheel, mock_client, mock_notifier):
        """If BTC order is rejected by exchange, keep the spread intact."""
        wheel.state = _make_active_state()
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = _make_tp_chain()
        mock_client.place_order_by_key.return_value = "ORD_BTC_2"
        mock_client.get_order_status.return_value = "rejected"

        wheel.check_exits()

        assert mock_client.place_order_by_key.call_count == 1
        assert wheel.state["Nifty 50"]["current_stage"] == "STAGE_1_CSP"


class TestStcFailureAfterBtcFill:
    """When BTC fills but STC fails, short is covered — only a benign long put remains."""

    @patch("time.sleep", return_value=None)
    def test_stc_fails_archives_with_residual_alert(self, mock_sleep, wheel, mock_client, mock_notifier):
        """BTC fills, STC placement fails → archive trade, alert about residual long put."""
        wheel.state = _make_active_state()
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = _make_tp_chain()
        # BTC succeeds, STC fails to place
        mock_client.place_order_by_key.side_effect = ["ORD_BTC_OK", None]
        mock_client.get_order_status.return_value = "complete"
        mock_client.get_order_fill_price.return_value = 2.04

        wheel.check_exits()

        # State should move to CLOSED (short is covered — safe)
        assert wheel.state["Nifty 50"]["current_stage"] == "CLOSED"
        # Notification about residual long put
        notif_calls = mock_notifier.send_notification.call_args_list
        residual_alerts = [c for c in notif_calls if "residual" in str(c).lower() or "hedge" in str(c).lower()]
        assert len(residual_alerts) > 0

    @patch("time.sleep", return_value=None)
    def test_stc_timeout_still_closes_with_alert(self, mock_sleep, wheel, mock_client, mock_notifier):
        """BTC fills, STC times out → close position (short covered), alert for manual hedge close."""
        wheel.state = _make_active_state()
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = _make_tp_chain()
        mock_client.place_order_by_key.side_effect = ["ORD_BTC_OK", "ORD_STC_PEND"]
        # BTC fills, STC stays pending
        mock_client.get_order_status.side_effect = lambda oid: "complete" if oid == "ORD_BTC_OK" else "pending"
        mock_client.get_order_fill_price.side_effect = lambda oid: 2.04 if oid == "ORD_BTC_OK" else None

        wheel.check_exits()

        assert wheel.state["Nifty 50"]["current_stage"] == "CLOSED"


class TestRealFillPnl:
    """P&L must use actual fill prices, not theoretical pre-trade quotes."""

    @patch("time.sleep", return_value=None)
    def test_pnl_uses_fill_prices(self, mock_sleep, wheel, mock_client):
        """Verify realized_pnl is calculated from real fills, not the pre-trade snapshot."""
        wheel.state = _make_active_state()
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = _make_tp_chain()
        mock_client.place_order_by_key.side_effect = ["ORD_BTC", "ORD_STC"]
        mock_client.get_order_status.return_value = "complete"

        # Real fills differ from quotes:
        # BTC filled at 2.10 (worse than ask 2.0 — slippage)
        # STC filled at 0.90 (worse than bid 1.0 — slippage)
        # actual_cost_to_close = 2.10 - 0.90 = 1.20
        # initial_credit = 50.0 - 30.0 = 20.0
        # gross pnl = (20.0 - 1.20) * 25 = 470.0, booked net of round-trip fees
        mock_client.get_order_fill_price.side_effect = lambda oid: 2.10 if oid == "ORD_BTC" else 0.90

        # Spy on _archive_trade to capture the P&L it receives
        archive_calls = []
        wheel._archive_trade = lambda sym, reason, pnl, exit_slippage_per_leg=None: archive_calls.append((sym, reason, pnl))

        wheel.check_exits()

        assert len(archive_calls) == 1
        _, _, recorded_pnl = archive_calls[0]
        expected_pnl = (20.0 - 1.20) * 25 - round_trip_fees(20.0, 1.20, 25, 1)
        assert abs(recorded_pnl - expected_pnl) < 0.01, f"Expected {expected_pnl}, got {recorded_pnl}"

    @patch("time.sleep", return_value=None)
    def test_pnl_fallback_when_fill_price_unavailable(self, mock_sleep, wheel, mock_client):
        """If get_order_fill_price returns None, fall back to theoretical cost."""
        wheel.state = _make_active_state()
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = _make_tp_chain()
        mock_client.place_order_by_key.side_effect = ["ORD_BTC", "ORD_STC"]
        mock_client.get_order_status.return_value = "complete"
        mock_client.get_order_fill_price.return_value = None  # Unavailable

        archive_calls = []
        wheel._archive_trade = lambda sym, reason, pnl, exit_slippage_per_leg=None: archive_calls.append((sym, reason, pnl))

        wheel.check_exits()

        assert len(archive_calls) == 1
        # Fallback: theoretical cost_to_close = short_ask - long_bid = 2.0 - 1.0 = 1.0
        # gross pnl = (20.0 - 1.0) * 25 = 475.0, booked net of round-trip fees
        _, _, recorded_pnl = archive_calls[0]
        expected_pnl = (20.0 - 1.0) * 25 - round_trip_fees(20.0, 1.0, 25, 1)
        assert abs(recorded_pnl - expected_pnl) < 0.01


class TestGetOrderFillPrice:
    """Tests for UpstoxClient.get_order_fill_price()."""

    def test_paper_trade_returns_none(self):
        from core.client import UpstoxClient
        with patch.object(UpstoxClient, "__init__", lambda self: None):
            client = UpstoxClient()
            client.is_paper_trade = True
            result = client.get_order_fill_price("PAPER_abc123")
            assert result is None

    def test_live_returns_average_price(self):
        from core.client import UpstoxClient
        with patch.object(UpstoxClient, "__init__", lambda self: None):
            client = UpstoxClient()
            client.is_paper_trade = False
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"order_id": "ORD123", "status": "complete", "average_price": 42.50}]
            }
            with patch.object(client, "_make_authenticated_request", return_value=mock_response):
                result = client.get_order_fill_price("ORD123")
                assert result == 42.50

    def test_live_returns_none_on_api_failure(self):
        from core.client import UpstoxClient
        with patch.object(UpstoxClient, "__init__", lambda self: None):
            client = UpstoxClient()
            client.is_paper_trade = False
            with patch.object(client, "_make_authenticated_request", return_value=None):
                result = client.get_order_fill_price("ORD123")
                assert result is None


class TestFillQualityCapture:
    """PROF-022: realized slippage must survive to trade_history, not just stdout."""

    def test_entry_slippage_is_half_the_credit_shortfall(self, wheel):
        from strategies.wheel_strategy import WheelStateMachine
        state = {"theoretical_credit": 20.0, "net_credit_received": 19.0 * 65}
        # 1.0 point of credit given up across 2 legs = 0.5 per leg
        assert WheelStateMachine._entry_slippage_per_leg(state, 65) == 0.5

    def test_entry_slippage_none_without_baseline(self, wheel):
        from strategies.wheel_strategy import WheelStateMachine
        state = {"net_credit_received": 1000.0}
        assert WheelStateMachine._entry_slippage_per_leg(state, 65) is None

    def test_entry_slippage_none_without_quantity(self, wheel):
        from strategies.wheel_strategy import WheelStateMachine
        state = {"theoretical_credit": 20.0, "net_credit_received": 1000.0}
        assert WheelStateMachine._entry_slippage_per_leg(state, 0) is None

    @patch("time.sleep", return_value=None)
    def test_exit_slippage_reaches_archive(self, mock_sleep, wheel, mock_client):
        captured = {}
        wheel._archive_trade = lambda sym, reason, pnl, exit_slippage_per_leg=None: captured.update(
            {"slippage": exit_slippage_per_leg}
        )
        wheel.state["Nifty 50"] = {
            "current_stage": "STAGE_1_CSP", "lifetime_realized_pnl": 0.0,
            "active_position": {}, "hedge_position": {},
        }
        mock_client.get_order_fill_price.side_effect = [31.0, 9.0]  # ctc 22 vs 20 theoretical
        wheel._execute_exit("Nifty 50", "Take Profit", {
            "short_instrument_key": "S", "long_instrument_key": "L", "quantity": 65,
            "short_live_ask": 30.0, "long_live_bid": 10.0,
            "initial_credit": 40.0, "current_cost_to_close": 20.0,
        })
        assert captured["slippage"] == 1.0


def _quoted_chain():
    """Chain whose target spread has a known mid/natural gap.

    Short 21700 (bid 50 / ask 51, mid 50.5), long 21600 (bid 30 / ask 31, mid 30.5):
    natural credit 50 - 31 = 19.0, mid credit 50.5 - 30.5 = 20.0, half-spread 0.5/leg.
    """
    expiry = (date.today() + timedelta(days=20)).isoformat()
    return pl.DataFrame([
        {"instrument_key": "NSE_FO|NIFTY21700PE", "type": "PE", "strike": 21700.0,
         "expiry": expiry, "bid": 50.0, "ask": 51.0, "last_price": 50.5},
        {"instrument_key": "NSE_FO|NIFTY21600PE", "type": "PE", "strike": 21600.0,
         "expiry": expiry, "bid": 30.0, "ask": 31.0, "last_price": 30.5},
    ])


class TestSpreadQualitySampler:
    """PROF-022: the half-spread must be observable without an entry firing."""

    def test_returns_half_the_mid_natural_gap(self, wheel, mock_client):
        mock_client.get_option_chain.return_value = _quoted_chain()
        assert wheel.sample_spread_quality("Nifty 50") == 0.5

    def test_places_no_orders(self, wheel, mock_client):
        mock_client.get_option_chain.return_value = _quoted_chain()
        wheel.sample_spread_quality("Nifty 50")
        mock_client.place_order_by_key.assert_not_called()

    def test_samples_even_when_vix_would_block_entry(self, wheel, mock_client):
        # VIX 30 trips the entry circuit breaker outright; wide-VIX days are precisely
        # the ones a slippage sample must not omit. Strikes sit lower here because the
        # regime widens OTM to 1.5%, which is the selection the sampler should follow.
        expiry = (date.today() + timedelta(days=20)).isoformat()
        mock_client.get_india_vix.return_value = 30.0
        mock_client.get_option_chain.return_value = pl.DataFrame([
            {"instrument_key": "NSE_FO|NIFTY21600PE", "type": "PE", "strike": 21600.0,
             "expiry": expiry, "bid": 50.0, "ask": 51.0, "last_price": 50.5},
            {"instrument_key": "NSE_FO|NIFTY21500PE", "type": "PE", "strike": 21500.0,
             "expiry": expiry, "bid": 30.0, "ask": 31.0, "last_price": 30.5},
        ])
        assert wheel.sample_spread_quality("Nifty 50") == 0.5

    def test_returns_none_without_a_target_spread(self, wheel, mock_client):
        mock_client.get_option_chain.return_value = pl.DataFrame(schema={
            "instrument_key": pl.Utf8, "type": pl.Utf8, "strike": pl.Float64,
            "expiry": pl.Utf8, "bid": pl.Float64, "ask": pl.Float64, "last_price": pl.Float64
        })
        assert wheel.sample_spread_quality("Nifty 50") is None


class TestPaperFillsAreNotFree:
    """PROF-022: paper entry must not record 0.00 slippage by measuring mid against mid."""

    @patch("time.sleep", return_value=None)
    def test_paper_entry_records_the_half_spread(self, mock_sleep, wheel, mock_client):
        from strategies.wheel_strategy import WheelStateMachine

        mock_client.get_option_chain.return_value = _quoted_chain()
        wheel.execute_daily_cycle("Nifty 50", {"allocation_pct": 1.0, "entry_session": "friday"})

        state = wheel.state["Nifty 50"]
        assert state["current_stage"] == "STAGE_1_CSP"
        # Baseline stays the mid; the fill is booked at natural, so the gap survives.
        assert state["theoretical_credit"] == 20.0
        quantity = state["active_position"]["quantity"]
        assert state["net_credit_received"] == 19.0 * quantity
        assert WheelStateMachine._entry_slippage_per_leg(state, quantity) == 0.5
