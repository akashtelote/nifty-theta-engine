"""Adversarial scenario harness for the Nifty put credit spread engine.

`run_pcs_backtest` already prices, sizes, and floors max loss correctly. What it
has never been shown is a path that *gaps*: `synthetic_spot_path` is plain GBM
with VIX clipped at 35, so it structurally cannot produce the one event that
actually kills a short put spread — an overnight jump through both strikes. The
real `^NSEI` series used elsewhere starts 2022-01, which excludes COVID-2020,
the only genuine tail in recent Indian equity history.

So this module changes no engine code. It only builds the paths the engine has
never seen and runs the unmodified backtest against them.

    uv run python stress.py                 # scenario table
    uv run python stress.py --sweeps        # + slippage and capital sweeps
    uv run python stress.py --scenario covid_crash --verbose

Every scenario opens with a benign run-up long enough to populate the 252-day
IVR window and the 50-day SMA, because the entry gates need history and because
that is how crashes actually arrive: after a calm bull market, not during one.
"""

from __future__ import annotations

import argparse
import contextlib
import math
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Callable

import numpy as np
import polars as pl

import backtest
from backtest import PCSParams, run_pcs_backtest


@contextlib.contextmanager
def capital_ceiling(rupees: float):
    """Temporarily raise the ceiling `run_pcs_backtest` sizes against.

    `backtest` binds MAX_CAPITAL at import from config.settings, and sizing uses
    `min(equity, MAX_CAPITAL)`. Without patching it, asking for a ₹200k run
    returns a ₹50k result wearing a ₹200k label — the sweep would silently
    "prove" that extra capital changes nothing.
    """
    original = backtest.MAX_CAPITAL
    backtest.MAX_CAPITAL = rupees
    try:
        yield
    finally:
        backtest.MAX_CAPITAL = original

# ---------------------------------------------------------------- path building

# Long enough to fill the IVR lookback (252) and the SMA50 before anything trades.
# Must stay a multiple of 5 so weekday alignment is predictable: starting on a
# Monday, index 320 is also a Monday, which is what lets a scenario place an
# entry on a known Friday and land a gap on the Monday after it.
WARMUP_DAYS = 320

# The warmup must place ZERO trades: it exists only to fill the 252-day IVR window
# and the SMA50. An earlier version traded through warmup, bled past the funding
# cliff before any shock landed, and made all ten scenarios return the same dead
# account — every "result" was the identical warmup, not the scenario.
#
# The lever is the IVR gate, NOT credit/width. Credit is not vol-sensitive here:
# `_select_strikes` walks down the band until c/w clears 0.15, so at low vol it
# simply picks a strike nearer spot and still finds ~17 points. What does block is
# IVR — current VIX must sit at or above the 30th percentile of its own trailing
# window. So the warmup decays VIX from 22 to 10: current is always near the floor
# of its own history, and every entry is gated out. `test_stress.py` asserts this
# holds rather than trusting it.
# Starts ABOVE vix_max (22) on purpose. The IVR gate needs a populated trailing
# window to block anything, so the first few Fridays of a fresh path sail through
# it — percentile of one sample against itself is 100. The `vix > vix_max` check
# is the first line of `_select_strikes` and reads no history at all, so the decay
# begins at 26 and only crosses 22 around day 80, by which point the SMA50 and a
# real IVR window both exist and take over the blocking.
WARMUP_VIX_START = 26.0
WARMUP_VIX_END = 10.0

# VIX during the live window: above the warmup's trailing percentile, below vix_max.
TRADE_VIX = 17.0


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _warmup(n: int = WARMUP_DAYS, start_spot: float = 22000.0, seed: int = 7) -> list[tuple[float, float]]:
    """Gentle uptrend on a monotonically decaying VIX: fills history, enters nothing.

    The decay is what keeps entries gated (see WARMUP_VIX_START above) — current
    VIX stays pinned near the bottom of its own trailing distribution throughout.
    """
    rng = np.random.default_rng(seed)
    rows, spot = [], start_spot
    for i in range(n):
        # Linear decay plus small noise. Noise stays well under the per-day decay
        # step ((22-10)/320 = 0.0375) so the series is effectively monotone: a
        # noisier VIX lets an early bump clear the 30th percentile of a still-short
        # trailing window, which is exactly how three entries leaked in before.
        vix = WARMUP_VIX_START + (WARMUP_VIX_END - WARMUP_VIX_START) * (i / n) + rng.normal(0, 0.02)
        vix = float(np.clip(vix, 8.0, 23.0))
        # Deliberately smooth: quoted VIX drives option pricing, but the warmup's
        # realised path only needs to end above its own SMA50 with a predictable
        # spot level. Using VIX as realised vol made the terminal spot a coin flip
        # (seed 7 landed -37%), and every downstream strike level inherited it.
        spot *= math.exp(0.10 / 252.0 + 0.005 * rng.normal())
        rows.append((float(spot), vix))
    return rows


