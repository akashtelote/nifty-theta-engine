"""NSE equity (CM) bhavcopy -> partitioned Parquet of EQ and BE series (plan 20261017 E1-E4, task A1).

Archives (probed 2026-10-17):
  * legacy  .../content/historical/EQUITIES/<YYYY>/<MON>/cm<DDMONYYYY>bhav.csv.zip
            last day 2024-07-05 (404 from 2024-07-08). ISIN column only in later years; null before.
  * UDiFF   .../content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip  (overlaps legacy on 2024-07-05)
Prices are as traded: PREVCLOSE is NOT corporate-action adjusted (INFY 2014-12-02 close 2126.6, prev 4349.85).
Adjustment is A2; the permanent stock ID (ISIN chaining) is built on top of these rows.

Layout: data/equity/year=YYYY/<YYYY-MM-DD>.parquet, data/equity/manifest.csv (date,status).
CLI: uv run python -m research.equity 2005-01-01 [end-date]   (resumable)
"""
from __future__ import annotations

import io
import sys
from datetime import date
from pathlib import Path

import polars as pl

from research import bhavcopy

ROOT = Path("data/equity")
MANIFEST = ROOT / "manifest.csv"
SERIES = ("EQ", "BE")

SCHEMA = {
    "date": pl.Date, "symbol": pl.Utf8, "series": pl.Utf8, "isin": pl.Utf8,
    "open": pl.Float64, "high": pl.Float64, "low": pl.Float64, "close": pl.Float64,
    "prevclose": pl.Float64, "qty": pl.Int64, "value": pl.Float64, "trades": pl.Int64,
}


def url_for(d: date) -> str:
    if d <= bhavcopy.LEGACY_LAST:
        mon = d.strftime("%b").upper()
        return f"{bhavcopy.BASE}/historical/EQUITIES/{d.year}/{mon}/cm{d.day:02d}{mon}{d.year}bhav.csv.zip"
    return f"{bhavcopy.BASE}/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def _f(c: str) -> pl.Expr:
    return pl.col(c).str.strip_chars().cast(pl.Float64, strict=False)


def parse(raw_csv: bytes, d: date) -> pl.DataFrame:
    """Normalise one day's csv (either format, auto-detected from header) to SCHEMA, EQ/BE rows only."""
    df = pl.read_csv(io.BytesIO(raw_csv), infer_schema_length=0, truncate_ragged_lines=True)
    df = df.rename({c: c.strip() for c in df.columns})
    if "TckrSymb" in df.columns:  # UDiFF
        o = df.filter(pl.col("SctySrs").is_in(SERIES))
        return o.select(
            pl.lit(d).alias("date"), pl.col("TckrSymb").alias("symbol"), pl.col("SctySrs").alias("series"),
            pl.col("ISIN").alias("isin"), _f("OpnPric").alias("open"), _f("HghPric").alias("high"),
            _f("LwPric").alias("low"), _f("ClsPric").alias("close"), _f("PrvsClsgPric").alias("prevclose"),
            _f("TtlTradgVol").cast(pl.Int64).alias("qty"), _f("TtlTrfVal").alias("value"),
            _f("TtlNbOfTxsExctd").cast(pl.Int64).alias("trades"),
        ).cast(SCHEMA)
    o = df.filter(pl.col("SERIES").str.strip_chars().is_in(SERIES))
    return o.select(
        pl.lit(d).alias("date"), pl.col("SYMBOL").str.strip_chars().alias("symbol"),
        pl.col("SERIES").str.strip_chars().alias("series"),
        (pl.col("ISIN").str.strip_chars() if "ISIN" in df.columns else pl.lit(None, pl.Utf8)).alias("isin"),
        _f("OPEN").alias("open"), _f("HIGH").alias("high"), _f("LOW").alias("low"), _f("CLOSE").alias("close"),
        _f("PREVCLOSE").alias("prevclose"), _f("TOTTRDQTY").cast(pl.Int64).alias("qty"),
        _f("TOTTRDVAL").alias("value"),
        (_f("TOTALTRADES").cast(pl.Int64) if "TOTALTRADES" in df.columns else pl.lit(None, pl.Int64)).alias("trades"),
    ).cast(SCHEMA)


def run(start: date, end: date, pause: float = 0.3) -> None:
    bhavcopy.run(start, end, pause, manifest=MANIFEST, url=url_for, parser=parse, out=ROOT)


def load(start: date | None = None, end: date | None = None) -> pl.DataFrame:
    lf = pl.scan_parquet(str(ROOT / "year=*" / "*.parquet"))
    if start:
        lf = lf.filter(pl.col("date") >= start)
    if end:
        lf = lf.filter(pl.col("date") <= end)
    return lf.collect()


if __name__ == "__main__":
    s = date.fromisoformat(sys.argv[1])
    e = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    run(s, e)
