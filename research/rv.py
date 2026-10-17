"""Nifty index close, India VIX and realised-vol forecasts (Phase A3/A4 of docs/plans/20261017-next-hypotheses-plan.md).

Source: Yahoo (^NSEI, ^INDIAVIX via yfinance), with sessions/VIX prints Yahoo lacks patched from the NSE daily
index archive (patch_from_nse), cached to data/index/nifty_vix.parquet. Validated against the UDiFF bhavcopy
`underlying` column (validate_against_bhavcopy). Re-run fetch() after a bhavcopy download so new sessions get patched. Meant to replace the parity-forward spot
proxy for the benchmark and gap-day list (artefacts in the v2 OOS run); that rebuild is Phase C, nothing uses it yet.

RV is close-to-close (overnight gaps included, which is what a held option pays for), annualised with 252.
HAR (Corsi 2009) on daily squared returns: target = mean r^2 over the next h days, regressors = mean r^2 over the
last 1 / 5 / 22 days. Fit it on DEV dates only and apply the frozen coefficients everywhere else.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

CACHE = Path("data/index/nifty_vix.parquet")
NSE_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{}.csv"
ANN = 252


def fetch(start: str = "2010-01-01", end: str | None = None) -> pl.DataFrame:
    import yfinance as yf

    out = None
    for sym, col in (("^NSEI", "close"), ("^INDIAVIX", "vix")):
        h = yf.Ticker(sym).history(start=start, end=end, auto_adjust=False)
        f = pl.DataFrame({"date": [x.date() for x in h.index], col: h["Close"].to_list()})
        out = f if out is None else out.join(f, on="date", how="full", coalesce=True)
    out = patch_from_nse(out.sort("date").filter(pl.col("close").is_not_null()).with_columns(src=pl.lit("yahoo")))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(CACHE)
    return out


def _nse_day(d: date, session) -> tuple[float | None, float | None]:
    """(Nifty close, India VIX) from NSE's ind_close_all file; Nones where the archive lacks the file or row."""
    r = session.get(NSE_URL.format(d.strftime("%d%m%Y")), timeout=20)
    if r.status_code != 200:
        return None, None
    rows = {l.split(",")[0].strip().lower(): l.split(",") for l in r.text.splitlines()}
    nifty = rows.get("nifty 50") or rows.get("cnx nifty")
    vix = rows.get("india vix")
    return (float(nifty[5]) if nifty else None), (float(vix[5]) if vix else None)


def patch_from_nse(df: pl.DataFrame) -> pl.DataFrame:
    """Yahoo drops some NSE sessions (e.g. the 2020-02-01 budget Saturday) and some VIX prints. Fill them from the
    NSE archive for every bhavcopy trading day (manifest 'ok'); src records 'nse' / 'yahoo+nse_vix'. The archive itself
    is patchy (no files for 2011-2012, no VIX row before ~2015), so a gap it cannot fill stays a gap."""
    import requests

    from research.bhavcopy import _load_manifest

    have = dict(zip(df["date"], df["vix"]))
    want = [date.fromisoformat(d) for d, s in _load_manifest().items() if s == "ok"]
    want = [d for d in want if d not in have or have[d] is None]
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    new, vix_fill = [], {}
    for d in want:
        c, v = _nse_day(d, s)
        if d not in have and c is not None:
            new.append({"date": d, "close": c, "vix": v, "src": "nse"})
        elif d in have and v is not None:
            vix_fill[d] = v
    print(f"nse patch: {len(want)} wanted, {len(new)} sessions added, {len(vix_fill)} vix filled", file=sys.stderr)
    df = df.with_columns(
        vix=pl.coalesce("vix", pl.col("date").replace_strict(vix_fill, default=None, return_dtype=pl.Float64)),
        src=pl.when(pl.col("date").is_in(list(vix_fill))).then(pl.lit("yahoo+nse_vix")).otherwise("src"))
    return pl.concat([df, pl.DataFrame(new, schema=df.schema)]).sort("date") if new else df


def load() -> pl.DataFrame:
    """date, close, vix (VIX in vol points, e.g. 14.0), plus r = log return and r2 = r^2."""
    df = pl.read_parquet(CACHE).sort("date")
    return df.with_columns(r=pl.col("close").log().diff()).with_columns(r2=pl.col("r") ** 2)


def add_rv(df: pl.DataFrame, windows=(10, 21)) -> pl.DataFrame:
    """Trailing annualised close-to-close RV, known at that day's close."""
    return df.with_columns([(pl.col("r2").rolling_mean(w) * ANN).sqrt().alias(f"rv{w}") for w in windows])


def _har_frame(df: pl.DataFrame, h: int) -> pl.DataFrame:
    return df.with_columns(
        x1=pl.col("r2"), x5=pl.col("r2").rolling_mean(5), x22=pl.col("r2").rolling_mean(22),
        y=pl.col("r2").rolling_mean(h).shift(-h),  # realised over the NEXT h days
    )


def har_fit(df: pl.DataFrame, h: int, start: date, end: date) -> np.ndarray:
    """OLS coefficients [b0, b1, b5, b22]. Targets must end inside [start, end], so the last h days are dropped."""
    f = _har_frame(df, h).with_row_index("i")
    last = f.filter(pl.col("date") <= end)["i"].max() - h
    f = f.filter((pl.col("date") >= start) & (pl.col("i") <= last)).drop_nulls(["x1", "x5", "x22", "y"])
    x = np.column_stack([np.ones(f.height), f["x1"], f["x5"], f["x22"]])
    coef, *_ = np.linalg.lstsq(x, f["y"].to_numpy(), rcond=None)
    return coef


def har_forecast(df: pl.DataFrame, coef: np.ndarray, h: int) -> pl.DataFrame:
    """date, harvol{h} = annualised vol forecast for the next h days, known at that day's close."""
    f = _har_frame(df, h)
    var = coef[0] + coef[1] * f["x1"] + coef[2] * f["x5"] + coef[3] * f["x22"]
    return f.select("date").with_columns((var.clip(lower_bound=1e-8) * ANN).sqrt().alias(f"harvol{h}"))


def validate_against_bhavcopy(idx: pl.DataFrame, opts: pl.DataFrame) -> pl.DataFrame:
    """Per-day |Yahoo close - bhavcopy underlying| in index points (UDiFF rows only carry `underlying`)."""
    u = opts.filter(pl.col("underlying").is_not_null()).group_by("date").agg(pl.col("underlying").median())
    return u.join(idx.select("date", "close"), on="date").with_columns(
        diff=(pl.col("close") - pl.col("underlying")).abs()).sort("date")


if __name__ == "__main__":
    d = fetch(*sys.argv[1:2])
    print(d.height, d["date"].min(), d["date"].max(), "vix nulls:", d["vix"].null_count())