def _frame(rows: list[tuple[float, float]], start: date = date(2021, 1, 4)) -> pl.DataFrame:
    dates = _weekdays(start, len(rows))
    return pl.DataFrame(
        {
            "Date": dates,
            "Spot_Price": [r[0] for r in rows],
            "VIX": [r[1] for r in rows],
        }
    )


def _drift(
    rows: list[tuple[float, float]],
    days: int,
    daily: float,
    vix: float,
    seed: int = 3,
    noise: float = 0.002,
) -> None:
    """Append `days` sessions moving `daily` per session, VIX easing toward `vix`."""
    rng = np.random.default_rng(seed)
    spot, cur_vix = rows[-1]
    for _ in range(days):
        spot *= 1.0 + daily + rng.normal(0, noise)
        cur_vix += 0.34 * (vix - cur_vix) + rng.normal(0, 0.3)
        rows.append((float(spot), float(np.clip(cur_vix, 8.0, 90.0))))


def _shock(rows: list[tuple[float, float]], pct: float, vix_to: float) -> None:
    """One session that gaps `pct` (negative = down) and reprices vol."""
    spot, _ = rows[-1]
    rows.append((float(spot * (1.0 + pct)), float(vix_to)))


def _gap_cycles(pct: float, shock_vix: float, cycles: int = 10) -> pl.DataFrame:
    """Warmup, then repeated: one tradeable week (entry fires Friday), gap on the
    following Monday, then recovery. 15 days per cycle keeps Friday alignment.

    A gap over the weekend is the honest version of this risk. The engine only
    ever sees a daily close, so an overnight move is exactly the case where the
    stop-loss cannot act before the damage is done.
    """
    rows = _warmup()
    for i in range(cycles):
        _drift(rows, 5, 0.0008, TRADE_VIX, seed=i, noise=0.0015)   # Mon-Fri: entry on Fri
        _shock(rows, pct, shock_vix)                                # Mon: the gap
        # Recovery must actually clear the SMA50 again, otherwise the trend gate
        # blocks every later cycle and a 30-cycle scenario silently measures one
        # single gap. Sized to roughly undo the shock: 24 sessions at +0.3%/day.
        _drift(rows, 24, abs(pct) / 20.0, TRADE_VIX, seed=100 + i, noise=0.0015)
    return _frame(rows)


# ------------------------------------------------------------------- scenarios


@dataclass
class Scenario:
    name: str
    build: Callable[[], pl.DataFrame]
    note: str


def _calm_bull() -> pl.DataFrame:
    """Control: benign uptrend at tradeable vol. Whatever this loses is the
    strategy's own cost of doing business, not a tail event — every other
    scenario should be read as a delta against this one."""
    rows = _warmup()
    _drift(rows, 260, 0.0008, TRADE_VIX, seed=5, noise=0.0035)
    return _frame(rows)


def _gap_between_strikes() -> pl.DataFrame:
    """-2% weekend gaps: spot lands between short and long strike.

    The short sits ~1-3% OTM with the hedge 100 points (~0.45%) below, so 2% puts
    price inside the spread — loss is real but the hedge has not yet capped it.
    """
    return _gap_cycles(-0.020, 26.0)


def _gap_through_hedge() -> pl.DataFrame:
    """-6% weekend gaps clean through the long strike → structural max loss.

    The stop-loss cannot save this: the engine sees only daily closes, so by the
    time it can act price is already past the hedge. The hedge is the only thing
    that bounds it, which is exactly what this scenario is here to verify.
    """
    return _gap_cycles(-0.060, 38.0)


def _black_swan() -> pl.DataFrame:
    """Single -20% session with vol to 80 — the once-a-decade event."""
    rows = _warmup()
    _drift(rows, 20, 0.0009, TRADE_VIX, seed=8, noise=0.0015)
    _shock(rows, -0.20, 80.0)
    # Deliberately short tail. A long favourable recovery would bury the event
    # under post-crash winners and report the crash as profitable.
    _drift(rows, 30, 0.0012, 30.0, seed=9)
    return _frame(rows)


