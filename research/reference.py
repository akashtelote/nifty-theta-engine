"""Point-in-time Nifty option reference data (Phase 2).

Lot size is a property of the *contract series*, so it is keyed by (trade date, expiry).
Sources / verification:
  * UDiFF era (trade date >= 2024-07-08): the bhavcopy itself carries NewBrdLotQty per row;
    use the data, not this table (25 -> 75 from 2024-11-22, 75 -> 65 from 2025-10-29 seen in data).
    Circulars: 25 -> 75 NSE circular of 18-Oct-2024 (new contracts from 2024-11-20, quarterly/half-yearly
    from 2024-12-26); 75 -> 65 NSE circular of 3-Oct-2025 (contracts from the Dec-2025/Jan-2026 series).
  * 2024-04-26: 50 -> 25, SEBI periodic review via NSE circular, effective 26-Apr-2024 (first weekly
    expiry 2024-05-02). Confirmed in data: on 2024-04-25 all expiries imply 50, on 2024-04-26 all imply 25
    (implied lot = legacy VAL_INLAKH*1e5 / (contracts*strike), modal value).
  * 2021: 75 -> 50, by contract series. Confirmed in data (implied lot, modal per expiry): on every trade
    date from 2021-06-14 on, expiries <= 2021-07-22 imply 75 and expiries >= 2021-07-29 imply 50; from
    2021-07-23 everything implies 50. Far-dated series (>45 dte) read 75 up to at least 2021-04-29 and are
    ambiguous 2021-05-01..07-22 (lot_size returns None). Not tied to an NSE circular number here.
  * 2015-10-30 .. 2021: 75 for every series (all 2019 contracts imply 75, including far-dated series).
  * 2011..2015-10-29 (backward holdout, implied lot = VAL_INLAKH*1e5 / (contracts*(strike+settle)), modal per
    expiry, checked on 2011-06-01, 2014-10-29/31, 2015-08-27/28, 2015-10-01/30, 2018-06-01): 50 until 2014-10-30;
    near series 25 from 2014-10-31 (far series stayed 50 until revised; the Mar/Jun-2015 ones were 25 by dte<=45,
    checked 2015-02-16, 05-20, 06-01); from 2015-08-28 new series (Nov-2015 on) 75 while the
    Sep/Oct-2015 series kept 25 to expiry. Far series (>45 dte) in 2014-10-31..2015-10-29 are mixed -> None.
    Matches NSE/F&O/069/2014 and NSE/F&O/071/2015 as cited secondhand (tradingqna); circulars not read directly.
Weekly expiry weekday: Thursday through the 2025-08-28 expiry; Tuesday for contracts expiring on or after
2025-09-02 (NSE circular of 25-Jun-2025, effective 1-Sep-2025; circular number not independently confirmed
-- the weekday change is confirmed from the expiry dates in the data, see expiry_weekday_by_year()).
Holidays: any weekday whose archive 404s (manifest.csv status 'holiday'); an expiry that falls on a holiday
shows up in the data on the previous trading day, so expiries are always taken from the data, never computed.
"""
from __future__ import annotations

from datetime import date

import polars as pl

UDIFF_START = date(2024, 7, 8)


def lot_size(trade_date: date, expiry: date) -> int | None:
    """Lot size for a pre-UDiFF (trade_date < 2024-07-08) contract; later dates use the data column.

    None = ambiguous: a series expiring after 2021-07-22 and >45 days out, traded 2021-05-01..2021-07-22.
    The 75->50 change hit far series on some trade date in Apr-Jun 2021 (implied lots there are noisy);
    inside the research scope (dte <= 45) the rule is unambiguous, so consumers must filter dte <= 45.
    """
    if trade_date >= UDIFF_START:
        raise ValueError("use the lot_size column from UDiFF rows")
    if trade_date < date(2015, 10, 30):
        if trade_date < date(2014, 10, 31):
            return 50
        if (expiry - trade_date).days > 45:
            return None
        return 25 if trade_date < date(2015, 8, 28) or expiry <= date(2015, 10, 29) else 75
    if trade_date >= date(2024, 4, 26):
        return 25
    if expiry <= date(2021, 7, 22):
        return 75
    if trade_date >= date(2021, 7, 23) or (expiry - trade_date).days <= 45:
        return 50
    return 75 if trade_date < date(2021, 5, 1) else None


def fill_lot_size(df: pl.DataFrame) -> pl.DataFrame:
    """Fill null lot_size (legacy rows) from the table above."""
    legacy = df.filter(pl.col("lot_size").is_null())
    rest = df.filter(pl.col("lot_size").is_not_null())
    if not legacy.is_empty():
        legacy = legacy.with_columns(
            pl.struct("date", "expiry").map_elements(
                lambda r: lot_size(r["date"], r["expiry"]), return_dtype=pl.Int64
            ).alias("lot_size")
        )
    return pl.concat([legacy, rest]).sort(["date", "expiry", "strike", "opt_type"])


def expected_weekday(expiry: date) -> int:
    """ISO weekday (Mon=1) of a regular Nifty weekly expiry: Thu before 2025-09-01, Tue after."""
    return 4 if expiry < date(2025, 9, 1) else 2


def expiry_weekday_by_year(df: pl.DataFrame) -> pl.DataFrame:
    return (df.select("expiry").unique()
            .with_columns(wd=pl.col("expiry").dt.weekday(), year=pl.col("expiry").dt.year())
            .group_by(["year", "wd"]).len().sort(["year", "wd"]))
