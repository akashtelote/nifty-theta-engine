import struct
from datetime import date, timedelta

import polars as pl

from research.futures import SCHEMA, _dbf, continuous, monthly, nse_lots, parse_cds, parse_mcx, parse_nse


def _dbf_bytes(fields, rows):
    hlen, rlen = 32 + 32 * len(fields) + 1, 1 + sum(n for _, n in fields)
    out = bytes([3, 124, 1, 1]) + struct.pack("<IHH", len(rows), hlen, rlen) + bytes(20)
    for name, n in fields:
        out += name.encode().ljust(11, b"\0") + b"C" + bytes(4) + bytes([n]) + bytes(15)
    out += b"\r"
    for r in rows:
        out += b" " + b"".join(v.encode().ljust(n) for v, (_, n) in zip(r, fields))
    return out


def test_cds_legacy_dbf():
    f = [("CONTRACT_D", 25), ("OPEN_PRICE", 8), ("HIGH_PRICE", 8), ("LOW_PRICE", 8), ("CLOSE_PRIC", 8),
         ("SETTLEMENT", 8), ("OI_NO_CON", 8), ("TRADED_QUA", 8), ("TRADED_VAL", 12)]
    raw = _dbf_bytes(f, [("FUTCURUSDINR29-DEC-2010", "45.5", "45.6", "45.4", "45.55", "45.55", "100", "20",
                          "911000"),
                         ("FUTCUREURUSD29-DEC-2010", "1.3", "1.3", "1.3", "1.3", "1.3", "1", "1", "1300"),
                         ("FUTCURJPYINR29-DEC-2010", "", "", "", "", "54.2", "0", "0", "0")])
    assert _dbf(raw).height == 3
    d = parse_cds(raw, date(2010, 12, 1))
    assert d["symbol"].to_list() == ["USDINR", "JPYINR"]
    r = d.row(0, named=True)
    assert (r["expiry"], r["close"], r["lots"], r["mult"]) == (date(2010, 12, 29), 45.55, 20, 1000.0)
    assert d["close"][1] is None and d["settle"][1] == 54.2


def test_parse_mcx_lot_and_units():
    row = {"Date": "01/04/2006", "Symbol": "GOLD      ", "ExpiryDate": "05FEB2006", "Open": "7000", "High": "7100",
           "Low": "6900", "Close": "7050", "Volume": "10", "VolumeInThousands": "10.000 GRMS", "Value": "70.5",
           "OpenInterest": "5", "InstrumentName": "FUTCOM  "}
    d = parse_mcx([row, {**row, "InstrumentName": "OPTFUT"}])
    r = d.row(0, named=True)
    assert d.height == 1 and r["date"] == date(2006, 1, 4) and r["expiry"] == date(2006, 2, 5)
    assert r["mult"] == 100.0 and r["value"] == 70.5e5  # 1 kg lot quoted per 10 g; Value in lakhs
    assert r["value"] / (r["lots"] * r["close"] * r["mult"]) == 1.0


def test_nse_lots_fill():
    d0 = date(2005, 1, 3)
    df = pl.DataFrame({"date": [d0, d0 + timedelta(1), d0, d0 + timedelta(1)], "exch": "NSE", "symbol": "NIFTY",
                       "expiry": [date(2005, 1, 27)] * 2 + [date(2005, 3, 31)] * 2,
                       "lots": [500, 3, 2, 0], "implied": [198.9, 150.0, 210.0, None], "mult": None},
                      schema_overrides={"mult": pl.Float64})
    out = nse_lots(df).sort("expiry", "date")
    assert out["mult"].to_list() == [200.0, 200.0, 200.0, 200.0]  # carried in contract, then from same day


def test_continuous_roll_and_additive_adjust():
    cal = [date(2020, 1, 1) + timedelta(days=i) for i in range(12)]
    e1, e2 = cal[7], date(2020, 3, 1)
    rows = [(d, e1, 100.0 + i) for i, d in enumerate(cal[:8])] + [(d, e2, 110.0 + i) for i, d in enumerate(cal)]
    df = pl.DataFrame(rows, schema=["date", "expiry", "close"], orient="row").with_columns(settle=pl.col("close"), lots=pl.lit(1))
    c = continuous(df, roll=5)
    # e1 has 5 sessions left on cal[2] (cal[3..7]) -> roll there; never back
    assert c["expiry"].to_list() == [e1, e1] + [e2] * 10 and c["roll"].to_list() == [False, False, True] + [False] * 9
    gap = 112.0 - 102.0
    assert c["adj_close"].to_list()[:3] == [100.0 + gap, 101.0 + gap, 112.0]
    assert c["adj_close"].to_list()[3:] == c["close"].to_list()[3:]
    neg = continuous(df.with_columns(close=pl.col("close") - 150.0, settle=pl.col("close") - 150.0))
    assert neg["adj_close"].diff().drop_nulls().to_list() == c["adj_close"].diff().drop_nulls().to_list()


def test_schema_columns():
    assert parse_mcx([]).schema == pl.Schema(SCHEMA)


def test_parse_nse_two_digit_expiry_year():
    hdr = "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT\n"
    raw = (hdr + "FUTIDX,NIFTY,31-May-12,0,XX,4930,4950,4880,4888.25,4888.25,2,4.9,10\n"
                 "FUTIDX,NIFTY,28-Jun-2012,0,XX,4950,4960,4900,4904.15,4904.15,1,2.5,5\n"
                 "OPTIDX,NIFTY,31-May-12,5000,CE,1,1,1,1,1,1,1,1\n").encode()
    assert parse_nse(raw, date(2012, 5, 14))["expiry"].to_list() == [date(2012, 5, 31), date(2012, 6, 28)]


