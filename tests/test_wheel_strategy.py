import polars as pl
from datetime import date, timedelta
from unittest.mock import patch

from config.settings import round_trip_fees


class TestEnsureSymbolState:
    def test_initializes_new_symbol(self, wheel):
        wheel.ensure_symbol_state("Nifty 50")
        assert wheel.state["Nifty 50"]["current_stage"] == "IDLE"
        assert wheel.state["Nifty 50"]["active_position"] is None
        assert wheel.state["Nifty 50"]["hedge_position"] is None

    def test_does_not_overwrite_existing(self, wheel):
        wheel.state["Nifty 50"] = {"current_stage": "STAGE_1_CSP", "active_position": {"strike": 22000}}
        wheel.ensure_symbol_state("Nifty 50")
        assert wheel.state["Nifty 50"]["current_stage"] == "STAGE_1_CSP"


class TestVixCircuitBreaker:
    def test_blocks_entry_when_vix_high(self, wheel, mock_client):
        mock_client.get_india_vix.return_value = 30.0
        wheel.execute_daily_cycle("Nifty 50", {"allocation_pct": 1.0, "entry_session": "friday"})
        mock_client.get_market_quote_ltp.assert_not_called()

    def test_allows_entry_when_vix_safe(self, wheel, mock_client):
        mock_client.get_india_vix.return_value = 14.0
        mock_client.get_option_chain.return_value = pl.DataFrame(schema={
            "instrument_key": pl.Utf8, "type": pl.Utf8, "strike": pl.Float64,
            "expiry": pl.Utf8, "bid": pl.Float64, "ask": pl.Float64, "last_price": pl.Float64
        })
        wheel.execute_daily_cycle("Nifty 50", {"allocation_pct": 1.0, "entry_session": "friday"})
        mock_client.get_market_quote_ltp.assert_called_once()

    def test_allows_entry_when_vix_none(self, wheel, mock_client):
        mock_client.get_india_vix.return_value = None
        mock_client.get_option_chain.return_value = pl.DataFrame(schema={
            "instrument_key": pl.Utf8, "type": pl.Utf8, "strike": pl.Float64,
            "expiry": pl.Utf8, "bid": pl.Float64, "ask": pl.Float64, "last_price": pl.Float64
        })
        wheel.execute_daily_cycle("Nifty 50", {"allocation_pct": 1.0, "entry_session": "friday"})
        mock_client.get_market_quote_ltp.assert_called_once()


class TestPositionSizing:
    @patch("time.sleep", return_value=None)
    def test_uses_margin_api(self, mock_sleep, wheel, mock_client):
        """Verify budget is derived from margin, not hardcoded."""
        mock_client.get_available_margin.return_value = 100000.0
        mock_client.get_india_vix.return_value = 14.0
        mock_client.get_market_quote_ltp.return_value = 22000.0

        # _select_target_put: target_strike = 22000 * 0.99 = 21780
        # Short put needs strike <= 21780, hedge needs strike <= (short_strike - 100)
        expiry = (date.today() + timedelta(days=20)).isoformat()
        chain = pl.DataFrame([
            {"instrument_key": "NSE_FO|NIFTY21700PE", "type": "PE", "strike": 21700.0,
             "expiry": expiry, "bid": 50.0, "ask": 51.0, "last_price": 50.5},
            {"instrument_key": "NSE_FO|NIFTY21600PE", "type": "PE", "strike": 21600.0,
             "expiry": expiry, "bid": 30.0, "ask": 31.0, "last_price": 30.5},
        ])
        mock_client.get_option_chain.return_value = chain
        wheel.execute_daily_cycle("Nifty 50", {"allocation_pct": 0.5, "entry_session": "friday"})
        mock_client.get_available_margin.assert_called_once()

    def test_aborts_on_margin_failure(self, wheel, mock_client):
        mock_client.get_india_vix.return_value = 14.0
        mock_client.get_market_quote_ltp.return_value = 22000.0
        mock_client.get_available_margin.return_value = None

        expiry = (date.today() + timedelta(days=20)).isoformat()
        chain = pl.DataFrame([
            {"instrument_key": "NSE_FO|NIFTY21700PE", "type": "PE", "strike": 21700.0,
             "expiry": expiry, "bid": 50.0, "ask": 51.0, "last_price": 50.5},
            {"instrument_key": "NSE_FO|NIFTY21600PE", "type": "PE", "strike": 21600.0,
             "expiry": expiry, "bid": 30.0, "ask": 31.0, "last_price": 30.5},
        ])
        mock_client.get_option_chain.return_value = chain
        wheel.execute_daily_cycle("Nifty 50", {"allocation_pct": 1.0, "entry_session": "friday"})
        mock_client.place_order_by_key.assert_not_called()


