"""Data-quality checks + coverage report for the bhavcopy Parquet store (Phase 2).

Run: uv run python -m research.quality   -> prints and writes data/bhavcopy/coverage_report.txt
Checks: missing days (vs manifest), zero/stale prices, put-call parity, strike-grid gaps, expiry weekday.
"""
from __future__ import annotations

import sys
from datetime import date

import polars as pl

from research import bhavcopy
from research.reference import expected_weekday, expiry_weekday_by_year

NEAR_PCT = 0.05  # "near the money" band for grid / parity checks


def missing_days(df: pl.DataFrame) -> list[str]:
    """Weekdays absent from both the stored data and the manifest's holiday list (i.e. download gaps)."""
    man = bhavcopy._load_manifest()
    have = set(df["date"].unique().to_list())
    out = []
    for k, st in man.items():
        d = date.fromisoformat(k)
        if st == "error" or (st == "ok" and d not in have):
            out.append(k)
    return out


def front_chain(df: pl.DataFrame, min_dte: int = 3, max_dte: int = 45) -> pl.DataFrame:
    """Rows with dte in [min_dte, max_dte], plus implied forward from put-call parity per (date, expiry, strike)."""
    f = df.with_columns(dte=(pl.col("expiry") - pl.col("date")).dt.total_days()).filter(
        pl.col("dte").is_between(min_dte, max_dte))
    ce = f.filter(pl.col("opt_type") == "CE").select("date", "expiry", "strike", "dte", ce="settle", ce_c="contracts")
    pe = f.filter(pl.col("opt_type") == "PE").select("date", "expiry", "strike", pe="settle", pe_c="contracts")
    return ce.join(pe, on=["date", "expiry", "strike"]).with_columns(fwd=pl.col("strike") + pl.col("ce") - pl.col("pe"))


def parity_report(chain: pl.DataFrame) -> pl.DataFrame:
    """Per (date, expiry): median implied forward (from 5 strikes nearest where |ce-pe| is smallest) and the
    max deviation of those 5 forwards from it. Large deviation => bad price in the near-ATM strikes."""
    ranked = chain.with_columns(atm_rank=(pl.col("ce") - pl.col("pe")).abs().rank("ordinal").over(["date", "expiry"]))
    atm = ranked.filter(pl.col("atm_rank") <= 5)
    return atm.group_by(["date", "expiry"]).agg(
        fwd=pl.col("fwd").median(), dev=(pl.col("fwd") - pl.col("fwd").median()).abs().max())


def grid_gaps(chain: pl.DataFrame, fwd: pl.DataFrame) -> pl.DataFrame:
    """Missing 50-pt strikes within +-NEAR_PCT of the forward, per (date, expiry), nearest 2 expiries only."""
    j = chain.join(fwd.select("date", "expiry", f="fwd"), on=["date", "expiry"])
    j = j.filter((pl.col("strike") - pl.col("f")).abs() <= NEAR_PCT * pl.col("f"))
    g = j.group_by(["date", "expiry"]).agg(n=pl.len(), lo=pl.col("strike").min(), hi=pl.col("strike").max())
    return g.with_columns(expected=((pl.col("hi") - pl.col("lo")) / 50 + 1).round(0).cast(pl.Int64)).filter(
        pl.col("n") < pl.col("expected"))


def report(df: pl.DataFrame) -> str:
    L: list[str] = []
    ok = df["date"].n_unique()
    man = bhavcopy._load_manifest()
    hol = sum(1 for v in man.values() if v == "holiday")
    L.append(f"COVERAGE {df['date'].min()} .. {df['date'].max()}: {ok} trading days stored, "
             f"{hol} non-trading days (404), rows={df.height:,}")
    L.append("rows by year: " + ", ".join(f"{y}:{n:,}" for y, n in
             df.group_by(df["date"].dt.year().alias("y")).len().sort("y").iter_rows()))
    L.append(f"missing/error days: {missing_days(df) or 'none'}")
    # weekdays per year sanity: ~245-250 trading days
    L.append("trading days/year: " + ", ".join(f"{y}:{n}" for y, n in
             df.group_by(df["date"].dt.year().alias("y")).agg(pl.col("date").n_unique()).sort("y").iter_rows()))

    # zero / stale
    z = df.filter((pl.col("settle") <= 0) | pl.col("settle").is_null())
    L.append(f"settle<=0 or null rows: {z.height:,} ({z.height / df.height:.2%}); with oi>0: {z.filter(pl.col('oi') > 0).height:,}")
    nz = df.filter(pl.col("contracts") > 0)
    L.append(f"traded rows (contracts>0): {nz.height:,} ({nz.height / df.height:.1%}); close==0 among traded: "
             f"{nz.filter(pl.col('close') <= 0).height}")
    stale = (df.sort("date").with_columns(prev=pl.col("settle").shift(1).over(["expiry", "strike", "opt_type"]))
             .filter((pl.col("contracts") > 100) & (pl.col("settle") == pl.col("prev"))))
    L.append(f"stale (liquid rows, contracts>100, settle unchanged vs previous day): {stale.height:,}")

    # expiry weekday
    ex = df.select("expiry").unique().with_columns(wd=pl.col("expiry").dt.weekday())
    wk = ex.filter(pl.col("wd") != pl.Series([expected_weekday(e) for e in ex["expiry"]]))
    L.append(f"expiries not on the expected weekday (holiday shifts expected, a few/yr): {wk.height} of {ex.height}")
    L.append("expiry weekday counts by year (Mon=1):\n" + str(expiry_weekday_by_year(df)))

    # parity + grid on front expiries
    ch = front_chain(df)
    liquid = ch.filter((pl.col("ce_c") >= 50) & (pl.col("pe_c") >= 50))  # thin strikes carry NSE-model settle, noisy
    par = parity_report(liquid)
    bad = par.filter(pl.col("dev") > 15)
    L.append(f"put-call parity (ATM-5 forwards, pairs with >=50 contracts each leg): {par.height:,} date/expiry pairs; "
             f"dev>15pts: {bad.height} ({bad.height / max(par.height, 1):.2%}); median dev {par['dev'].median():.2f}")
    byb = (par.with_columns(b=((pl.col("expiry") - pl.col("date")).dt.total_days() // 10) * 10)
           .group_by("b").agg(bad=(pl.col("dev") > 15).mean(), n=pl.len()).sort("b"))
    L.append("parity dev>15pts share by DTE bucket (start day): " + ", ".join(f"{b}+:{x:.1%}(n={n})" for b, x, n in byb.iter_rows()))
    gaps = grid_gaps(ch, par)
    L.append(f"strike-grid gaps within +-{NEAR_PCT:.0%} of forward (dte 3-45): {gaps.height:,} of {par.height:,} date/expiry pairs")
    L.append("worst parity examples:\n" + str(bad.sort("dev", descending=True).head(5)))
    return "\n".join(L)


if __name__ == "__main__":
    text = report(bhavcopy.load())
    out = bhavcopy.ROOT / "coverage_report.txt"
    out.write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)