def _covid_crash() -> pl.DataFrame:
    """COVID-2020 shape: -35% over ~25 sessions, VIX to 85, then a V recovery.

    The path the live `^NSEI` series (starting 2022-01) has never contained.
    """
    rows = _warmup()
    _drift(rows, 25, 0.0010, TRADE_VIX, seed=10, noise=0.0015)
    _drift(rows, 25, -0.017, 85.0, seed=11, noise=0.010)   # the collapse
    _drift(rows, 40, 0.0000, 45.0, seed=12, noise=0.012)   # elevated-vol chop
    # Tail trimmed to 45 sessions. At 140 the V-recovery produced 15 winners
    # against one crash loss and reported COVID as PF 5.18 — true of that path,
    # and completely useless as a stress result.
    _drift(rows, 45, 0.0018, 22.0, seed=13)
    return _frame(rows)


def _vol_spike_only() -> pl.DataFrame:
    """VIX 17 → 45 with spot roughly flat: no directional damage, pure mark-to-market.

    Tests whether the stop harvests losses on positions that were never actually
    in danger — `ctc >= 2× credit` can trip on repriced vol alone.
    """
    rows = _warmup()
    for i in range(9):
        _drift(rows, 15, 0.0004, TRADE_VIX, seed=300 + i, noise=0.0012)
        _drift(rows, 10, -0.0004, 45.0, seed=400 + i, noise=0.0015)
    return _frame(rows)


def _grind_down() -> pl.DataFrame:
    """Slow -0.4%/session bleed. Delta-manage and the SMA50 trend gate should both
    engage; verifies the bot stops re-entering into an established downtrend."""
    rows = _warmup()
    # No recovery tail: with one appended, the trend gate blocked the entire grind
    # and all five recorded trades came from the rebound — a downtrend scenario
    # that reported 100% wins and a worst trade of zero.
    _drift(rows, 120, -0.004, 24.0, seed=17, noise=0.003)
    return _frame(rows)


def _whipsaw() -> pl.DataFrame:
    """Oscillation across the short strike: the stop fires, then price recovers.

    The worst *sequence* risk for a mechanical stop — repeatedly realising a loss
    immediately before the position would have come back on its own.
    """
    rows = _warmup()
    rng = np.random.default_rng(23)
    spot, _ = rows[-1]
    for i in range(240):
        spot *= 1.0 + 0.020 * math.sin(i / 3.5) + rng.normal(0, 0.003)
        vix = float(np.clip(TRADE_VIX + 5.0 * abs(math.sin(i / 3.5)) + rng.normal(0, 0.6), 12.0, 34.0))
        rows.append((float(spot), vix))
    return _frame(rows)


def _dead_vol() -> pl.DataFrame:
    """VIX decaying 10 -> 8 in a rising market. Expected: near-zero entries.

    Note the mechanism is the IVR gate, not credit/width — `_select_strikes` is
    not vol-sensitive at the low end, since it walks down the band until c/w
    clears 0.15 and at low vol simply picks a strike nearer spot. An earlier
    version of this scenario claimed the credit gate did the blocking, held VIX
    flat at 9.5, and traded six times.
    """
    rows = _warmup()
    _drift(rows, 220, 0.0004, 8.0, seed=29)
    return _frame(rows)


def _rate_shock_repeat() -> pl.DataFrame:
    """A -6% weekend gap every cycle for ~30 cycles — a deliberately unfair
    regime, used to find the ruin floor and the funding cliff."""
    return _gap_cycles(-0.060, 40.0, cycles=30)


SCENARIOS: list[Scenario] = [
    Scenario("calm_bull", _calm_bull, "control — benign uptrend"),
    Scenario("gap_between_strikes", _gap_between_strikes, "-2% gaps, land inside the spread"),
    Scenario("gap_through_hedge", _gap_through_hedge, "-6% gaps, straight through the hedge"),
    Scenario("black_swan", _black_swan, "single -20% day, VIX 80"),
    Scenario("covid_crash", _covid_crash, "-35% over 25 sessions, VIX 85"),
    Scenario("vol_spike_only", _vol_spike_only, "VIX 15->45, spot flat"),
    Scenario("grind_down", _grind_down, "-0.4%/session bleed"),
    Scenario("whipsaw", _whipsaw, "oscillation across the short strike"),
    Scenario("dead_vol", _dead_vol, "VIX decaying 10->8, IVR gate throttles entries"),
    Scenario("rate_shock_repeat", _rate_shock_repeat, "-6% gap every 8 weeks, 2 years"),
]


# --------------------------------------------------------------------- metrics


def funding_cliff(params: PCSParams) -> float:
    """Equity below which `floor(budget / width×lot)` hits 0 and the bot stops.

    Not reported by BacktestResult: an account that bricks itself simply stops
    producing trades, so its drawdown *flatlines* and `ruin_proxy` reads it as
    safe. This is the metric that distinguishes "survived" from "died quietly".
    """
    return (params.hedge_width * params.lot_size) / params.allocation_pct


