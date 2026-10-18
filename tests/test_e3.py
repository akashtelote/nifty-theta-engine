import math
from datetime import date, timedelta

import polars as pl

from research import e3_trend as e3


def test_pregate_thresholds():
    d = [date(2020, 1, i) for i in (1, 2)]
    c = pl.DataFrame({"market": ["A", "A", "B", "B"], "date": d * 2, "product": "x", "live": True,
                      "notional": 1.0, "risk": [1.0, 1.0, 1e9, 1.0]})
    ok, t = e3.pregate(c, *d)
    assert ok and t["share"].to_list() == [1.0, 0.5] and t["holdable"].to_list() == [True, False]
    cap = e3.CAP_X * e3.TARGET / math.sqrt(2) * e3.CAPITAL
    assert not e3.pregate(c.with_columns(risk=pl.lit(cap * 1.01)), *d)[0]


def test_sizing_and_trade_rule():
    tr = e3.TARGET / 3 * e3.CAPITAL  # N = 9
    assert e3.target_lots(1.0, 9, tr / 2.5) == 3 and e3.target_lots(-1 / 3, 9, tr / 4.5) == -2  # half away from 0
    assert e3.target_lots(1.0, 9, 2.01 * tr) == 0 and e3.target_lots(1.0, 9, None) == 0
    assert e3.trade_ok(0, 1) and not e3.trade_ok(4, 4) and not e3.trade_ok(5, 6) and e3.trade_ok(4, 5)
    assert e3.trade_ok(3, -3) and not e3.trade_ok(0, 0)


def test_simulate_one_market_weekly_fill_and_roll():
    # NIFTY only: Mon 2015-01-05 .. Fri 2015-01-16; order set at Fri 01-09 close, filled at Mon 01-12 open;
    # contract rolls from e1 to e2 at Wed 01-14's open
    days = [date(2015, 1, 5) + timedelta(i) for i in range(12) if (date(2015, 1, 5) + timedelta(i)).weekday() < 5]
    e1, e2 = date(2015, 1, 29), date(2015, 2, 26)
    exp = [e1 if d < date(2015, 1, 14) else e2 for d in days]
    p = pl.DataFrame({"symbol": "NIFTY", "date": days, "expiry": exp, "adj_close": 100.0})
    px = pl.DataFrame({"symbol": "NIFTY", "expiry": [e1] * len(days) + [e2] * len(days), "date": days * 2,
                       "open": [100.0] * len(days) + [110.0] * len(days),
                       "close": [101.0] * len(days) + [111.0] * len(days), "mult": 50.0})
    c = pl.DataFrame({"market": "NIFTY", "date": days, "product": "NIFTY", "live": True, "notional": 5050.0,
                      "risk": e3.TARGET / 1 * e3.CAPITAL / 2})  # N=1 -> signal 1 targets 2 lots
    sig = {d: 1.0 for d in days}
    orig = e3.signals
    e3.signals = lambda _p: pl.DataFrame({"market": "NIFTY", "date": days, "signal": [sig[d] for d in days]})
    try:
        nav, s = e3.simulate(c, p, px, days[0], days[-1])
    finally:
        e3.signals = orig
    # Mon 01-05 sets prod; Fri 01-09 order -> Mon 01-12 buy 2 at 100; Wed 01-14 roll e1 -> e2 at the open
    assert s["orders"] == 2 and s["rolls"] == 1  # the fill, then the roll's re-open on e2
    pnl = dict(zip(nav["date"], nav["pnl"]))
    assert pnl[date(2015, 1, 9)] == 0.0 and pnl[date(2015, 1, 12)] == 2 * 50 * 1.0  # open 100 -> close 101
    assert pnl[date(2015, 1, 13)] == 0.0  # 101 -> open 100 -> close 101
    assert pnl[date(2015, 1, 14)] == 2 * 50 * (100 - 101) + 2 * 50 * (111 - 110)
    assert nav["held"][-1] == 1 and s["costs"] > 0


def test_fy_tax_carries_losses_forward():
    assert e3.fy_tax(2012, -100.0, 0.0) == (0.0, 100.0)
    t, cf = e3.fy_tax(2013, 150.0, 100.0)
    assert cf == 0.0 and math.isclose(t, e3.tax_rate(2013) * 50.0)
    assert e3.fy_tax(2014, 30.0, 50.0) == (0.0, 20.0)


def test_current_specs_rescales_risk_to_latest_lot():
    d = [date(2025, 10, 1), date(2025, 11, 3)]
    c = pl.DataFrame({"market": "NIFTY", "date": d, "product": "NIFTY", "live": True, "notional": [75.0, 65.0],
                      "risk": [7.5, 6.5]})
    p = pl.DataFrame({"symbol": "NIFTY", "date": d, "mult": [75.0, 65.0]})
    out = e3.at_current_specs(c, p, d[-1])
    assert out["risk"].to_list() == [6.5, 6.5] and out["notional"].to_list() == [65.0, 65.0]
