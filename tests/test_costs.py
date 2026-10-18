"""Tests for the round-trip cost model (config/settings.round_trip_fees) and the
backtest/live parity of the strike-selection floor. See docs/PROFITABILITY_ROADMAP.md
Task D.
"""

from datetime import date, timedelta

from config.settings import exercise_stt, stt_sell_rate

import polars as pl
import pytest

from config.settings import round_trip_fees
from backtest import PCSParams, _round_strike, _select_strikes, run_pcs_backtest, synthetic_spot_path


class TestRoundTripFees:
    def test_known_value_per_leg(self):
        """Independent hand calculation, 2026 regime, 1 lot of 65, exact per-leg bases."""
        legs = (68.0, 52.0, 10.0, 5.0)  # short in, long in, short out, long out
        qty = 65
        sell, buy = (68.0 + 5.0) * qty, (52.0 + 10.0) * qty
        gross = sell + buy
        brokerage = 80.0
        txn = 0.0003503 * gross
        sebi = 1e-6 * gross
        expected = (brokerage + 0.0015 * sell + txn + 0.00003 * buy + sebi
                    + 5e-6 * gross + 0.18 * (brokerage + txn + sebi))
        got = round_trip_fees(16.0, 5.0, 65, 1, on=date(2026, 6, 1), legs=legs)
        assert got == pytest.approx(expected)

    @pytest.mark.parametrize("on,rate", [
        (date(2023, 3, 31), 0.0005), (date(2023, 4, 1), 0.000625),
        (date(2024, 9, 30), 0.000625), (date(2024, 10, 1), 0.001),
        (date(2026, 3, 31), 0.001), (date(2026, 4, 1), 0.0015),
    ])
    def test_stt_regime_boundaries(self, on, rate):
        assert stt_sell_rate(on) == rate

    def test_stt_regime_changes_fees(self):
        legs = (68.0, 52.0, 10.0, 5.0)
        old = round_trip_fees(16.0, 5.0, 65, 1, on=date(2026, 3, 31), legs=legs)
        new = round_trip_fees(16.0, 5.0, 65, 1, on=date(2026, 4, 1), legs=legs)
        assert new - old == pytest.approx(0.0005 * 73.0 * 65)

    def test_exercise_stt(self):
        assert exercise_stt(10_000, on=date(2026, 3, 31)) == pytest.approx(12.5)
        assert exercise_stt(10_000, on=date(2026, 4, 1)) == pytest.approx(15.0)
        # before 2019-09-01 the base is the whole settlement value, not intrinsic
        assert exercise_stt(10_000, on=date(2019, 8, 29), settlement_value=800_000) == pytest.approx(1000.0)
        assert exercise_stt(10_000, on=date(2019, 9, 5), settlement_value=800_000) == pytest.approx(12.5)
        with pytest.raises(ValueError):
            exercise_stt(10_000, on=date(2019, 8, 29))

    def test_option_sale_stt_2016_change(self):
        assert stt_sell_rate(date(2016, 5, 31)) == pytest.approx(0.00017)
        assert stt_sell_rate(date(2016, 6, 1)) == pytest.approx(0.0005)

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


def test_equity_delivery_fees_dated():
    from config.settings import equity_delivery_fees
    # 2015-01: STT 0.1% x2, txn 0.00345% x2, SEBI, stamp 0.01%, Rs40 brokerage + Rs20 DP, service tax 12.36%
    taxable = 40 + 20 + 2 * 100_000 * (0.0000345 + 0.000001)
    expect = 200 + 10 + taxable * 1.1236
    assert equity_delivery_fees(100_000, 100_000, date(2015, 1, 1), date(2015, 2, 1)) == pytest.approx(expect)
    # STT 0.125% before 2012-07-01, 0.1% from it; GST 18% from 2017-07-01
    assert (equity_delivery_fees(1e6, 0, date(2012, 6, 29), date(2012, 6, 29))
            - equity_delivery_fees(1e6, 0, date(2012, 7, 2), date(2012, 7, 2))) == pytest.approx(250)
    assert equity_delivery_fees(0, 0, date(2020, 1, 1), date(2020, 1, 1)) == 0


def test_futures_fees_dated():
    from config.settings import futures_fees
    # 2015-01-01 NSE order of Rs10L: Rs20 + txn + SEBI at 12.36% service tax; STT 0.01% sell, stamp 0.002% buy
    taxable = 20 + (0.0000188 + 0.000001) * 1e6
    assert futures_fees(1e6, date(2015, 1, 1), False, "NSE") == pytest.approx(taxable * 1.1236 + 100)
    assert futures_fees(-1e6, date(2015, 1, 1), True, "NSE") == pytest.approx(taxable * 1.1236 + 20)
    assert futures_fees(0, date(2015, 1, 1), True, "MCX") == 0.0
    # MCX CTT starts 2013-07-01; NSE futures STT 0.05% from 2026-04-01
    assert (futures_fees(1e6, date(2013, 7, 1), False, "MCX") - futures_fees(1e6, date(2013, 6, 28), False, "MCX")
            == pytest.approx(100))
    assert futures_fees(1e6, date(2026, 4, 1), False, "NSE") - futures_fees(1e6, date(2026, 3, 31), False, "NSE") \
        == pytest.approx(300)
