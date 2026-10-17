"""EOD implied-vol surface from bhavcopy `close` (Phase A2 of docs/plans/20261017-next-hypotheses-plan.md).

Black-76 with r=0 against the close-parity forward (engine.forward(col="close")), so no rate or dividend input is
needed. Time to expiry = calendar days / 365 (quote and expiry both taken at the close). Only strikes with
contracts >= MIN_CONTRACTS are used: `close` of an untraded strike is a stale or theoretical number.
"""
from __future__ import annotations

import math
from datetime import date

import polars as pl

from research.engine import _ncdf, forward

MIN_CONTRACTS = 50


def black76(f: float, k: float, t: float, v: float, typ: str) -> float:
    sd = v * math.sqrt(t)
    d1 = (math.log(f / k) + 0.5 * sd * sd) / sd
    if typ == "CE":
        return f * _ncdf(d1) - k * _ncdf(d1 - sd)
    return k * _ncdf(sd - d1) - f * _ncdf(-d1)


def delta(f: float, k: float, t: float, v: float, typ: str) -> float:
    d1 = (math.log(f / k) + 0.5 * v * v * t) / (v * math.sqrt(t))
    return _ncdf(d1) if typ == "CE" else _ncdf(d1) - 1.0


def implied_vol(price: float, f: float, k: float, t: float, typ: str) -> float | None:
    """Bisection on [1%, 300%]. None outside no-arbitrage bounds (price <= intrinsic or >= the cap)."""
    if t <= 0 or price <= 0:
        return None
    intrinsic = max(f - k, 0.0) if typ == "CE" else max(k - f, 0.0)
    cap = f if typ == "CE" else k
    if price <= intrinsic + 1e-9 or price >= cap:
        return None
    lo, hi = 0.01, 3.0
    if not black76(f, k, t, lo, typ) <= price <= black76(f, k, t, hi, typ):
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if black76(f, k, t, mid, typ) < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def expiry_row(day: pl.DataFrame, d: date, expiry: date) -> dict | None:
    """ATM straddle, ATM IV and 25-delta put/call IV for one (day, expiry); None if the chain is too thin."""
    t = (expiry - d).days / 365.0
    if t <= 0:
        return None
    f = forward(day, expiry, min_contracts=MIN_CONTRACTS, col="close")
    if f is None:
        return None
    e = day.filter((pl.col("expiry") == expiry) & (pl.col("contracts") >= MIN_CONTRACTS) & (pl.col("close") > 0))
    ce = dict(e.filter(pl.col("opt_type") == "CE").select("strike", "close").iter_rows())
    pe = dict(e.filter(pl.col("opt_type") == "PE").select("strike", "close").iter_rows())
    both = sorted(set(ce) & set(pe), key=lambda k: abs(k - f))
    if not both:
        return None
    k_atm = both[0]
    ivs = [x for x in (implied_vol(ce[k_atm], f, k_atm, t, "CE"), implied_vol(pe[k_atm], f, k_atm, t, "PE")) if x]
    if not ivs:
        return None

    def wing(quotes: dict, typ: str, otm) -> float | None:  # IV of the OTM strike whose delta is nearest 0.25
        best = None
        for k, px in quotes.items():
            if not otm(k):
                continue
            v = implied_vol(px, f, k, t, typ)
            if v:
                gap = abs(abs(delta(f, k, t, v, typ)) - 0.25)
                if best is None or gap < best[0]:
                    best = (gap, v)
        return best[1] if best and best[0] <= 0.10 else None

    return {
        "date": d, "expiry": expiry, "dte": (expiry - d).days, "fwd": f, "atm_k": k_atm,
        "straddle": ce[k_atm] + pe[k_atm], "atm_iv": sum(ivs) / len(ivs),
        "put25_iv": wing(pe, "PE", lambda k: k < f), "call25_iv": wing(ce, "CE", lambda k: k > f),
    }


def surface(df: pl.DataFrame, max_dte: int = 70) -> pl.DataFrame:
    """One row per (date, expiry) with 1 <= dte <= max_dte. df = bhavcopy.load(...) rows."""
    df = df.filter(((pl.col("expiry") - pl.col("date")).dt.total_days()).is_between(1, max_dte))
    rows = []
    for (d,), day in df.partition_by("date", as_dict=True).items():
        for ex in day["expiry"].unique().to_list():
            r = expiry_row(day, d, ex)
            if r:
                rows.append(r)
    return pl.DataFrame(rows).sort(["date", "expiry"]) if rows else pl.DataFrame()


def constant_maturity(surf: pl.DataFrame, days: int) -> pl.DataFrame:
    """ATM IV at a fixed horizon by linear interpolation in total variance (v^2 t) between the two expiries that
    bracket `days`; no extrapolation (a date without a bracket is dropped)."""
    out = []
    for (d,), g in surf.partition_by("date", as_dict=True).items():
        pts = sorted(zip(g["dte"].to_list(), g["atm_iv"].to_list()))
        below = [p for p in pts if p[0] <= days]
        above = [p for p in pts if p[0] >= days]
        if not below or not above:
            continue
        (t1, v1), (t2, v2) = below[-1], above[0]
        if t1 == t2:
            out.append({"date": d, f"iv{days}": v1})
            continue
        w = (days - t1) / (t2 - t1)
        var = (1 - w) * v1 * v1 * t1 + w * v2 * v2 * t2
        out.append({"date": d, f"iv{days}": math.sqrt(var / days)})
    return pl.DataFrame(out, schema={"date": pl.Date, f"iv{days}": pl.Float64}).sort("date")