class TestExitVerification:
    def _setup_active_position(self, wheel):
        expiry = (date.today() + timedelta(days=30)).isoformat()
        wheel.state["Nifty 50"] = {
            "current_stage": "STAGE_1_CSP",
            "active_position": {
                "instrument_key": "NSE_FO|NIFTY22000PE",
                "strike": 22000.0,
                "expiry": expiry,
                "entry_price": 50.0,
                "order_id": "ORD1",
                "quantity": 25,
            },
            "hedge_position": {
                "instrument_key": "NSE_FO|NIFTY21900PE",
                "strike": 21900.0,
                "expiry": expiry,
                "entry_price": 30.0,
                "order_id": "ORD2",
                "quantity": 25,
            },
            "net_credit_received": 500.0,
            "realized_pnl": 0.0,
        }

    @patch("time.sleep", return_value=None)
    def test_closes_on_take_profit(self, mock_sleep, wheel, mock_client):
        self._setup_active_position(wheel)
        mock_client.get_market_quote_ltp.return_value = 23000.0
        expiry = wheel.state["Nifty 50"]["active_position"]["expiry"]

        # Build an option chain DataFrame that contains both instrument keys
        chain = pl.DataFrame([
            {"instrument_key": "NSE_FO|NIFTY22000PE", "type": "PE", "strike": 22000.0,
             "expiry": expiry, "bid": 1.5, "ask": 2.0, "last_price": 1.75},
            {"instrument_key": "NSE_FO|NIFTY21900PE", "type": "PE", "strike": 21900.0,
             "expiry": expiry, "bid": 1.0, "ask": 1.5, "last_price": 1.25},
        ])
        mock_client.get_option_chain.return_value = chain
        mock_client.get_order_status.return_value = "complete"
        mock_client.place_order_by_key.return_value = "PAPER_exit1234"

        wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "CLOSED"

    @patch("time.sleep", return_value=None)
    def test_does_not_close_on_partial_fill(self, mock_sleep, wheel, mock_client):
        self._setup_active_position(wheel)
        mock_client.get_market_quote_ltp.return_value = 23000.0
        expiry = wheel.state["Nifty 50"]["active_position"]["expiry"]

        chain = pl.DataFrame([
            {"instrument_key": "NSE_FO|NIFTY22000PE", "type": "PE", "strike": 22000.0,
             "expiry": expiry, "bid": 1.5, "ask": 2.0, "last_price": 1.75},
            {"instrument_key": "NSE_FO|NIFTY21900PE", "type": "PE", "strike": 21900.0,
             "expiry": expiry, "bid": 1.0, "ask": 1.5, "last_price": 1.25},
        ])
        mock_client.get_option_chain.return_value = chain
        mock_client.get_order_status.return_value = "pending"
        mock_client.place_order_by_key.return_value = "PAPER_exit1234"

        wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "STAGE_1_CSP"


class TestHedgeUnwinding:
    @patch("time.sleep", return_value=None)
    def test_unwind_on_short_order_failure(self, mock_sleep, wheel, mock_client):
        """When Leg 2 placement fails, Leg 1 should be unwound."""
        mock_client.get_india_vix.return_value = 14.0
        mock_client.get_market_quote_ltp.return_value = 22000.0
        mock_client.get_available_margin.return_value = 100000.0

        expiry = (date.today() + timedelta(days=20)).isoformat()
        chain = pl.DataFrame([
            {"instrument_key": "NSE_FO|NIFTY21700PE", "type": "PE", "strike": 21700.0,
             "expiry": expiry, "bid": 50.0, "ask": 51.0, "last_price": 50.5},
            {"instrument_key": "NSE_FO|NIFTY21600PE", "type": "PE", "strike": 21600.0,
             "expiry": expiry, "bid": 30.0, "ask": 31.0, "last_price": 30.5},
        ])
        mock_client.get_option_chain.return_value = chain
        # Leg 1 (hedge) succeeds, then order status checks return "complete",
        # then Leg 2 (short) fails with None
        mock_client.place_order_by_key.side_effect = ["PAPER_hedge1", None, "PAPER_unwind1"]
        mock_client.get_order_status.return_value = "complete"

        wheel.execute_daily_cycle("Nifty 50", {"allocation_pct": 1.0})
        # State should remain IDLE (not transitioned to STAGE_1_CSP)
        assert wheel.state["Nifty 50"]["current_stage"] == "IDLE"