def worst_case_per_lot(params: PCSParams) -> float:
    """Structural floor on a single trade: (width - credit) × lot × lots."""
    return params.hedge_width * params.lot_size


def analyse(res, params: PCSParams) -> dict:
    """Derive tail metrics from the trade list — no engine change needed."""
    cliff = funding_cliff(params)
    equity = params.initial_capital
    bricked_after = None
    for i, t in enumerate(res.trades, start=1):
        equity += t.pnl
        if equity < cliff and bricked_after is None:
            bricked_after = i
    losses = [t.pnl for t in res.trades if t.pnl < 0]
    return {
        "trades": res.total_trades,
        "win_rate": res.win_rate,
        "pf": res.profit_factor,
        "total_pnl": res.total_pnl,
        "worst_trade": min(losses) if losses else 0.0,
        "max_dd": res.max_drawdown,
        "ruin": res.ruin_proxy,
        "final_equity": equity,
        "bricked_after": bricked_after,
        "cliff": cliff,
        "mix": res.exit_reason_mix,
    }


def run_scenario(sc: Scenario, params: PCSParams) -> dict:
    res = run_pcs_backtest(sc.build(), params)
    return analyse(res, params)


# ---------------------------------------------------------------------- report


def _row(name: str, m: dict) -> str:
    brick = f"#{m['bricked_after']}" if m["bricked_after"] else "-"
    return (
        f"{name:<22} {m['trades']:>4}  {m['win_rate']:>5.1f}%  {m['pf']:>5.2f} "
        f"{m['total_pnl']:>10,.0f} {m['worst_trade']:>10,.0f} {m['max_dd']:>10,.0f} "
        f"{m['ruin']:>7.1%}  {brick:>5}"
    )


HEADER = (
    f"{'scenario':<22} {'n':>4}  {'win':>6}  {'PF':>5} "
    f"{'net P&L':>10} {'worst':>10} {'max DD':>10} {'ruin':>7}  {'brick':>5}"
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", help="run only this scenario")
    ap.add_argument("--sweeps", action="store_true", help="also run slippage and capital sweeps")
    ap.add_argument("--slippage", type=float, default=None, help="override slippage points/side")
    ap.add_argument("--verbose", action="store_true", help="print exit-reason mix")
    args = ap.parse_args()

    base = PCSParams()
    if args.slippage is not None:
        base = replace(base, slippage_points=args.slippage)

    chosen = [s for s in SCENARIOS if not args.scenario or s.name == args.scenario]
    if not chosen:
        raise SystemExit(f"unknown scenario. options: {', '.join(s.name for s in SCENARIOS)}")

    print(
        f"\ncapital INR {base.initial_capital:,.0f} | allocation {base.allocation_pct:.0%} | "
        f"slippage {base.slippage_points}/side | lot {base.lot_size} | width {base.hedge_width:.0f}"
    )
    print(f"one lot needs INR {worst_case_per_lot(base):,.0f} | funding cliff INR {funding_cliff(base):,.0f}")
    print(f"\n{HEADER}\n{'-' * len(HEADER)}")
    for sc in chosen:
        m = run_scenario(sc, base)
        print(_row(sc.name, m))
        if args.verbose:
            print(f"{'':<22} {sc.note} | exits: {m['mix']}")

    if args.sweeps:
        print("\n\nSLIPPAGE SENSITIVITY (gap_through_hedge + covid_crash + calm_bull)")
        print(f"{HEADER}\n{'-' * len(HEADER)}")
        for slip in (0.0, 0.4, 1.0, 1.5, 2.5):
            p = replace(base, slippage_points=slip)
            for sc in SCENARIOS:
                if sc.name in ("gap_through_hedge", "covid_crash", "calm_bull"):
                    print(_row(f"{sc.name[:14]}@{slip}", run_scenario(sc, p)))

        print("\n\nCAPITAL / ALLOCATION (covid_crash — the case that decides sizing)")
        print(f"{HEADER}\n{'-' * len(HEADER)}")
        covid = next(s for s in SCENARIOS if s.name == "covid_crash")
        for cap, alloc in ((50_000, 0.15), (50_000, 0.25), (200_000, 0.15), (200_000, 0.25)):
            p = replace(base, initial_capital=float(cap), allocation_pct=alloc)
            lots = math.floor(cap * alloc / worst_case_per_lot(p))
            with capital_ceiling(float(cap)):
                m = run_scenario(covid, p)
            print(_row(f"{cap // 1000}k @{alloc:.0%} ({lots} lot)", m))


if __name__ == "__main__":
    main()
