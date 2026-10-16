"""NSE F&O bhavcopy -> partitioned Parquet of Nifty index options (Phase 2).

Two archive formats, both served from nsearchives.nseindia.com (verified 2026-10-16):
  * legacy  .../content/historical/DERIVATIVES/<YYYY>/<MON>/fo<DDMONYYYY>bhav.csv.zip
            last published trading day: 2024-07-05 (404 from 2024-07-08)
  * UDiFF   .../content/fo/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip
            available from at least 2024-06-28 (overlaps legacy); first UDiFF-only day 2024-07-08
For overlap days legacy is used (it is the archive the pre-2024 history came from); the
two formats were checked against each other once on 2024-07-05 (1,634 rows, 0 mismatches; see ISS-R8).

Layout: data/bhavcopy/nifty_options/year=YYYY/<YYYY-MM-DD>.parquet and
data/bhavcopy/manifest.csv (date,status) where status is ok | holiday (404) | error.
Bhavcopy has no bid/ask: execution cost is modelled explicitly downstream.

CLI: uv run python -m research.bhavcopy 2019-01-01 [end-date]   (resumable)
"""
from __future__ import annotations

import io
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import requests

ROOT = Path("data/bhavcopy")
OUT = ROOT / "nifty_options"
MANIFEST = ROOT / "manifest.csv"
BASE = "https://nsearchives.nseindia.com/content"
LEGACY_LAST = date(2024, 7, 5)
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36"}

SCHEMA = {
    "date": pl.Date, "expiry": pl.Date, "strike": pl.Float64, "opt_type": pl.Utf8,
    "open": pl.Float64, "high": pl.Float64, "low": pl.Float64, "close": pl.Float64,
    "settle": pl.Float64, "contracts": pl.Int64, "oi": pl.Int64,
    "underlying": pl.Float64, "lot_size": pl.Int64,  # last two: UDiFF only, else null
}


def url_for(d: date) -> str:
    if d <= LEGACY_LAST:
        mon = d.strftime("%b").upper()  # %b is locale-dependent; fine for C/English
        return f"{BASE}/historical/DERIVATIVES/{d.year}/{mon}/fo{d.day:02d}{mon}{d.year}bhav.csv.zip"
    return f"{BASE}/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def parse(raw_csv: bytes, d: date) -> pl.DataFrame:
    """Normalise one day's csv (either format, auto-detected from header) to SCHEMA."""
    df = pl.read_csv(io.BytesIO(raw_csv), infer_schema_length=0)
    if "TckrSymb" in df.columns:  # UDiFF
        o = df.filter((pl.col("TckrSymb") == "NIFTY") & (pl.col("FinInstrmTp") == "IDO"))
        return o.select(
            pl.lit(d).alias("date"),
            pl.col("XpryDt").str.to_date("%Y-%m-%d").alias("expiry"),
            pl.col("StrkPric").cast(pl.Float64, strict=False).alias("strike"),
            pl.col("OptnTp").alias("opt_type"),
            pl.col("OpnPric").cast(pl.Float64, strict=False).alias("open"),
            pl.col("HghPric").cast(pl.Float64, strict=False).alias("high"),
            pl.col("LwPric").cast(pl.Float64, strict=False).alias("low"),
            pl.col("ClsPric").cast(pl.Float64, strict=False).alias("close"),
            pl.col("SttlmPric").cast(pl.Float64, strict=False).alias("settle"),
            pl.col("TtlTradgVol").cast(pl.Float64, strict=False).cast(pl.Int64).alias("contracts"),
            pl.col("OpnIntrst").cast(pl.Float64, strict=False).cast(pl.Int64).alias("oi"),
            pl.col("UndrlygPric").cast(pl.Float64, strict=False).alias("underlying"),
            pl.col("NewBrdLotQty").cast(pl.Float64, strict=False).cast(pl.Int64).alias("lot_size"),
        ).select(list(SCHEMA)).cast(SCHEMA)
    df = df.rename({c: c.strip() for c in df.columns})
    o = df.filter((pl.col("SYMBOL") == "NIFTY") & (pl.col("INSTRUMENT") == "OPTIDX"))
    return o.select(
        pl.lit(d).alias("date"),
        pl.col("EXPIRY_DT").str.to_date("%d-%b-%Y").alias("expiry"),
        pl.col("STRIKE_PR").cast(pl.Float64, strict=False).alias("strike"),
        pl.col("OPTION_TYP").alias("opt_type"),
        pl.col("OPEN").cast(pl.Float64, strict=False).alias("open"),
        pl.col("HIGH").cast(pl.Float64, strict=False).alias("high"),
        pl.col("LOW").cast(pl.Float64, strict=False).alias("low"),
        pl.col("CLOSE").cast(pl.Float64, strict=False).alias("close"),
        pl.col("SETTLE_PR").cast(pl.Float64, strict=False).alias("settle"),
        pl.col("CONTRACTS").cast(pl.Float64, strict=False).cast(pl.Int64).alias("contracts"),
        pl.col("OPEN_INT").cast(pl.Float64, strict=False).cast(pl.Int64).alias("oi"),
        pl.lit(None, dtype=pl.Float64).alias("underlying"),
        pl.lit(None, dtype=pl.Int64).alias("lot_size"),
    ).cast(SCHEMA)


def fetch_day(d: date, session: requests.Session) -> str:
    """Download+store one day. Returns 'ok' | 'holiday' | 'error'."""
    for attempt in range(3):
        try:
            r = session.get(url_for(d), headers=_HEADERS, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 404:
            # ponytail: a 404 in the last 2 days may just be an unpublished file, so don't cache it as a holiday
            return "error" if d >= date.today() - timedelta(days=2) else "holiday"
        if r.status_code != 200 or not r.content.startswith(b"PK"):
            time.sleep(2 * (attempt + 1))
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                df = parse(z.read(z.namelist()[0]), d)
        except zipfile.BadZipFile:
            time.sleep(2 * (attempt + 1))
            continue
        if df.is_empty():
            return "error"
        path = OUT / f"year={d.year}" / f"{d:%Y-%m-%d}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        return "ok"
    return "error"


def _load_manifest() -> dict[str, str]:
    if not MANIFEST.exists():
        return {}
    return dict(line.split(",") for line in MANIFEST.read_text().split()[1:])


def run(start: date, end: date, pause: float = 0.3) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    done = _load_manifest()
    sess = requests.Session()
    d, n = start, 0
    while d <= end:
        key = f"{d:%Y-%m-%d}"
        # weekends included: special sessions (Budget Saturdays, Muhurat) are published; 404 -> holiday
        if done.get(key) not in ("ok", "holiday"):
            done[key] = fetch_day(d, sess)
            time.sleep(pause)
            n += 1
            if n % 50 == 0:
                _save(done)
                print(key, flush=True)
        d += timedelta(days=1)
    _save(done)


def _save(done: dict[str, str]) -> None:
    MANIFEST.write_text("date,status\n" + "\n".join(f"{k},{v}" for k, v in sorted(done.items())) + "\n")


def load(start: date | None = None, end: date | None = None) -> pl.DataFrame:
    """All stored option rows in [start, end] (inclusive)."""
    lf = pl.scan_parquet(str(OUT / "year=*" / "*.parquet"))
    if start:
        lf = lf.filter(pl.col("date") >= start)
    if end:
        lf = lf.filter(pl.col("date") <= end)
    return lf.collect()


if __name__ == "__main__":
    s = date.fromisoformat(sys.argv[1])
    e = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    run(s, e)
