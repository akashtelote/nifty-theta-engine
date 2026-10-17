from datetime import date, timedelta

import polars as pl

from research.equity_coverage import gap_days, isin_near_misses, sym_long_gaps

D = [date(2011, 1, 3) + timedelta(i) for i in range(200)]


def test_near_misses_skip_linked_and_other_codes():
    nodes = pl.DataFrame({"node": ["INE111A01011", "INE111A01029", "INE111A01037", "INE222B01011", "SYM:X"],
                          "first": [D[0], D[5], D[10], D[5], D[0]], "last": [D[2], D[8], D[12], D[6], D[1]],
                          "sym0": ["A", "A", "A", "B", "X"], "sym1": ["A", "A", "A", "B", "X"]})
    links = pl.DataFrame({"a": ["INE111A01029"], "b": ["INE111A01037"], "missing": [1]})
    near = isin_near_misses(nodes, links, D)
    assert near.select("node", "node_b", "missing").rows() == [("INE111A01011", "INE111A01029", 2),
                                                               ("INE111A01011", "INE111A01037", 7)]


def test_sym_long_gaps_and_gap_days():
    rows = pl.DataFrame({"date": [D[0], D[62], D[63], D[0]], "symbol": ["S", "S", "S", "T"],
                         "isin": [None, None, None, "INE1"]}, schema={"date": pl.Date, "symbol": pl.Utf8,
                                                                       "isin": pl.Utf8})
    assert sym_long_gaps(rows, D).rows() == [("S", D[0], D[62], 61)]
    assert gap_days([D[0], D[2]], [D[0], D[1], D[2], D[3]]) == [D[1]]
