from datetime import date, timedelta

import polars as pl

from research.e4_whale import block_bootstrap, cluster, signals, windows

D1, D2 = date(2012, 3, 1), date(2012, 3, 2)


def _deals(rows):
    return pl.DataFrame(rows, schema=["date", "symbol", "client", "side", "qty", "kind"], orient="row")


def test_signals_fallback_rule():
    s = signals(_deals([
        (D1, "A", "XYZ Mutual Fund", "BUY", 100, "bulk"),        # bulk inst buyer, net > 0 -> whale
        (D1, "B", "abc capital ltd", "BUY", 100, "block"),       # block-only buy -> not whale, block_buy
        (D1, "C", "Big Bank", "BUY", 100, "bulk"),
        (D1, "C", "Big Bank", "SELL", 150, "block"),             # client's own net < 0, total net < 0 -> sell
        (D1, "D", "Some Fund", "BUY", 50, "bulk"),
        (D1, "D", "Other Pension", "SELL", 80, "block"),         # bulk buyer but total net < 0 -> neither
        (D2, "E", "Retail Person", "BUY", 999, "bulk"),          # not institutional: no row
    ])).sort("symbol")
    assert s["symbol"].to_list() == ["A", "B", "C", "D"]
    assert s["buy"].to_list() == [True, False, False, False]
    assert s["sell"].to_list() == [False, False, True, False]
    assert s["block_buy"].to_list() == [False, True, False, False]


def test_cluster_and_windows():
    cal = [date(2012, 1, 2) + timedelta(days=i) for i in range(60)]
    ev = cluster([("A", cal[0]), ("A", cal[5]), ("A", cal[20]), ("A", cal[21]), ("B", cal[5])], cal, gap=20)
    assert ev == [("A", cal[0]), ("B", cal[5]), ("A", cal[21])]  # cal[20] is 20 sessions after cal[0]: same event
    w = windows([("A", cal[0]), ("A", cal[58])], cal, 3)
    assert w.row(0, named=True)["t0"] == cal[1] and w.row(0, named=True)["t1"] == cal[3]
    assert w.row(1, named=True)["t1"] is None


def test_block_bootstrap_deterministic_and_brackets_mean():
    d0 = date(2010, 1, 4)
    k = pl.DataFrame({"entry_date": [d0 + timedelta(weeks=i) for i in range(100)],
                      "abn": [0.01 if i % 3 else -0.01 for i in range(100)]})
    lo, hi = block_bootstrap(k, span=(d0, d0 + timedelta(weeks=99)))
    assert (lo, hi) == block_bootstrap(k, span=(d0, d0 + timedelta(weeks=99)))
    assert lo < k["abn"].mean() < hi