def test_cds_udiff_units():
    raw = ("TckrSymb,FinInstrmTp,XpryDt,OpnPric,HghPric,LwPric,ClsPric,SttlmPric,TtlTradgVol,TtlTrfVal,OpnIntrst,"
           "NewBrdLotQty\nUSDINR,CDF,2024-07-29,83.5,83.6,83.5,83.5575,83.5575,124999,104397.16,10,1\n").encode()
    r = parse_cds(raw, date(2024, 7, 8)).row(0, named=True)
    assert r["mult"] == 1000.0 and abs(r["value"] / (r["lots"] * r["close"] * r["mult"]) - 1) < 1e-3


def test_nse_lots_keeps_contract_mode_on_volatile_day():
    d0 = date(2020, 3, 2)
    df = pl.DataFrame({"date": [d0 + timedelta(i) for i in range(4)], "exch": "NSE", "symbol": "NIFTY",
                       "expiry": date(2020, 3, 26), "lots": [100] * 4, "implied": [75.1, 74.8, 72.4, 50.2],
                       "mult": None}, schema_overrides={"mult": pl.Float64})
    assert nse_lots(df).sort("date")["mult"].to_list() == [75.0, 75.0, 75.0, 50.0]  # 72.4 -> 75; 50 is a real change


def test_continuous_gap_uses_last_common_day():
    cal = [date(2020, 1, 1) + timedelta(days=i) for i in range(12)]
    e1, e2 = cal[7], date(2020, 3, 1)
    rows = [(d, e1, 100.0 + i) for i, d in enumerate(cal[:8]) if i != 2] + [(d, e2, 110.0 + 2 * i)
                                                                           for i, d in enumerate(cal)]
    df = pl.DataFrame(rows, schema=["date", "expiry", "close"], orient="row").with_columns(settle=pl.col("close"), lots=pl.lit(1))
    c = continuous(df, roll=5)  # roll on cal[2] where e1 is unquoted: gap from cal[1]
    assert c["roll"].to_list()[2] and c["adj_close"][2] - c["adj_close"][1] == 2.0  # e2's own move cal[1]->cal[2]


def test_monthly_drops_weeklies():
    rows = [(date(2024, 1, d), "EURINR", e, n) for d in (2, 3) for e, n in
            ((date(2024, 1, 12), 5), (date(2024, 1, 29), 900), (date(2024, 2, 2), 1), (date(2024, 2, 27), 300))]
    df = pl.DataFrame(rows, schema=["date", "symbol", "expiry", "lots"], orient="row")
    assert sorted(set(monthly(df)["expiry"])) == [date(2024, 1, 29), date(2024, 2, 27)]


def test_monthly_keeps_redated_contract_and_rolls_without_gap():
    d1, d2 = date(2025, 1, 1), date(2025, 1, 2)
    df = pl.DataFrame([(d1, "BANKNIFTY", date(2025, 1, 29), 100.0, 40), (d2, "BANKNIFTY", date(2025, 1, 30), 101.0, 90)],
                      schema=["date", "symbol", "expiry", "close", "lots"], orient="row")
    assert monthly(df).height == 2
    c = continuous(monthly(df).with_columns(settle=pl.col("close"), lots=pl.lit(1)), roll=0)
    assert c["adj_close"].to_list() == [100.0, 101.0]  # re-dated: the 1-point move stays a return


def test_monthly_drops_weekly_expiring_after_monthly():
    rows = [(date(2022, 4, d), "USDINR", e, n) for d in (4, 5) for e, n in
            ((date(2022, 4, 27), 9000), (date(2022, 4, 29), 400), (date(2022, 5, 27), 3000))]
    df = pl.DataFrame(rows, schema=["date", "symbol", "expiry", "lots"], orient="row")
    assert sorted(set(monthly(df)["expiry"])) == [date(2022, 4, 27), date(2022, 5, 27)]


def test_continuous_rolls_at_data_tail():
    cal = [date(2020, 1, 6) + timedelta(days=i) for i in range(5)]  # Mon..Fri; e1 expires next Tue, beyond the data
    e1, e2 = date(2020, 1, 14), date(2020, 2, 25)
    df = pl.DataFrame([(d, e, 100.0) for d in cal for e in (e1, e2)], schema=["date", "expiry", "close"],
                      orient="row").with_columns(settle=pl.col("close"), lots=pl.lit(1))
    assert continuous(df, roll=5)["expiry"].to_list()[-1] == e2


def test_continuous_prices_untraded_days_at_settle():
    cal = [date(2026, 7, 24) + timedelta(days=i) for i in range(3)]
    df = pl.DataFrame({"date": cal, "expiry": date(2026, 8, 27), "close": [63.3, 63.3, 59.2], "settle": [59.1, 58.9, 59.2],
                       "lots": [0, 0, 7]})
    assert continuous(df, roll=0)["close"].to_list() == [59.1, 58.9, 59.2]  # UDiFF stale ClsPric ignored


def test_continuous_follows_contract_redated_earlier():
    cal = [date(2024, 2, 26) + timedelta(days=i) for i in range(4)]
    e_old, e_new, e_apr = date(2024, 3, 28), date(2024, 3, 27), date(2024, 4, 24)
    rows = [(cal[0], e_old, 100.0), (cal[1], e_old, 101.0), (cal[2], e_new, 102.0), (cal[3], e_new, 103.0)] +            [(d, e_apr, 200.0 + i) for i, d in enumerate(cal)]
    df = pl.DataFrame(rows, schema=["date", "expiry", "close"], orient="row").with_columns(settle=pl.col("close"),
                                                                                          lots=pl.lit(1))
    c = continuous(df, roll=5)
    assert c["expiry"].to_list() == [e_old, e_old, e_new, e_new] and c["adj_close"].to_list() == [100.0, 101.0, 102.0, 103.0]
