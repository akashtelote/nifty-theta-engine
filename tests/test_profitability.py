"""Tests for PROF-005..014 profitability stages."""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
import math

import polars as pl
import pytest
import pytz

from config.settings import Settings, vix_regime_otm
from backtest import PCSParams, run_pcs_backtest, synthetic_spot_path, sweep_exit_params


IST = pytz.timezone("Asia/Kolkata")


def _liquid_chain(spot: float = 22000.0, width: float = 100.0):
    """Synthetic PE chain around ~1% OTM with tight spreads and meaningful credit."""
    expiry = (date.today() + timedelta(days=21)).isoformat()
    short = round(spot * 0.99 / 50) * 50
    rows = []
    for k in range(int(short - 400), int(short + 150), 50):
        # Intrinsic-ish + OTM time value so credit/width clears MIN_CREDIT_WIDTH_RATIO
        intrinsic = max(spot - k, 0.0) * 0.0  # OTM puts: no intrinsic when k < spot
        otm = max(spot - k, 0.0)
        mid = max(10.0, 180.0 * math.exp(-otm / 500.0))
        bid = round(mid * 0.98, 2)
        ask = round(mid * 1.02, 2)
        rows.append({
            "instrument_key": f"NSE_FO|NIFTY{int(k)}PE",
            "type": "PE",
            "strike": float(k),
            "expiry": expiry,
            "bid": bid,
            "ask": ask,
            "last_price": mid,
        })
    return pl.DataFrame(rows), short, short - width


class TestVixRegimeMapping:
    def test_skip_above_max(self):
        action, otm = vix_regime_otm(30.0)
        assert action == "skip"

    def test_low_wider_otm(self):
        action, otm = vix_regime_otm(11.0)
        assert action == "enter"
        assert otm == pytest.approx(0.012)

    def test_normal_otm(self):
        action, otm = vix_regime_otm(15.0)
        assert action == "enter"
        assert otm == pytest.approx(0.010)

    def test_elevated_defensive_otm(self):
        action, otm = vix_regime_otm(20.0)
        assert action == "enter"
        assert otm == pytest.approx(0.015)

    def test_none_fail_open(self):
        action, otm = vix_regime_otm(None)
        assert action == "enter"
        assert otm == pytest.approx(0.010)


