"""Explicit per-leg execution-cost model for bhavcopy-priced backtests (Phase 2).

Bhavcopy has no bid/ask, so every fill is the settle price moved *against* us by `slip` index points:
buys pay settle+slip, sells receive settle-slip (floored at the 0.05 tick).
Calibration (Phase 0): measured paper entry slippage was only ~0.09 pt/leg, but that is a simulated fill
against the quoted book, not a real fill, and settle is a 15:30 reference while entries are at 15:15.
So results are reported at a fixed bracket of levels rather than one calibrated number.
"""
SLIPPAGE_LEVELS = {"low": 0.25, "mid": 0.50, "high": 1.00}  # index points per leg per fill
TICK = 0.05


def fill(settle: float, side: str, slip: float) -> float:
    """Fill price for one option leg. side: 'buy' | 'sell'."""
    if side == "buy":
        return settle + slip
    if side == "sell":
        return max(settle - slip, TICK)
    raise ValueError(side)
