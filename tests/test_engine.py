"""Phase 3 engine + metrics tests on SYNTHETIC chains only (never real result data)."""
from dataclasses import replace
from datetime import date, timedelta

import polars as pl
import pytest

from config.settings import exercise_stt, round_trip_fees
from research import engine, metrics
from research.engine import Chain, Config, _ncdf, _put, put_delta

VOL, LOT = 0.15, 75


def _call(f, k, t, v):
    return _put(f, k, t, v) + f - k  # parity, r = 0


def make_chain(spot_fn, start=date(2023, 1, 2), end=date(2023, 3, 31)) -> Chain:
    rows, d = [], start
    while d <= end:
        if d.weekday() < 5:
            f = spot_fn(d)
            exps = [d + timedelta(days=x) for x in range(0, 21) if (d + timedelta(days=x)).weekday() == 3]
            for e in exps:
                t = (e - d).days / 365.0
                for k in range(19000, 25001, 50):
                    for typ in ("CE", "PE"):
                        if t == 0:
                            px = max(f - k, 0) if typ == "CE" else max(k - f, 0)
                        else:
                            px = _call(f, k, t, VOL) if typ == "CE" else _put(f, k, t, VOL)
                        rows.append((d, e, float(k), typ, max(px, 0.05), 1000, 5000, LOT))
        d += timedelta(days=1)
    df = pl.DataFrame(rows, schema=["date", "expiry", "strike", "opt_type", "settle", "contracts", "oi", "lot_size"],
                      orient="row")
    return Chain(df)


FLAT = lambda d: 22000.0  # noqa: E731
CFG = Config(sma_gate=False, exit_mode="hold", tp_residual=0.0, slip=0.5)
FIRST = (date(2023, 1, 2), date(2023, 1, 6))  # one entry (Fri 2023-01-06), expiry Thu 2023-01-12


def test_put_delta_roundtrip():
    f, k, t = 22000.0, 21600.0, 6 / 365
    d1 = (engine.math.log(f / k) + 0.5 * VOL**2 * t) / (VOL * t**0.5)
    assert put_delta(f, k, t, _put(f, k, t, VOL)) == pytest.approx(_ncdf(-d1), abs=1e-6)
    assert put_delta(f, k, t, 0.0) is None