class TestExitParameterization:
    def _setup(self, wheel, initial_short=50.0, initial_long=30.0):
        expiry = (date.today() + timedelta(days=30)).isoformat()
        wheel.state["Nifty 50"] = {
            "current_stage": "STAGE_1_CSP",
            "active_position": {
                "instrument_key": "NSE_FO|NIFTY22000PE",
                "strike": 22000.0,
                "expiry": expiry,
                "entry_price": initial_short,
                "order_id": "ORD1",
                "quantity": 25,
            },
            "hedge_position": {
                "instrument_key": "NSE_FO|NIFTY21900PE",
                "strike": 21900.0,
                "expiry": expiry,
                "entry_price": initial_long,
                "order_id": "ORD2",
                "quantity": 25,
            },
            "net_credit_received": (initial_short - initial_long) * 25,
            "realized_pnl": 0.0,
        }
        return expiry

    def _chain(self, expiry, short_ask, long_bid):
        return pl.DataFrame([
            {"instrument_key": "NSE_FO|NIFTY22000PE", "type": "PE", "strike": 22000.0,
             "expiry": expiry, "bid": short_ask - 0.5, "ask": short_ask, "last_price": short_ask},
            {"instrument_key": "NSE_FO|NIFTY21900PE", "type": "PE", "strike": 21900.0,
             "expiry": expiry, "bid": long_bid, "ask": long_bid + 0.5, "last_price": long_bid},
        ])

    @patch("time.sleep", return_value=None)
    def test_take_profit_uses_settings(self, mock_sleep, wheel, mock_client, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "TP_RESIDUAL_CREDIT_FRACTION", 0.25)
        monkeypatch.setattr(settings_mod.settings, "SL_CREDIT_MULTIPLE", 2.0)
        expiry = self._setup(wheel)  # credit = 20
        # cost 4.0 <= 0.25 * 20 = 5.0 → TP
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = self._chain(expiry, 5.0, 1.0)
        mock_client.get_order_status.return_value = "complete"
        mock_client.place_order_by_key.return_value = "PAPER_x"
        wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "CLOSED"

    @patch("time.sleep", return_value=None)
    def test_stop_loss_credit_multiple(self, mock_sleep, wheel, mock_client, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "TP_RESIDUAL_CREDIT_FRACTION", 0.25)
        monkeypatch.setattr(settings_mod.settings, "SL_CREDIT_MULTIPLE", 2.0)
        expiry = self._setup(wheel)  # credit = 20
        # cost 45 >= 40 → SL
        mock_client.get_market_quote_ltp.return_value = 22500.0
        mock_client.get_option_chain.return_value = self._chain(expiry, 50.0, 5.0)
        mock_client.get_order_status.return_value = "complete"
        mock_client.place_order_by_key.return_value = "PAPER_x"
        wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "CLOSED"

    @patch("time.sleep", return_value=None)
    def test_stop_loss_spot_breach(self, mock_sleep, wheel, mock_client, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "TP_RESIDUAL_CREDIT_FRACTION", 0.05)
        monkeypatch.setattr(settings_mod.settings, "SL_CREDIT_MULTIPLE", 10.0)
        expiry = self._setup(wheel)
        mock_client.get_market_quote_ltp.return_value = 21900.0  # <= short strike
        mock_client.get_option_chain.return_value = self._chain(expiry, 25.0, 10.0)
        mock_client.get_order_status.return_value = "complete"
        mock_client.place_order_by_key.return_value = "PAPER_x"
        wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "CLOSED"

    @patch("time.sleep", return_value=None)
    def test_spot_breach_ignored_when_touch_stop_disabled(self, mock_sleep, wheel, mock_client, monkeypatch):
        """STOP_ON_STRIKE_TOUCH=False must not exit on a touch, but the credit multiple still stops."""
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "TP_RESIDUAL_CREDIT_FRACTION", 0.05)
        monkeypatch.setattr(settings_mod.settings, "SL_CREDIT_MULTIPLE", 10.0)
        monkeypatch.setattr(settings_mod.settings, "STOP_ON_STRIKE_TOUCH", False)
        monkeypatch.setattr(settings_mod.settings, "DTE_MANAGE_THRESHOLD", -1)
        monkeypatch.setattr(settings_mod.settings, "SHORT_DELTA_MANAGE", 0.99)
        expiry = self._setup(wheel)  # credit = 20
        mock_client.get_market_quote_ltp.return_value = 21900.0  # <= short strike
        mock_client.get_option_chain.return_value = self._chain(expiry, 25.0, 10.0)  # cost 15 < 200
        mock_client.get_order_status.return_value = "complete"
        mock_client.place_order_by_key.return_value = "PAPER_x"
        wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "STAGE_1_CSP"

        # Credit-multiple stop is untouched by the flag: cost 205 >= 10 * 20
        mock_client.get_option_chain.return_value = self._chain(expiry, 210.0, 5.0)
        wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "CLOSED"

    @patch("time.sleep", return_value=None)
    def test_time_stop_weekday_hour(self, mock_sleep, wheel, mock_client, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "TP_RESIDUAL_CREDIT_FRACTION", 0.01)
        monkeypatch.setattr(settings_mod.settings, "SL_CREDIT_MULTIPLE", 10.0)
        monkeypatch.setattr(settings_mod.settings, "TIME_STOP_WEEKDAY", 3)
        monkeypatch.setattr(settings_mod.settings, "TIME_STOP_HOUR", 15)
        expiry = self._setup(wheel)
        # cost not TP/SL: 15 with credit 20
        mock_client.get_market_quote_ltp.return_value = 23000.0
        mock_client.get_option_chain.return_value = self._chain(expiry, 20.0, 5.0)
        mock_client.get_order_status.return_value = "complete"
        mock_client.place_order_by_key.return_value = "PAPER_x"

        thu_1500 = IST.localize(datetime(2026, 7, 30, 15, 5))  # Thursday
        with patch("strategies.wheel_strategy.datetime") as mock_dt:
            mock_dt.now.return_value = thu_1500
            mock_dt.strptime = datetime.strptime
            wheel.check_exits()
        assert wheel.state["Nifty 50"]["current_stage"] == "CLOSED"


class TestStrikeSelection:
    def test_selects_liquid_delta_credit_pair(self, wheel):
        chain, _, _ = _liquid_chain()
        short, long = wheel._select_target_put(chain, 22000.0, otm_pct=0.01, vix=15.0, lot_size=25)
        assert short is not None and long is not None
        assert short["strike"] > long["strike"]
        assert (short["strike"] - long["strike"]) * 25 <= 50000

    def test_rejects_wide_bid_ask(self, wheel):
        expiry = (date.today() + timedelta(days=21)).isoformat()
        chain = pl.DataFrame([
            {"instrument_key": "A", "type": "PE", "strike": 21700.0, "expiry": expiry,
             "bid": 50.0, "ask": 80.0, "last_price": 65.0},
            {"instrument_key": "B", "type": "PE", "strike": 21600.0, "expiry": expiry,
             "bid": 30.0, "ask": 31.0, "last_price": 30.5},
        ])
        short, long = wheel._select_target_put(chain, 22000.0, otm_pct=0.01, vix=15.0, lot_size=25)
        assert short is None and long is None

    def test_hedge_width_over_capital_aborts(self, wheel, monkeypatch, caplog):
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "HEDGE_WIDTH", 3000.0)  # 3000*25=75k > 50k
        chain, _, _ = _liquid_chain()
        import logging
        with caplog.at_level(logging.ERROR):
            short, long = wheel._select_target_put(chain, 22000.0, otm_pct=0.01, vix=15.0, lot_size=25)
        assert short is None and long is None
        assert any("MAX_CAPITAL" in r.message for r in caplog.records)

    def test_configurable_hedge_width(self, wheel, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "HEDGE_WIDTH", 50.0)
        monkeypatch.setattr(settings_mod.settings, "MIN_CREDIT_WIDTH_RATIO", 0.05)
        chain, _, _ = _liquid_chain(width=50.0)
        short, long = wheel._select_target_put(chain, 22000.0, otm_pct=0.01, vix=15.0, lot_size=25)
        assert short is not None and long is not None
        assert short["strike"] - long["strike"] == pytest.approx(50.0)


