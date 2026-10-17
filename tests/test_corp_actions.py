from datetime import date, timedelta

import polars as pl
import pytest

from research.corp_actions import (adjust, day_factors, flag, gate_days, manual_events, map_events, parse_subject,
                                   schemes, stale, suspects, unofficial)

D = [date(2014, 12, d) for d in (1, 2, 3, 4)]


@pytest.mark.parametrize("subject, want", [
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", [("split", 0.2)]),
    ("Fv Spl-Rs10tore1/Bon-1:1", [("split", 0.1), ("bonus", 0.5)]),
    ("Fv Splt Frm Rs 10 To Rs 2", [("split", 0.2)]),
    ("Consolidation Of Equity Shares From Re 1 Per Share To Rs 10 Per Share", [("split", 10.0)]),
    ("Bonus Shares In The Ratio Of 1:2", [("bonus", 2 / 3)]),
    ("Rights 7:50 @ Premium Rs.59/-", [("rights", 7.0, 50.0, 59.0)]),
    ("Rights 4:7 At Par", [("rights", 4.0, 7.0, 0.0)]),
    ("Agm/Rights-35:12", [("rights", 35.0, 12.0, None)]),
    ("Spl Div-Rs.80/- Per Share", []),
    ("Bonus 1 Dvr : 10 Eq Share", []),
    ("Intdiv-Rs 3persh/Bonus1:1", [("bonus", 0.5)]),
    ("Rht 7:2@Prem Rs 20 Per Sh", [("rights", 7.0, 2.0, 20.0)]),
    ("Bonds Of 1:2", []),
])
def test_parse_subject(subject, want):
    assert parse_subject(subject) == want


NSE = "https://www.nseindia.com/api/corporates-corporateActions?index=equities"


def _ev(symbol, isin, ex, kind, f=None, a=None, b=None, premium=None, face=10.0, source=NSE):
    return {"symbol": symbol, "isin": isin, "ex_date": ex, "face": face, "subject": "", "kind": kind, "f": f,
            "a": a, "b": b, "premium": premium, "source": source}


def _events(*rows):  # the schema raw_events() gives (all-null columns would otherwise be dtype Null)
    return pl.DataFrame(list(rows), schema={"symbol": pl.Utf8, "isin": pl.Utf8, "ex_date": pl.Date, "face": pl.Float64,
                                            "subject": pl.Utf8, "kind": pl.Utf8, "f": pl.Float64, "a": pl.Float64,
                                            "b": pl.Float64, "premium": pl.Float64, "source": pl.Utf8})


def test_manual_events_need_nse_or_bse_source(tmp_path):
    p = tmp_path / "m.csv"
    head = "symbol,isin,ex_date,kind,f,source\n"
    p.write_text(head + "TCS,,2006-07-28,bonus,0.5,https://www.bseindia.com/x\n")
    assert manual_events(p)["subject"][0] == "manual: https://www.bseindia.com/x"
    for row in ("TCS,,2006-07-28,bonus,0.5,https://finance.yahoo.com/x", "TCS,,2006-07-28,bonus,0.5,",
                "TCS,,2006-07-28,rights,0.5,https://www.nseindia.com/x", "TCS,,2006-07-28,split,0,https://www.nseindia.com/x"):
        p.write_text(head + row + "\n")
        with pytest.raises(ValueError):
            manual_events(p)
    p.write_text(head)
    assert manual_events(p).is_empty()


def test_unofficial_flags_applied_events_without_nse_bse_source():
    ev = _events(_ev("A", None, D[0], "split", f=0.5), _ev("B", None, D[0], "bonus", f=0.5, source=None),
                 _ev("C", None, D[0], "bonus", f=0.5, source="https://query1.finance.yahoo.com/x"),
                 _ev("D", None, D[0], "rights", source=None),            # unresolved (f null): not applied
                 _ev("E", None, D[0], "bonus", f=0.5, source=None))      # not in the sample
    ev = ev.with_columns(perm_id=pl.col("symbol"))
    assert unofficial(ev, ["A", "B", "C", "D"])["perm_id"].to_list() == ["B", "C"]


def test_map_events_isin_path_rights_and_adjust():
    # P traded as OLD before the event; NSE reports today's symbol NEW with the ISIN.
    rows = pl.DataFrame({"date": D, "symbol": ["OLD"] * 4, "perm_id": ["INE1"] * 4,
                         "open": [100.0, 51.0, 50.0, 50.0], "close": [100.0, 50.0, 50.0, 40.0],
                         "prev_close": [None, 100.0, 50.0, 50.0]})
    ids = pl.DataFrame({"node": ["INE1"], "perm_id": ["INE1"]})
    ev = _events(_ev("NEW", "INE1", D[1], "bonus", f=0.5),
                 _ev("NEW", "INE1", D[3], "rights", a=1.0, b=1.0, premium=10.0),   # TERP (1+20/50)/2 = 0.7
                 _ev("NEW", "INE1", D[2], "rights", a=1.0, b=1.0),                 # no premium: unresolved
                 _ev("GONE", "INE9", date(2020, 1, 1), "bonus", f=0.5))
    m, un = map_events(ev, rows, ids)
    assert un["symbol"].to_list() == ["GONE"]
    got = {(r["date"], r["kind"]): r["f"] for r in m.iter_rows(named=True)}
    assert got[(D[1], "bonus")] == 0.5 and got[(D[3], "rights")] == pytest.approx(0.7)
    assert got[(D[2], "rights")] is None
    adj = adjust(rows, day_factors(m))["adj"].to_list()
    assert adj == pytest.approx([0.35, 0.7, 0.7, 1.0])


