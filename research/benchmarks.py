"""Index benchmarks from niftyindices.com (plan 20261017 E1-E4, task A3).

Endpoints (from liveindexsa.niftyindices.com/assets/js/IISLComponet.js, probed 2026-10-17):
  POST https://www.niftyindices.com/BackPage/getHistoricaldatatabletoString  -> price index OHLC
  POST https://www.niftyindices.com/BackPage/getTotalReturnIndexString       -> TRI
  body {"cinfo": "{'name':'NIFTY 500','startDate':'01-Jan-2005','endDate':'31-Dec-2005','indexName':'NIFTY 500'}"}
A whole year per request works (996 rows for 2005-2008 in one call). Nifty200 Momentum 30 starts at its
base date 2005-04-01.

Source note: the plan names NSE's ind_close_all snapshot for the Nifty 500 price-index open/close, but that
archive starts ~2013 (404 for 2010-2012). niftyindices (same index provider, NSE Indices Ltd) serves the price
OHLC back to 2005, so it is used for the whole span; `check_gaps` tests it against trading days.

Risk-free (plan amendment 2): RBI monthly SGL T-bill yield, 15-91 day bucket, DBIE SDMX YIELD_TB_RN via
  https://data-api.dbie.rbihub.in/api/tables/financial_markets/yield_tb_rn/rows (paged, limit/offset).
  The DBIE 91-day *auction* tables are integer-rounded (price "99", yield "05") and unusable.

Layout: data/benchmarks/<kind>_<slug>.parquet with columns date + open/high/low/close (price) or tri (TRI).
CLI: uv run python -m research.benchmarks [end-year]
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import polars as pl
import requests

ROOT = Path("data/benchmarks")
URL = "https://www.niftyindices.com/BackPage/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.niftyindices.com/reports/historical-data",
}
PRICE = ("NIFTY 50", "NIFTY 500")
TRI = ("NIFTY 50", "NIFTY 500", "NIFTY200 MOMENTUM 30")
FIRST_YEAR = 2005


def _post(session: requests.Session, endpoint: str, name: str, start: date, end: date) -> list[dict]:
    cinfo = "{'name':'%s','startDate':'%s','endDate':'%s','indexName':'%s'}" % (
        name, start.strftime("%d-%b-%Y"), end.strftime("%d-%b-%Y"), name)
    r = session.post(URL + endpoint, data=json.dumps({"cinfo": cinfo}), timeout=60)
    r.raise_for_status()
    d = json.loads(r.text)  # raises on the HTML error page -> fail loud
    return json.loads(d["d"]) if isinstance(d, dict) else d


def _num(c: str) -> pl.Expr:
    return pl.col(c).str.replace_all(",", "").str.strip_chars().cast(pl.Float64, strict=False)


def parse(rows: list[dict], kind: str) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema={"date": pl.Date, **({"tri": pl.Float64} if kind == "tri" else
                                    {k: pl.Float64 for k in ("open", "high", "low", "close")})})
    df = pl.DataFrame(rows, infer_schema_length=None).cast(pl.Utf8)
    if kind == "tri":
        out = df.select(pl.col("Date").str.strptime(pl.Date, "%d %b %Y").alias("date"),
                        _num("TotalReturnsIndex").alias("tri"))
    else:
        out = df.select(pl.col("HistoricalDate").str.strptime(pl.Date, "%d %b %Y").alias("date"),
                        *(_num(c.upper()).alias(c) for c in ("open", "high", "low", "close")))
    out = out.unique()
    if out["date"].is_duplicated().any():
        raise ValueError(f"conflicting values for {out.filter(pl.col('date').is_duplicated())['date'].unique().to_list()}")
    return out.sort("date")


def path(kind: str, name: str) -> Path:
    return ROOT / f"{kind}_{name.lower().replace(' ', '_')}.parquet"


def fetch(kind: str, name: str, last_year: int, pause: float = 1.0) -> pl.DataFrame:
    endpoint = "getTotalReturnIndexString" if kind == "tri" else "getHistoricaldatatabletoString"
    s = requests.Session()
    s.headers.update(HEADERS)
    parts = []
    for y in range(FIRST_YEAR, last_year + 1):
        part = parse(_post(s, endpoint, name, date(y, 1, 1), date(y, 12, 31)), kind)
        if part.is_empty():  # a rate-limit / hiccup returns [] -> never write a silently short series
            raise RuntimeError(f"{kind} {name}: no rows for {y}")
        parts.append(part)
        time.sleep(pause)
    df = pl.concat(parts).sort("date")
    ROOT.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path(kind, name))
    return df


TBILL_URL = "https://data-api.dbie.rbihub.in/api/tables/financial_markets/yield_tb_rn/rows"
TBILL_PATH = ROOT / "tbill_15to91_monthly.parquet"
TBILL_FROM = date(2005, 1, 31)  # earliest month any E-hypothesis uses; RBI gaps 2001-08 and 2004-10 lie before it


def parse_tbill(columns: list[str], rows: list[list]) -> pl.DataFrame:
    """Month-end date + yield in percent p.a. for the 15-91 day bucket."""
    df = pl.DataFrame(rows, schema=columns, orient="row", infer_schema_length=None)
    out = df.filter(pl.col("mat_term_d_rn") == "15TO91").select(
        pl.col("time_period").cast(pl.Utf8).str.strptime(pl.Date, "%Y-%m-%d").alias("date"),
        pl.col("obs_value").cast(pl.Float64).alias("yield_pct"))
    if out["date"].is_duplicated().any() or out["yield_pct"].null_count():
        raise ValueError("T-bill series has duplicate months or null yields")
    out = out.sort("date")
    used = out.filter(pl.col("date") >= TBILL_FROM)["date"].to_list()
    months = [d.year * 12 + d.month for d in used]
    if not months or months != list(range(months[0], months[0] + len(months))) or used[0].month != TBILL_FROM.month             or used[0].year != TBILL_FROM.year:
        raise ValueError(f"T-bill series not contiguous monthly from {TBILL_FROM:%Y-%m}")
    return out


def fetch_tbill() -> pl.DataFrame:
    s = requests.Session()
    s.headers.update({"User-Agent": HEADERS["User-Agent"]})
    rows, off, cols = [], 0, None
    while True:
        r = s.get(TBILL_URL, params={"limit": 1000, "offset": off}, timeout=60)
        r.raise_for_status()
        d = r.json()
        cols = d["columns"]
        rows += d["rows"]
        off += d["returned"]
        if d["returned"] < 1000:
            break
    if not rows:  # hiccup / schema change -> never overwrite the stored series with nothing
        raise RuntimeError("T-bill API returned no rows")
    df = parse_tbill(cols, rows)
    ROOT.mkdir(parents=True, exist_ok=True)
    df.write_parquet(TBILL_PATH)
    return df


def load(kind: str, name: str) -> pl.DataFrame:
    return pl.read_parquet(path(kind, name))


def check_gaps(df: pl.DataFrame, trading_days: list[date], col: str) -> list[date]:
    """Trading days with no row or a null value in `col`. The caller passes exactly the days the series must
    cover (e.g. from 2005-04-01 for Momentum 30), so a missing head or tail counts as a gap."""
    have = set(df.filter(pl.col(col).is_not_null())["date"].to_list())
    return [d for d in trading_days if d not in have]


if __name__ == "__main__":
    last = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year
    for n in PRICE:
        print("price", n, fetch("price", n, last).height)
    for n in TRI:
        print("tri", n, fetch("tri", n, last).height)
    print("tbill", fetch_tbill().height)
