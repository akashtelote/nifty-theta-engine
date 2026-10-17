from datetime import date

from research.equity import parse, url_for

LEGACY = b"""SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,
3MINDIA,EQ,584,585,580,581.1,581,575.55,1387,808306.35,3-JAN-2005,
XYZ,BE,10,11,9,10.5,10.5,10,100,1050,3-JAN-2005,
0MOFSL27,N3,990,990,990,990,990,980,50,49500,3-JAN-2005,
"""
LEGACY_ISIN = b"""SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,
INFY,EQ,2100,2130,2090,2126.6,2125,4349.85,1000,2126600,02-DEC-2014,50,INE009A01021,
"""
UDIFF = (b"TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
         b"OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
         b"ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
         b"2024-07-05,2024-07-05,CM,NSE,STK,19277,INE778K01012,EMAMIREAL,EQ,,,,,EMAMI REALTY LIMITED,102.57,102.57,"
         b"100.00,100.86,101.30,101.11,,100.87,,,47263,4780850.96,1297,F1,1,,,,,\n"
         b"2024-07-05,2024-07-05,CM,NSE,STK,19078,IN0020200104,SGBJUN28,GB,,,,,GOLD,1,1,1,1,1,1,,1,,,1,1,1,F1,1,,,,,\n")


def test_parse_legacy_keeps_eq_be_and_null_isin():
    df = parse(LEGACY, date(2005, 1, 3))
    assert df["series"].to_list() == ["EQ", "BE"]
    assert df["isin"].null_count() == 2 and df["trades"].null_count() == 2
    assert df.row(0, named=True)["close"] == 581.1 and df.row(0, named=True)["qty"] == 1387


def test_parse_legacy_with_isin_and_udiff():
    r = parse(LEGACY_ISIN, date(2014, 12, 2)).row(0, named=True)
    assert (r["isin"], r["prevclose"], r["trades"]) == ("INE009A01021", 4349.85, 50)
    u = parse(UDIFF, date(2024, 7, 5))
    assert u.height == 1 and u.row(0, named=True)["symbol"] == "EMAMIREAL"
    assert u.row(0, named=True)["value"] == 4780850.96


def test_url_switches_format_after_legacy_end():
    assert url_for(date(2024, 7, 5)).endswith("EQUITIES/2024/JUL/cm05JUL2024bhav.csv.zip")
    assert url_for(date(2024, 7, 8)).endswith("cm/BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip")