class TestExpiryAutoClose:
    def test_closes_expired_position(self, wheel, mock_client, mock_notifier):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        wheel.state["Nifty 50"] = {
            "current_stage": "STAGE_1_CSP",
            "active_position": {
                "instrument_key": "NSE_FO|NIFTY22000PE",
                "strike": 22000.0,
                "expiry": yesterday,
                "entry_price": 50.0,
                "order_id": "ORD1",
                "quantity": 25,
            },
            "hedge_position": {
                "instrument_key": "NSE_FO|NIFTY21900PE",
                "strike": 21900.0,
                "expiry": yesterday,
                "entry_price": 30.0,
                "order_id": "ORD2",
                "quantity": 25,
            },
            "net_credit_received": 500.0,
            "realized_pnl": 0.0,
        }
        wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "CLOSED"
        assert wheel.state["Nifty 50"]["active_position"] is None
        # Max profit is booked net of round-trip fees (gross 20.0 * 25 = 500.0)
        expected_pnl = 500.0 - round_trip_fees(20.0, 0.0, 25, 1)
        assert abs(wheel.state["Nifty 50"]["realized_pnl"] - expected_pnl) < 0.01
        mock_client.get_market_quote_ltp.assert_not_called()
        mock_notifier.send_notification.assert_called()

    def test_does_not_close_unexpired_position(self, wheel, mock_client):
        future = (date.today() + timedelta(days=7)).isoformat()
        wheel.state["Nifty 50"] = {
            "current_stage": "STAGE_1_CSP",
            "active_position": {
                "instrument_key": "NSE_FO|NIFTY22000PE",
                "strike": 22000.0,
                "expiry": future,
                "entry_price": 50.0,
                "order_id": "ORD1",
                "quantity": 25,
            },
            "hedge_position": {
                "instrument_key": "NSE_FO|NIFTY21900PE",
                "strike": 21900.0,
                "expiry": future,
                "entry_price": 30.0,
                "order_id": "ORD2",
                "quantity": 25,
            },
            "net_credit_received": 500.0,
            "realized_pnl": 0.0,
        }
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = pl.DataFrame(schema={
            "instrument_key": pl.Utf8, "type": pl.Utf8, "strike": pl.Float64,
            "expiry": pl.Utf8, "bid": pl.Float64, "ask": pl.Float64, "last_price": pl.Float64
        })
        wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "STAGE_1_CSP"


class TestReconciliation:
    def test_skips_in_paper_trade_mode(self, wheel, mock_client, mock_notifier):
        mock_client.is_paper_trade = True
        wheel.state["Nifty 50"] = {
            "current_stage": "STAGE_1_CSP",
            "active_position": {"instrument_key": "NSE_FO|NIFTY22000PE"},
            "hedge_position": {"instrument_key": "NSE_FO|NIFTY21900PE"},
        }
        wheel.reconcile_positions()
        mock_client.get_positions.assert_not_called()
        mock_notifier.send_notification.assert_not_called()

    def test_detects_missing_broker_position(self, wheel, mock_client, mock_notifier):
        mock_client.is_paper_trade = False
        wheel.state["Nifty 50"] = {
            "current_stage": "STAGE_1_CSP",
            "active_position": {"instrument_key": "NSE_FO|NIFTY22000PE"},
            "hedge_position": {"instrument_key": "NSE_FO|NIFTY21900PE"},
        }
        mock_client.get_positions.return_value = []
        wheel.reconcile_positions()
        mock_notifier.send_notification.assert_called()

    def test_detects_orphan_broker_position(self, wheel, mock_client, mock_notifier):
        mock_client.is_paper_trade = False
        wheel.state = {}
        mock_client.get_positions.return_value = [
            {"instrument_token": "NSE_FO|ORPHAN", "quantity": 25, "average_price": 50.0, "product": "D"}
        ]
        wheel.reconcile_positions()
        mock_notifier.send_notification.assert_called()

    def test_no_alert_when_matched(self, wheel, mock_client, mock_notifier):
        mock_client.is_paper_trade = False
        wheel.state["Nifty 50"] = {
            "current_stage": "STAGE_1_CSP",
            "active_position": {"instrument_key": "NSE_FO|NIFTY22000PE"},
            "hedge_position": {"instrument_key": "NSE_FO|NIFTY21900PE"},
        }
        mock_client.get_positions.return_value = [
            {"instrument_token": "NSE_FO|NIFTY22000PE", "quantity": -25, "average_price": 50.0, "product": "D"},
            {"instrument_token": "NSE_FO|NIFTY21900PE", "quantity": 25, "average_price": 30.0, "product": "D"},
        ]
        wheel.reconcile_positions()
        mock_notifier.send_notification.assert_not_called()