def test_entry_selection_sizing_and_flat_expiry():
    ch = make_chain(FLAT)
    (tr,) = engine.run(ch, CFG, *FIRST)
    assert (tr.entry, tr.expiry) == (date(2023, 1, 6), date(2023, 1, 12))
    assert tr.long_k == tr.short_k - 100 and tr.short_k % 50 == 0 and tr.short_k < 22000
    f = engine.forward(ch.days[tr.entry], tr.expiry)
    dl = put_delta(f, tr.short_k, 6 / 365, engine._px(ch.days[tr.entry], tr.expiry, tr.short_k))
    assert abs(dl - 0.20) < 0.04
    ml = (100 - tr.credit) * LOT
    assert tr.lots == int(2_000_000 * 0.02 // ml) and tr.max_loss == pytest.approx(ml * tr.lots)
    # natural credit pays slippage on both legs: mid credit minus 2*slip
    s = engine._px(ch.days[tr.entry], tr.expiry, tr.short_k)
    l = engine._px(ch.days[tr.entry], tr.expiry, tr.long_k)
    assert tr.credit == pytest.approx((s - 0.5) - (l + 0.5))
    # flat market: both legs expire worthless, no exit orders, no exercise STT
    assert tr.reason == "expiry" and tr.exit == tr.expiry and tr.exit_cost == pytest.approx(0.05 - 0.05, abs=1e-9)
    full = round_trip_fees(tr.credit, 0, LOT, tr.lots, on=tr.entry, legs=(s - 0.5, l + 0.5, 0, 0))
    assert tr.fees == pytest.approx(full - 2 * 20 * 1.18)
    assert tr.pnl == pytest.approx(tr.credit * LOT * tr.lots - tr.fees)


def crash(d):
    return 22000.0 if d <= date(2023, 1, 6) else 21000.0


def test_stop2x_decides_on_settle_executes_next_day():
    ch = make_chain(crash)
    (tr,) = engine.run(ch, replace(CFG, exit_mode="stop2x"), *FIRST)
    assert tr.reason == "stop"
    assert tr.exit == date(2023, 1, 10)  # trigger seen Mon 01-09 settle, executed Tue 01-10
    assert tr.pnl < 0 and tr.worst_pnl < 0


def test_hold_to_expiry_pays_exercise_stt_on_itm_long_put():
    ch = make_chain(crash)
    (tr,) = engine.run(ch, CFG, *FIRST)
    assert tr.reason == "expiry"
    assert tr.exit_cost == pytest.approx(100.0)  # both puts deep ITM: short - long = width
    s = engine._px(ch.days[tr.entry], tr.expiry, tr.short_k)
    l = engine._px(ch.days[tr.entry], tr.expiry, tr.long_k)
    base = round_trip_fees(tr.credit, 0, LOT, tr.lots, on=tr.entry, legs=(s - 0.5, l + 0.5, 0, 0)) - 2 * 20 * 1.18
    assert tr.fees == pytest.approx(base + exercise_stt((tr.long_k - 21000) * LOT * tr.lots, on=tr.expiry, settlement_value=21000 * LOT * tr.lots))
    assert tr.pnl == pytest.approx((tr.credit - 100.0) * LOT * tr.lots - tr.fees)


def test_sma_gate_blocks_downtrend_allows_uptrend_and_needs_history():
    down = make_chain(lambda d: 24000.0 - (d - date(2023, 1, 2)).days * 20)
    up = make_chain(lambda d: 21000.0 + (d - date(2023, 1, 2)).days * 20)
    cfg = replace(CFG, sma_gate=True)
    assert engine.run(down, cfg, date(2023, 1, 2), date(2023, 3, 31)) == []
    ups = engine.run(up, cfg, date(2023, 1, 2), date(2023, 3, 31))
    assert ups and min(t.entry for t in ups) >= up.dates[49]  # no entries before 50 days of history


def test_one_position_at_a_time_and_open_trade_at_data_end_is_dropped():
    ch = make_chain(FLAT)
    dropped: list = []
    ts = engine.run(ch, CFG, date(2023, 1, 2), date(2023, 3, 31), dropped)
    assert all(a.exit < b.entry for a, b in zip(ts, ts[1:]))
    # the 03-31 Friday entry has no expiry in the data -> attempted, dropped, counted
    assert dropped == [date(2023, 3, 31)] and ts[-1].entry < date(2023, 3, 31)


def test_min_credit_gate_skips():
    ch = make_chain(FLAT)
    assert engine.run(ch, replace(CFG, min_cw=0.9), *FIRST) == []


def test_metrics():
    assert metrics.profit_factor([100, -50, 50]) == 3.0
    assert metrics.profit_factor([-1.0]) == 0.0

    class T:  # minimal trade stub
        def __init__(s, pnl, worst, exit, ml=1000.0):
            s.pnl, s.worst_pnl, s.exit, s.fees, s.max_loss = pnl, worst, exit, 0.0, ml

    ts = [T(100, -20, date(2023, 4, 7)), T(-300, -400, date(2023, 4, 14)), T(50, 0, date(2024, 4, 5))]
    assert metrics.max_drawdown(ts, 1000.0) == pytest.approx((1100 - (1100 - 400)) / 1100)
    # FY2023 (Apr-23..Mar-24): -200 untaxed; FY2024: +50 taxed 30%
    assert metrics.after_tax_pnl(ts) == pytest.approx(-200 + 50 * 0.7)
    lo, hi = metrics.bootstrap_ci([1.0, 2.0, 3.0, 4.0], lambda x: sum(x) / len(x))
    assert 1.0 <= lo <= hi <= 4.0
    assert metrics.bootstrap_ci([1, 2, 3, 4], sum) == metrics.bootstrap_ci([1, 2, 3, 4], sum)  # seeded
    s = metrics.summarize(ts, 10_000.0, date(2023, 4, 1), date(2024, 4, 6))
    assert s["n"] == 3 and s["worst_trade"] == -300 and s["total_pnl"] == -150


def test_default_tp_executes_next_day_with_slippage():
    # tp_residual 0.25 default; a flat market decays the spread, TP fires before expiry
    ch = make_chain(FLAT)
    (tr,) = engine.run(ch, replace(CFG, exit_mode="stop2x", tp_residual=0.25), *FIRST)
    assert tr.reason == "tp" and tr.marks >= 1  # decided on an earlier settle, executed later (maybe expiry day)
    sp = engine._px(ch.days[tr.exit], tr.expiry, tr.short_k)
    lp = engine._px(ch.days[tr.exit], tr.expiry, tr.long_k)
    assert tr.exit_cost == pytest.approx((sp + 0.5) - max(lp - 0.5, 0.05))


def test_mgmt_exits_on_delta_and_deep_itm_delta_is_one():
    assert put_delta(22000.0, 22500.0, 3 / 365, 400.0) == 1.0  # settle below parity intrinsic (500)
    ch = make_chain(crash)
    (tr,) = engine.run(ch, replace(CFG, exit_mode="mgmt"), *FIRST)
    assert tr.reason == "manage" and tr.exit <= tr.expiry and tr.pnl < 0


def test_dte_manage_executes_on_expiry_day_not_free_cash_settle():
    ch = make_chain(FLAT)
    cfg = replace(CFG, exit_mode="mgmt", tp_residual=0.0, delta_manage=0.99)
    (tr,) = engine.run(ch, cfg, *FIRST)
    assert tr.reason == "manage" and tr.exit == tr.expiry  # decided Wed (dte 1), executed Thu with slippage


def test_bootstrap_all_winners_returns_nan():
    lo, hi = metrics.bootstrap_ci([1.0, 2.0, 3.0], metrics.profit_factor)
    assert lo != lo and hi != hi


def test_sizing_equity_capped_at_equity0():
    ch = make_chain(FLAT)
    rng = (date(2023, 1, 2), date(2023, 3, 31))
    t0 = engine.run(ch, CFG, *rng)[0]
    ml = (100 - t0.credit) * LOT
    cfg = replace(CFG, equity0=ml * 6.99 / 0.02)  # budget just under 7 lots; one profit would round up to 7 uncapped
    ts = engine.run(ch, cfg, *rng)
    assert len(ts) >= 3 and {t.lots for t in ts} == {6}


def test_holiday_shifted_expiry_settles_on_previous_trading_day():
    # series listed for Thu 2023-01-12; exchange closed that day, series relabelled 01-11 on its last day at intrinsic
    base = make_chain(FLAT)
    f = 22000.0
    df = pl.concat(list(base.days.values())).filter(pl.col("date") != date(2023, 1, 12))
    last = (pl.col("date") == date(2023, 1, 11)) & (pl.col("expiry") == date(2023, 1, 12))
    intr = pl.when(pl.col("opt_type") == "CE").then((f - pl.col("strike")).clip(lower_bound=0.05)) \
        .otherwise((pl.col("strike") - f).clip(lower_bound=0.05))
    df = df.with_columns(
        settle=pl.when(last).then(intr).otherwise(pl.col("settle")),
        expiry=pl.when(last).then(pl.lit(date(2023, 1, 11))).otherwise(pl.col("expiry")))
    (tr,) = engine.run(Chain(df), CFG, *FIRST)
    assert tr.expiry == date(2023, 1, 12) and tr.exit == date(2023, 1, 11) and tr.reason == "expiry"
    assert tr.exit_cost == pytest.approx(0.0)  # flat spot: both legs worthless at intrinsic


def test_expiry_day_settle_column_is_index_price_not_option_value():
    # bhavcopy 2020+: on expiry day every strike's `settle` is the index settlement (21000), not the option value
    base = make_chain(crash)
    df = pl.concat(list(base.days.values())).with_columns(
        settle=pl.when(pl.col("date") == pl.col("expiry")).then(pl.lit(21000.0)).otherwise(pl.col("settle")))
    (tr,) = engine.run(Chain(df), CFG, *FIRST)
    assert tr.reason == "expiry" and tr.exit_cost == pytest.approx(100.0)  # both puts ITM: full width lost
    assert tr.pnl < 0
    # a pending TP/stop executing on expiry day also prices off the index settle, not the raw column
    (st,) = engine.run(Chain(df), replace(CFG, exit_mode="stop2x"), *FIRST)
    assert st.exit_cost > 50


def test_pre_feb_2020_zero_settle_expiry_uses_close_parity():
    # bhavcopy before 2020-02-06: expiry-day `settle` is 0.0 on every row; index must come from parity on `close`
    base = make_chain(crash)
    df = pl.concat(list(base.days.values())).with_columns(close=pl.col("settle")).with_columns(
        settle=pl.when(pl.col("date") == pl.col("expiry")).then(pl.lit(0.0)).otherwise(pl.col("settle")))
    (tr,) = engine.run(Chain(df), CFG, *FIRST)
    assert tr.reason == "expiry" and tr.exit_cost == pytest.approx(100.0, abs=1.0)  # both puts ITM
    assert tr.pnl < 0


def test_zero_settle_expiry_without_parity_pairs_raises():
    # all-zero expiry-day settle and no CE/PE pairs on `close` -> must fail loudly, not value the spread at 0
    ex = date(2019, 6, 27)
    day = pl.DataFrame({"expiry": [ex] * 3, "strike": [10000.0, 10100.0, 10200.0], "opt_type": ["PE"] * 3,
                        "settle": [0.0] * 3, "close": [5.0, 6.0, 7.0], "contracts": [100] * 3})
    with pytest.raises(ValueError, match="zero-settle"):
        engine.underlying_settle(day, ex)
