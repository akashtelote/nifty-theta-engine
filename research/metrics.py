"""Performance metrics for research.engine trades (Phase 3). Pure functions, tested on synthetic trades."""
from __future__ import annotations

from datetime import date

import numpy as np

TAX_RATE = 0.30  # plan: 30% slab on F&O business income, flat per financial year, no loss carry-forward (conservative)


def profit_factor(pnl: list[float]) -> float:
    g, l = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x < 0)
    return float("inf") if l == 0 and g > 0 else (g / l if l else 0.0)


def bootstrap_ci(pnl: list[float], stat, n: int = 5000, seed: int = 12345, alpha: float = 0.05) -> tuple[float, float]:
    """Percentile bootstrap CI (i.i.d. trades) of stat(list). Seed fixed so reruns are identical."""
    if len(pnl) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    a = np.asarray(pnl)
    vals = [stat(list(a[rng.integers(0, len(a), len(a))])) for _ in range(n)]
    vals = [v for v in vals if np.isfinite(v)]
    if not vals:  # e.g. all-winner sample: PF infinite in every resample
        return float("nan"), float("nan")
    return float(np.percentile(vals, 100 * alpha / 2)), float(np.percentile(vals, 100 * (1 - alpha / 2)))


def max_drawdown(trades, equity0: float) -> float:
    """Max peak-to-trough fall (fraction of peak) incl. each trade's worst intratrade mid mark."""
    eq = peak = equity0
    worst = 0.0
    for t in trades:
        worst = max(worst, (peak - (eq + t.worst_pnl)) / peak)  # worst_pnl is <= 0, before fees
        eq += t.pnl
        peak = max(peak, eq)
        worst = max(worst, (peak - eq) / peak)
    return worst


def _fy(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def after_tax_pnl(trades) -> float:
    by: dict[int, float] = {}
    for t in trades:
        by[_fy(t.exit)] = by.get(_fy(t.exit), 0.0) + t.pnl
    return sum(v - TAX_RATE * max(v, 0.0) for v in by.values())


def worst_period(trades, key) -> float:
    by: dict = {}
    for t in trades:
        by[key(t.exit)] = by.get(key(t.exit), 0.0) + t.pnl
    return min(by.values()) if by else 0.0


def _cagr(e0: float, e1: float, yrs: float) -> float:
    return (e1 / e0) ** (1 / yrs) - 1 if e1 > 0 and yrs > 0 else -1.0


def summarize(trades, equity0: float, start: date, end: date) -> dict:
    pnl = [t.pnl for t in trades]
    if not pnl:
        return {"n": 0}
    final = equity0 + sum(pnl)
    yrs = (end - start).days / 365.25
    exp_lo, exp_hi = bootstrap_ci(pnl, lambda x: float(np.mean(x)))
    pf_lo, pf_hi = bootstrap_ci(pnl, profit_factor)
    return {
        "n": len(pnl), "win_rate": sum(x > 0 for x in pnl) / len(pnl),
        "pf": profit_factor(pnl), "pf_ci": (pf_lo, pf_hi),
        "expectancy": float(np.mean(pnl)), "expectancy_ci": (exp_lo, exp_hi),
        "total_pnl": sum(pnl), "cagr": _cagr(equity0, final, yrs),
        "max_dd": max_drawdown(trades, equity0),
        "worst_trade": min(pnl), "worst_week": worst_period(trades, lambda d: d.isocalendar()[:2]),
        "worst_month": worst_period(trades, lambda d: (d.year, d.month)),
        "return_on_margin": sum(pnl) / sum(t.max_loss for t in trades) if trades else 0.0,
        "after_tax_pnl": after_tax_pnl(trades), "after_tax_cagr": _cagr(equity0, equity0 + after_tax_pnl(trades), yrs),
        "worst_trade_pct": min(pnl) / equity0, "worst_week_pct": worst_period(trades, lambda d: d.isocalendar()[:2]) / equity0,
        "fees": sum(t.fees for t in trades),
    }


def window(trades, start: date, end: date) -> list:
    """Trades whose position was open at any time in [start, end] (for stress windows)."""
    return [t for t in trades if t.entry <= end and t.exit >= start]


def benchmark_cagr(prices: list[tuple[date, float]]) -> float:
    (d0, p0), (d1, p1) = prices[0], prices[-1]
    return (p1 / p0) ** (365.25 / (d1 - d0).days) - 1
