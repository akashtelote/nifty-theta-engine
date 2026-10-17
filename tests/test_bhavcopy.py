"""Offline tests for research/ (bhavcopy parse, reference data, execution model)."""
from datetime import date

import polars as pl
import pytest

from research import bhavcopy, execution, reference

LEGACY = (b"INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,\n"
          b"OPTIDX,NIFTY,03-Jan-2019,10800,PE,5,6,4,5.5,5.4,120.0,100,900,10,02-JAN-2019,\n"
          b"OPTIDX,BANKNIFTY,03-Jan-2019,27000,PE,5,6,4,5.5,5.4,120,100,900,10,02-JAN-2019,\n"
          b"FUTIDX,NIFTY,31-Jan-2019,0,XX,1,1,1,1,1,1,1,1,1,02-JAN-2019,\n")
UDIFF_HDR = (b"TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,"
             b"FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,"
             b"TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n")
UDIFF = (UDIFF_HDR
         + b"2024-07-08,2024-07-08,FO,NSE,IDO,1,,NIFTY,,2024-07-11,2024-07-11,24000.00,CE,N,1,2,0.5,1.5,1.5,1,24320.55,1.4,500,0,77,0.00,0,F1,25,,,,,\n"
         + b"2024-07-08,2024-07-08,FO,NSE,STO,2,,ABFRL,,2024-07-25,2024-07-25,250.00,PE,N,0,0,0,0.15,0.15,0.15,322.25,0.10,26000,0,0,0.00,0,F1,2600,,,,,\n")


def test_parse_legacy_filters_nifty_options_and_floats_contracts():
    df = bhavcopy.parse(LEGACY, date(2019, 1, 2))
    assert df.height == 1
    r = df.row(0, named=True)
    assert (r["expiry"], r["strike"], r["opt_type"], r["settle"], r["contracts"], r["oi"]) == (
        date(2019, 1, 3), 10800.0, "PE", 5.4, 120, 900)
    assert r["underlying"] is None and r["lot_size"] is None


def test_parse_udiff_filters_and_carries_lot_and_underlying():
    df = bhavcopy.parse(UDIFF, date(2024, 7, 8))
    assert df.height == 1
    r = df.row(0, named=True)
    assert (r["opt_type"], r["lot_size"], r["underlying"], r["settle"]) == ("CE", 25, 24320.55, 1.4)
    assert list(df.columns) == list(bhavcopy.SCHEMA)


def test_url_switch_at_legacy_end():
    assert bhavcopy.url_for(date(2024, 7, 5)).endswith("/DERIVATIVES/2024/JUL/fo05JUL2024bhav.csv.zip")
    assert bhavcopy.url_for(date(2024, 7, 8)).endswith("BhavCopy_NSE_FO_0_0_0_20240708_F_0000.csv.zip")


@pytest.mark.parametrize("trade,expiry,lot", [
    (date(2011, 6, 1), date(2011, 6, 30), 50),
    (date(2014, 10, 29), date(2015, 3, 26), 50),  # far series 50 before the cut
    (date(2014, 10, 30), date(2014, 11, 27), 50),
    (date(2014, 10, 31), date(2014, 11, 27), 25),   # data-derived: near series 25 from 31-Oct-2014
    (date(2014, 10, 31), date(2015, 3, 26), None),  # far series stayed 50: mixed, filtered by dte<=45
    (date(2015, 2, 16), date(2015, 3, 26), 25),     # pre-cut far series were 25 by the time dte<=45 (raw VAL_INLAKH)
    (date(2015, 5, 20), date(2015, 6, 25), 25),
    (date(2015, 8, 28), date(2015, 9, 24), 25),     # Sep/Oct-2015 series kept 25 to expiry
    (date(2015, 10, 1), date(2015, 10, 29), 25),
    (date(2015, 10, 15), date(2015, 11, 26), 75),   # new series 75 from 28-Aug-2015
    (date(2015, 10, 30), date(2015, 12, 31), 75),
    (date(2018, 6, 1), date(2018, 6, 28), 75),
    (date(2019, 6, 28), date(2019, 7, 4), 75),
    (date(2021, 7, 15), date(2021, 7, 22), 75),   # last 75 expiry (data-derived)
    (date(2021, 7, 23), date(2021, 7, 29), 50),   # first 50 expiry
    (date(2019, 6, 28), date(2021, 12, 30), 75),  # far series traded in 2019 is still 75 (review finding)
    (date(2021, 3, 26), date(2021, 9, 30), 75),
    (date(2021, 6, 16), date(2021, 7, 29), 50),   # near series after the switch, dte<=45
    (date(2021, 6, 16), date(2022, 12, 29), None),  # far series mid-switch: ambiguous, filtered by dte<=45
    (date(2024, 4, 25), date(2024, 12, 26), 50),  # far month still 50 the day before the change
    (date(2024, 4, 26), date(2024, 12, 26), 25),  # NSE circular effective 26-Apr-2024
])
def test_lot_size_rule(trade, expiry, lot):
    assert reference.lot_size(trade, expiry) == lot


def test_lot_size_rule_refuses_udiff_era():
    with pytest.raises(ValueError):
        reference.lot_size(date(2024, 7, 8), date(2024, 7, 11))


def test_fill_lot_size_only_fills_nulls():
    df = bhavcopy.parse(LEGACY, date(2019, 1, 2))
    assert reference.fill_lot_size(df)["lot_size"].to_list() == [75]
    u = bhavcopy.parse(UDIFF, date(2024, 7, 8))
    assert reference.fill_lot_size(u)["lot_size"].to_list() == [25]


def test_expected_weekday_switches_to_tuesday():
    assert reference.expected_weekday(date(2025, 8, 28)) == 4
    assert reference.expected_weekday(date(2025, 9, 2)) == 2


def test_fill_moves_against_us_and_floors_at_tick():
    assert execution.fill(10.0, "buy", 0.5) == 10.5
    assert execution.fill(10.0, "sell", 0.5) == 9.5
    assert execution.fill(0.2, "sell", 1.0) == execution.TICK
    with pytest.raises(ValueError):
        execution.fill(1.0, "hold", 0.5)


def test_fetch_day_needs_three_404s_for_holiday(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(bhavcopy.time, "sleep", lambda s: None)

    def sess(*codes):
        it = iter(codes)
        return SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=next(it), content=b""))

    assert bhavcopy.fetch_day(date(2021, 3, 28), sess(404, 404, 404)) == "holiday"
    assert bhavcopy.fetch_day(date(2021, 3, 30), sess(404, 500, 404)) == "error"  # retried next run, not cached
