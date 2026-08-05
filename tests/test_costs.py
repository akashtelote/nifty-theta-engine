"""Tests for the round-trip cost model (config/settings.round_trip_fees) and the
backtest/live parity of the strike-selection floor. See docs/PROFITABILITY_ROADMAP.md
Task D.
"""

from datetime import date, timedelta

import polars as pl
import pytest

from config.settings import round_trip_fees
from backtest import PCSParams, _round_strike, _select_strikes, run_pcs_backtest, synthetic_spot_path


class TestRoundTripFees:
    def test_known_value(self):
        # Pinned regression value; exact float is 116.34232085000001, hence approx.
        assert round_trip_fees(20.7, 10.35, 25, 20) == pytest.approx(116.34232085)

    def test_brokerage_is_flat_not_per_lot(self):
        """Brokerage is a flat 4-order fee, so per-lot cost must collapse as size grows.

        This is the property that makes 1-lot backtests cost-blind versus the
        20-lot bot: ~95/lot at 1 lot should fall to well under 10/lot at 20 lots.
        """
        per_lot_1 = round_trip_fees(20.7, 10.35, 25, 1) / 1
        per_lot_20 = round_trip_fees(20.7, 10.35, 25, 20) / 20
        assert per_lot_1 > 90
        assert per_lot_20 < 10
        assert per_lot_20 < per_lot_1

    def test_never_negative(self):
        assert round_trip_fees(20.7, 10.35, 25, 20) >= 0
        assert round_trip_fees(0.0, 0.0, 0, 0) >= 0
        assert round_trip_fees(-20.7, -10.35, -25, -20) >= 0


class TestStrikeBandParity:
    """The backtest's strike search must scan the same OTM band as the live bot's
    _select_target_put, or tuning the backtest optimizes a different strategy than
    the one actually traded.
    """

    def test_backtest_floor_matches_live_floor(self):
        spot = 25000.0
        otm_pct = 0.010
        otm_floor_extra = 0.02

        # Shared arithmetic (mirrors both wheel_strategy._select_target_put L471 and
        # backtest._select_strikes L231): floor = spot * (1 - max(otm*2.5, otm+extra)).
        expected_floor = spot * (1.0 - max(otm_pct * 2.5, otm_pct + otm_floor_extra))
        assert expected_floor == pytest.approx(24250.0)

        # --- Backtest side: force the search toward the most-OTM (lowest-delta)
        # strike via target_delta=0.0, so the winner is whatever the grid's lower
        # bound resolves to. If backtest's floor formula drifts, this strike moves.
        params = PCSParams(
            target_delta=0.0, otm_pct=otm_pct, otm_floor_extra=otm_floor_extra,
            skip_low_ivr=False, trend_filter=False, event_blackout=False,
        )
        result = _select_strikes(
            spot, vix=15.0, params=params,
            vix_history=[15.0] * 260, spot_history=[spot] * 260, on=date(2024, 1, 5),
        )
        assert result is not None
        backtest_short_k = result[0]
        assert backtest_short_k == pytest.approx(_round_strike(expected_floor))

        # --- Live side: _select_target_put hardcodes its "+0.02" floor extra inline
        # rather than exposing it as a named constant, so it can't be introspected
        # without duplicating the formula. Instead, exercise the real filter: give
        # it a strike just below the floor (24150) with dramatically better credit
        # economics than an in-band strike (24300), and confirm the in-band one is
        # still chosen -- proving the below-floor candidate was excluded, not
        # merely outscored.
        from strategies.wheel_strategy import WheelStateMachine

        wheel = WheelStateMachine.__new__(WheelStateMachine)
        expiry = (date.today() + timedelta(days=21)).isoformat()
        chain = pl.DataFrame([
            {"instrument_key": "BELOW_FLOOR_SHORT", "type": "PE", "strike": 24150.0,
             "expiry": expiry, "bid": 5000.0, "ask": 5010.0, "last_price": 5005.0},
            {"instrument_key": "BELOW_FLOOR_HEDGE", "type": "PE", "strike": 24050.0,
             "expiry": expiry, "bid": 0.9, "ask": 1.0, "last_price": 0.95},
            {"instrument_key": "IN_BAND_SHORT", "type": "PE", "strike": 24300.0,
             "expiry": expiry, "bid": 20.0, "ask": 20.6, "last_price": 20.3},
            {"instrument_key": "IN_BAND_HEDGE", "type": "PE", "strike": 24200.0,
             "expiry": expiry, "bid": 4.0, "ask": 4.2, "last_price": 4.1},
        ])
        short, long = wheel._select_target_put(chain, spot, otm_pct=otm_pct, vix=15.0, lot_size=25)
        assert short is not None
        assert short["strike"] == pytest.approx(24300.0)
        assert long["strike"] == pytest.approx(24200.0)


class TestCostsReducePnl:
    def test_slippage_lowers_total_pnl(self):
        df = synthetic_spot_path(n_days=120, seed=3)
        common = dict(skip_low_ivr=False, trend_filter=False, event_blackout=False)
        frictionless = run_pcs_backtest(df, PCSParams(slippage_points=0.0, **common))
        costed = run_pcs_backtest(df, PCSParams(slippage_points=1.5, **common))
        assert frictionless.total_trades > 0
        assert costed.total_pnl < frictionless.total_pnl
