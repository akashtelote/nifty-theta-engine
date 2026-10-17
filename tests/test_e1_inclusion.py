from datetime import date

import polars as pl

from research.e1_inclusion import bootstrap, events, hold

D = [date(2015, 3, d) for d in range(2, 21)]


def test_events_one_per_stock_highest_index():
    ch = pl.DataFrame({
        "announced": [date(2015, 2, 20)] * 5, "effective": [date(2015, 3, 27)] * 5,
        "index": ["NEXT50", "NIFTY50", "NIFTY500", "MIDCAP100", "NIFTY50"],
        "symbol": ["UP", "UP", "MID", "MID", "DOWN"], "side": ["remove", "add", "add", "add", "remove"],
        "kind": ["scheduled"] * 4 + ["criteria_revision"], "valid": [True] * 5,
    })
    ev = {r["symbol"]: r for r in events(ch).iter_rows(named=True)}
    assert len(ev) == 3
    assert (ev["UP"]["index"], ev["UP"]["side"]) == ("NIFTY50", "add")  # Next50 removal not counted
    assert ev["MID"]["index"] == "MIDCAP100" and ev["DOWN"]["side"] == "remove"


def test_hold_exit_and_rule7():
    px = {d: (100.0, 110.0, 1.0, 0) for d in D[:4]}
    t = hold(px, D, D[0], D[3])
    assert (t["entry"], t["exit"], t["exit_date"], t["forced"]) == (100.0, 110.0, D[3], False)
    t = hold(px | {D[8]: (1.0, 120.0, 1.0, 0)}, D, D[0], D[5])  # missing on exit day: next close (4 misses)
    assert (t["exit"], t["exit_date"], t["forced"]) == (120.0, D[8], False)
    t = hold(px, D, D[0], D[6])  # 5th consecutive missing session D[8]: last close -30%
    assert t["forced"] and t["exit_date"] == D[8] and abs(t["exit"] - 77.0) < 1e-9
    split = {D[0]: (200.0, 200.0, 0.5, 0), D[1]: (101.0, 102.0, 1.0, 1)}  # 2:1 split adjusted, flag counted
    t = hold(split, D, D[0], D[1])
    assert t["entry"] == 100.0 and t["exit"] == 102.0 and t["ca_n1"] > t["ca_n0"]
    assert hold(px, D, D[5], D[6]) == "no entry row"


def test_bootstrap_resamples_reviews():
    k = pl.DataFrame({"review": ["a", "a", "b", "c"], "abn": [0.0, 0.02, 0.02, 0.02]})
    lo, hi = bootstrap(k)
    assert 0.01 - 1e-12 <= lo < hi <= 0.02 + 1e-12