def test_map_events_renamed_symbol_and_manual_duplicate():
    # NSE files a pre-ISIN event under today's symbol NEW; the stock traded as OLD then (one perm_id "P").
    rows = pl.DataFrame({"date": D, "symbol": ["OLD", "OLD", "NEW", "NEW"], "perm_id": ["P"] * 4,
                         "open": [100.0] * 4, "close": [100.0] * 4, "prev_close": [None, 100.0, 100.0, 100.0]})
    no_ids = pl.DataFrame(schema={"node": pl.Utf8, "perm_id": pl.Utf8})
    m, un = map_events(_events(_ev("NEW", None, D[1], "split", f=0.1)), rows, no_ids)
    assert un.is_empty() and m.select("perm_id", "date").rows() == [("P", D[1])]
    dup = _events(_ev("NEW", None, D[1], "split", f=0.1),
                  {**_ev("NEW", None, D[1], "split", f=0.1, source="https://www.bseindia.com/x"), "subject": "manual: x"})
    with pytest.raises(ValueError):
        map_events(dup, rows, no_ids)
    man = {**_ev("NEW", None, D[2], "split", f=0.1, source="https://www.bseindia.com/x"), "subject": "manual: x"}
    assert map_events(_events(man), rows, no_ids)[0].height == 1
    with pytest.raises(ValueError):                # two manual rows on one session
        map_events(_events(man, man), rows, no_ids)


def test_flag_counts_flags_per_stock_in_date_order():
    rows = pl.DataFrame({"perm_id": ["A"] * 4 + ["B"] * 2, "date": [D[3], D[0], D[1], D[2], D[0], D[1]]})
    got = flag(rows, pl.DataFrame({"perm_id": ["A", "A", "B"], "date": [D[1], D[1], D[0]]}))
    assert got.select("perm_id", "date", "ca_flag", "ca_flag_n").rows() == [
        ("A", D[0], False, 0), ("A", D[1], True, 1), ("A", D[2], False, 1), ("A", D[3], False, 1),
        ("B", D[0], True, 1), ("B", D[1], False, 1)]
    # window (D[0], D[2]] spans A's flag; (D[1], D[3]] does not


def test_stale_and_schemes():
    cal = [date(2014, 1, 1) + timedelta(i) for i in range(40)]
    rows = pl.DataFrame({"perm_id": ["P"] * 4, "symbol": ["OLD", "OLD", "NEW", "NEW"],
                         "date": [cal[0], cal[1], cal[22], cal[23]],
                         "open": [100.0, 100.0, 40.0, 41.0], "close": [100.0, 100.0, 40.0, 41.0],
                         "prev_close": [None, 100.0, 100.0, 40.0]})
    assert stale(rows, cal).rows() == [("P", cal[22], 21)]           # 21 sessions back > STALE
    assert stale(rows.with_columns(date=pl.Series(cal[:4])), cal).is_empty()
    feed = pl.DataFrame({"symbol": ["OLD", "NEW", "NEW"], "ex": [cal[20], cal[23], cal[0]],
                         "subj": ["Demerger", "Scheme Of Arrangement", "Demerger"]})
    no_days = pl.DataFrame(schema={"perm_id": pl.Utf8, "date": pl.Date, "f": pl.Float64})
    # cal[22]: -60% gap, OLD's demerger 2 days before -> flagged; cal[23]: +2.5% gap -> not; cal[0] filing too old
    assert schemes(rows, no_days, feed).select("perm_id", "date").rows() == [("P", cal[22])]
    # a split factor that explains the gap leaves nothing to flag
    days = pl.DataFrame({"perm_id": ["P"], "date": [cal[22]], "f": [0.4]})
    assert schemes(rows, days, feed).is_empty()


def test_rights_above_cum_price_is_worthless():
    rows = pl.DataFrame({"date": D[:2], "symbol": ["S"] * 2, "perm_id": ["S"] * 2, "open": [10.0, 10.0],
                         "close": [10.0, 10.0], "prev_close": [None, 10.0]})
    ev = _events(_ev("S", None, D[1], "rights", a=1.0, b=1.0, premium=40.0))
    m, _ = map_events(ev, rows, pl.DataFrame(schema={"node": pl.Utf8, "perm_id": pl.Utf8}))
    assert m["f"].to_list() == [1.0]


def test_gate_days_counts_missing_dates_as_misses():
    sub = pl.DataFrame({"perm_id": ["P"] * 3, "date": D[:3], "adj_close": [100.0, 102.0, 101.0]})
    closes = {D[0]: 50.0, D[1]: 51.0}            # Yahoo lacks D[2]
    rows = gate_days(sub, [D[0], D[1], D[2], date(2027, 1, 1)], closes)
    assert [(r["date"], r["ok"]) for r in rows] == [(D[1], True), (D[2], False)]


def test_suspects_skip_event_days_and_penny_stocks():
    rows = pl.DataFrame({"perm_id": ["A", "A", "B", "C"], "symbol": ["A", "A", "B", "C"],
                         "date": [D[1], D[2], D[1], D[1]],
                         "prev_close": [100.0, 100.0, 3.0, 100.0], "open": [50.2, 50.0, 1.5, 97.0]})
    days = pl.DataFrame({"perm_id": ["A"], "date": [D[2]], "f": [0.5]})
    assert suspects(rows, days)["date"].to_list() == [D[1]] and suspects(rows, days)["perm_id"][0] == "A"