class TestMidweekEntry:
    def test_midweek_session_requires_vix_band(self, wheel, mock_client, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "ALLOW_MIDWEEK_ENTRY", True)
        monkeypatch.setattr(settings_mod.settings, "MIDWEEK_VIX_MIN", 16.0)
        monkeypatch.setattr(settings_mod.settings, "MIDWEEK_VIX_MAX", 22.0)
        mock_client.get_india_vix.return_value = 14.0  # below band
        wheel.execute_daily_cycle("Nifty 50", 25, {"allocation_pct": 1.0, "entry_session": "midweek"})
        mock_client.get_market_quote_ltp.assert_not_called()

    def test_midweek_blocked_when_flag_off(self, wheel, mock_client, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "ALLOW_MIDWEEK_ENTRY", False)
        mock_client.get_india_vix.return_value = 18.0
        wheel.execute_daily_cycle("Nifty 50", 25, {"allocation_pct": 1.0, "entry_session": "midweek"})
        mock_client.get_market_quote_ltp.assert_not_called()

    def test_friday_session_ignores_midweek_band(self, wheel, mock_client, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "ALLOW_MIDWEEK_ENTRY", False)
        mock_client.get_india_vix.return_value = 14.0
        mock_client.get_option_chain.return_value = pl.DataFrame(schema={
            "instrument_key": pl.Utf8, "type": pl.Utf8, "strike": pl.Float64,
            "expiry": pl.Utf8, "bid": pl.Float64, "ask": pl.Float64, "last_price": pl.Float64,
        })
        wheel.execute_daily_cycle("Nifty 50", 25, {"allocation_pct": 1.0, "entry_session": "friday"})
        mock_client.get_market_quote_ltp.assert_called_once()


class TestPcsBacktest:
    def test_runs_under_50k_and_reports_metrics(self):
        df = synthetic_spot_path(n_days=260, seed=1)
        res = run_pcs_backtest(
            df, PCSParams(skip_low_ivr=False, trend_filter=False, event_blackout=False)
        )
        assert res.total_trades > 0
        assert 0.0 <= res.win_rate <= 100.0
        assert "max_drawdown" in res.as_dict()
        assert res.exit_reason_mix
        assert res.final_equity <= 50000 + abs(res.total_pnl) + 1

    def test_rejects_over_budget_width(self):
        with pytest.raises(ValueError):
            run_pcs_backtest(synthetic_spot_path(n_days=50), PCSParams(hedge_width=5000.0))

    def test_sweep_returns_ranked_grid(self):
        grid = sweep_exit_params(synthetic_spot_path(n_days=120, seed=7))
        assert len(grid) >= 4
        assert grid[0]["total_pnl"] >= grid[-1]["total_pnl"]


class TestSettingsProfitDefaults:
    def test_exit_defaults_present(self):
        s = Settings(
            _env_file=None,
            DATABASE_URL="postgresql://x:y@localhost/z",
            TP_RESIDUAL_CREDIT_FRACTION=0.50,
            TIME_STOP_WEEKDAY=-1,
            DTE_MANAGE_THRESHOLD=7,
            SHORT_DELTA_MANAGE=0.30,
            ALLOW_MIDWEEK_ENTRY=True,
        )
        assert s.TP_RESIDUAL_CREDIT_FRACTION == 0.50
        assert s.SL_CREDIT_MULTIPLE == 2.0
        assert s.TIME_STOP_WEEKDAY == -1
        assert s.DTE_MANAGE_THRESHOLD == 7
        assert s.SHORT_DELTA_MANAGE == 0.30
        assert s.TIME_STOP_HOUR == 15
        assert s.HEDGE_WIDTH == 100.0
        assert s.ALLOW_MIDWEEK_ENTRY is True
        assert s.MAX_CAPITAL == 50000.0
        assert s.HEDGE_WIDTH * 25 <= s.MAX_CAPITAL
