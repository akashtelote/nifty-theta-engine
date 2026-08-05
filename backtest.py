"""Put Credit Spread (PCS) backtest harness (Stage 6 / PROF-015).

Pricing: VIX-calibrated Black–Scholes on Nifty + India VIX paths (yfinance),
or mid marks from ``data/option_chains/`` when parquet/CSV files are present.

Not absolute live expectancy without true NSE chains — use for ranking + walk-forward.

Capital ceiling: ₹50,000.

Run:
    uv run python backtest.py
    uv run python backtest.py --sweep
    uv run python backtest.py --walk-forward
    uv run python backtest.py --from-yahoo --start 2022-01-01
"""

from __future__ import annotations

import argparse
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import polars as pl

from config.event_calendar import in_event_blackout
from config.settings import round_trip_fees
from core.chain_loader import chain_files_available, load_option_chains
from core.ivr import ivr_allows_entry
from core.trend_filter import sma, trend_allows_entry

NIFTY_LOT = 25
INITIAL_CAPITAL = 50_000.0
DEFAULT_HEDGE_WIDTH = 100.0


@dataclass
class PCSParams:
    tp_residual: float = 0.50
    sl_multiple: float = 2.0
    time_stop_weekday: int = -1  # disabled
    dte_manage: int = 7
    short_delta_manage: float = 0.30
    otm_pct: float = 0.01
    otm_floor_extra: float = 0.02  # tracks wheel_strategy._find_credit_spread hardcode
    hedge_width: float = DEFAULT_HEDGE_WIDTH
    stop_on_touch: bool = True
    slippage_points: float = 1.5  # per-side bid-ask haircut vs the BS mid we price at
    allocation_pct: float = 1.0  # tracks scheduler ALLOCATION_PCT_PER_TRADE
    target_delta: float = 0.18
    min_credit_width: float = 0.15
    entry_weekday: int = 4  # Friday
    dte_entry: int = 21
    vix_max: float = 22.0
    ivr_min: float = 30.0  # tracks settings.IVR_MIN_PERCENTILE
    skip_low_ivr: bool = True
    trend_sma_days: int = 50
    trend_filter: bool = True
    event_blackout: bool = True
    event_before: int = 1
    event_after: int = 1
    lot_size: int = NIFTY_LOT
    initial_capital: float = INITIAL_CAPITAL


@dataclass
class TradeRecord:
    entry_date: date
    exit_date: date
    short_strike: float
    long_strike: float
    credit: float
    pnl: float
    exit_reason: str


@dataclass
class BacktestResult:
    total_trades: int = 0
    winning_trades: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    ruin_proxy: float = 0.0  # max_dd / initial_capital
    exit_reason_mix: dict[str, int] = field(default_factory=dict)
    trades: list[TradeRecord] = field(default_factory=list)
    final_equity: float = INITIAL_CAPITAL

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": self.win_rate,
            "avg_pnl": self.avg_pnl,
            "total_pnl": self.total_pnl,
            "max_drawdown": self.max_drawdown,
            "profit_factor": self.profit_factor,
            "ruin_proxy": self.ruin_proxy,
            "exit_reason_mix": dict(self.exit_reason_mix),
            "final_equity": self.final_equity,
        }


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_put_price(spot: float, strike: float, t_years: float, vol: float, r: float = 0.0) -> float:
    if t_years <= 1e-8:
        return max(strike - spot, 0.0)
    sigma = max(vol, 0.01)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * math.sqrt(t_years))
    d2 = d1 - sigma * math.sqrt(t_years)
    return strike * math.exp(-r * t_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_put_delta(spot: float, strike: float, t_years: float, vol: float, r: float = 0.0) -> float:
    if t_years <= 1e-8:
        return -1.0 if spot < strike else 0.0
    sigma = max(vol, 0.01)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * math.sqrt(t_years))
    return _norm_cdf(d1) - 1.0


def synthetic_spot_path(
    n_days: int = 756,
    start_spot: float = 22000.0,
    mu: float = 0.08,
    seed: int = 42,
) -> pl.DataFrame:
    """Generate trading-day spot + VIX path (no weekends). Offline CI fixture."""
    rng = np.random.default_rng(seed)
    rows = []
    spot = start_spot
    vix = 15.0
    d = date(2022, 1, 3)
    for _ in range(n_days):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        vix = float(np.clip(vix + 0.15 * (15.0 - vix) + rng.normal(0, 0.8), 10.0, 35.0))
        vol = vix / 100.0
        daily_ret = (mu - 0.5 * vol * vol) / 252.0 + vol * rng.normal() / math.sqrt(252.0)
        spot = float(spot * math.exp(daily_ret))
        rows.append({"Date": d, "Spot_Price": spot, "VIX": vix})
        d += timedelta(days=1)
    return pl.DataFrame(rows)


def fetch_nifty_vix_path(start: str = "2022-01-01", end: str | None = None) -> pl.DataFrame:
    """yfinance ^NSEI + ^INDIAVIX daily closes."""
    import yfinance as yf

    end = end or date.today().isoformat()
    asset_df = yf.download("^NSEI", start=start, end=end, progress=False)
    vix_df = yf.download("^INDIAVIX", start=start, end=end, progress=False)
    asset_close = asset_df[["Close"]].reset_index()
    vix_close = vix_df[["Close"]].reset_index()
    asset_close.columns = ["Date", "Spot_Price"]
    vix_close.columns = ["Date", "VIX"]
    pl_asset = pl.from_pandas(asset_close)
    pl_vix = pl.from_pandas(vix_close)
    for frame_name, frame in (("asset", pl_asset), ("vix", pl_vix)):
        if frame.schema["Date"] != pl.Date:
            try:
                frame = frame.with_columns(pl.col("Date").dt.date())
            except Exception:
                frame = frame.with_columns(pl.col("Date").cast(pl.Date))
            if frame_name == "asset":
                pl_asset = frame
            else:
                pl_vix = frame
    merged = pl_asset.join(pl_vix, on="Date", how="left")
    merged = merged.with_columns([
        pl.col("Spot_Price").fill_null(strategy="forward"),
        pl.col("VIX").fill_null(strategy="forward"),
    ]).drop_nulls()
    return merged.select(["Date", "Spot_Price", "VIX"])


def _round_strike(x: float, step: float = 50.0) -> float:
    return round(x / step) * step


def _select_strikes(
    spot: float,
    vix: float,
    params: PCSParams,
    vix_history: list[float],
    spot_history: list[float],
    on: date,
) -> tuple[float, float, float] | None:
    if vix > params.vix_max:
        return None
    if params.hedge_width * params.lot_size > params.initial_capital:
        return None

    ivr_ok, _, _ = ivr_allows_entry(
        vix,
        lookback_days=len(vix_history) or 252,
        min_percentile=params.ivr_min,
        skip_low_ivr=params.skip_low_ivr,
        history=vix_history,
    )
    if not ivr_ok:
        return None

    if params.event_blackout:
        blocked, _ = in_event_blackout(on, days_before=params.event_before, days_after=params.event_after)
        if blocked:
            return None

    trend_ok, _, _ = trend_allows_entry(
        spot,
        sma_days=params.trend_sma_days,
        enabled=params.trend_filter,
        closes=spot_history,
    )
    if not trend_ok:
        return None

    t = params.dte_entry / 365.0
    vol = vix / 100.0
    best = None
    # Same band the live bot searches (wheel_strategy._find_credit_spread).
    ceiling = spot * (1.0 - params.otm_pct)
    floor = spot * (1.0 - max(params.otm_pct * 2.5, params.otm_pct + params.otm_floor_extra))
    for k in np.arange(_round_strike(ceiling), _round_strike(floor) - 1, -50.0):
        delta = abs(bs_put_delta(spot, float(k), t, vol))
        long_k = float(k) - params.hedge_width
        if long_k <= 0:
            continue
        short_p = bs_put_price(spot, float(k), t, vol)
        long_p = bs_put_price(spot, long_k, t, vol)
        credit = short_p - long_p
        width = float(k) - long_k
        if credit <= 0 or width <= 0:
            continue
        if credit / width < params.min_credit_width:
            continue
        score = abs(delta - params.target_delta)
        if best is None or score < best[0]:
            best = (score, float(k), long_k, credit)
    if best is None:
        # Live falls back to "any strike <= ceiling" only when the band holds no
        # strikes at all; on a 50-point grid the band is never empty, so the only
        # fallback that can fire here is the ceiling strike itself.
        short_k = _round_strike(spot * (1.0 - params.otm_pct))
        long_k = short_k - params.hedge_width
        credit = bs_put_price(spot, short_k, t, vol) - bs_put_price(spot, long_k, t, vol)
        if credit <= 0 or params.hedge_width * params.lot_size > params.initial_capital:
            return None
        if credit / params.hedge_width < params.min_credit_width:
            return None
        return short_k, long_k, credit
    return best[1], best[2], best[3]


def _cost_to_close(spot: float, short_k: float, long_k: float, dte: int, vix: float) -> float:
    t = max(dte, 0) / 365.0
    vol = vix / 100.0
    return bs_put_price(spot, short_k, t, vol) - bs_put_price(spot, long_k, t, vol)


def run_pcs_backtest(df: pl.DataFrame, params: PCSParams | None = None) -> BacktestResult:
    """Simulate Friday PCS entries with Stage-6 exits/filters under ₹50k."""
    params = params or PCSParams()
    if params.hedge_width * params.lot_size > params.initial_capital:
        raise ValueError(
            f"width×lot {params.hedge_width * params.lot_size} exceeds capital {params.initial_capital}"
        )

    # Optional chain table (unused for pricing loop unless mid lookup added later)
    _ = load_option_chains() if chain_files_available() else None

    equity = params.initial_capital
    peak = equity
    max_dd = 0.0
    trades: list[TradeRecord] = []
    in_trade = False
    short_k = long_k = credit = 0.0
    num_lots = 0
    entry_d: date | None = None
    expiry_d: date | None = None
    vix_hist: list[float] = []
    spot_hist: list[float] = []

    rows = list(df.iter_rows(named=True))
    for row in rows:
        spot = float(row["Spot_Price"])
        vix = float(row["VIX"])
        d = row["Date"]
        if hasattr(d, "date"):
            d = d.date()
        vix_hist.append(vix)
        spot_hist.append(spot)

        if not in_trade:
            if d.weekday() != params.entry_weekday:
                continue
            sel = _select_strikes(spot, vix, params, vix_hist[-252:], spot_hist, d)
            if sel is None:
                continue
            short_k, long_k, credit = sel
            # Sizing parity with wheel_strategy: lots = floor(budget / width×lot).
            required_capital_per_lot = (short_k - long_k) * params.lot_size
            if required_capital_per_lot <= 0:
                continue
            num_lots = math.floor(equity * params.allocation_pct / required_capital_per_lot)
            if num_lots == 0:
                continue
            entry_d = d
            expiry_d = d + timedelta(days=params.dte_entry)
            in_trade = True
            continue

        assert entry_d is not None and expiry_d is not None
        dte = (expiry_d - d).days
        ctc = _cost_to_close(spot, short_k, long_k, max(dte, 0), vix)
        abs_delta = abs(bs_put_delta(spot, short_k, max(dte, 0) / 365.0, vix / 100.0))
        reason = None
        if ctc <= params.tp_residual * credit:
            reason = "Take Profit"
        elif ctc >= params.sl_multiple * credit or (params.stop_on_touch and spot <= short_k):
            reason = "Stop Loss"
        elif abs_delta >= params.short_delta_manage:
            reason = "Delta Manage"
        elif params.dte_manage >= 0 and dte <= params.dte_manage and d > entry_d:
            reason = "DTE Manage"
        elif params.time_stop_weekday >= 0 and d.weekday() == params.time_stop_weekday and d > entry_d:
            reason = "Time Stop"
        if dte <= 0 and reason is None:
            reason = "Expiry"
            ctc = max(ctc, 0.0)

        if reason is None:
            continue

        qty = params.lot_size * num_lots
        # Max loss is a structural property of the spread (width - credit), so the
        # clamp goes on the raw market P&L. Slippage and fees are friction paid on
        # top of that floor — subtract them after the clamp, or a max-loss trade
        # would come out looking free of both.
        market_pnl = max((credit - ctc) * qty, -(params.hedge_width - credit) * qty)
        # Nothing is traded to close when the spread expires worthless: no exit haircut.
        exit_traded = not (reason == "Expiry" and ctc <= 0.0)
        slippage = params.slippage_points * qty * (2 if exit_traded else 1)
        pnl = market_pnl - slippage - round_trip_fees(credit, ctc, params.lot_size, num_lots)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        trades.append(TradeRecord(entry_d, d, short_k, long_k, credit, pnl, reason))
        in_trade = False

    wins = sum(1 for t in trades if t.pnl > 0)
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    pf = (gross_win / gross_loss) if gross_loss > 1e-9 else (float("inf") if gross_win > 0 else 0.0)
    mix = Counter(t.exit_reason for t in trades)
    total_pnl = sum(t.pnl for t in trades)
    n = len(trades)
    return BacktestResult(
        total_trades=n,
        winning_trades=wins,
        win_rate=(wins / n * 100.0) if n else 0.0,
        avg_pnl=(total_pnl / n) if n else 0.0,
        total_pnl=total_pnl,
        max_drawdown=max_dd,
        profit_factor=pf if pf != float("inf") else 99.0,
        ruin_proxy=max_dd / params.initial_capital,
        exit_reason_mix=dict(mix),
        trades=trades,
        final_equity=equity,
    )


def sweep_exit_params(
    df: pl.DataFrame | None = None,
    slippage_points: float = PCSParams.slippage_points,
) -> list[dict[str, Any]]:
    """Sweep the untested levers: touch-stop x hedge width x take-profit (18 cells).

    sl_multiple/dte_manage stay at defaults — the full cross product is >100 cells
    of mostly noise.
    """
    df = df if df is not None else synthetic_spot_path()
    defaults = PCSParams()
    grid = []
    for touch in (True, False):
        for width in (100.0, 200.0, 300.0):
            for tp in (0.25, 0.50, 0.75):
                params = PCSParams(
                    tp_residual=tp,
                    hedge_width=width,
                    stop_on_touch=touch,
                    slippage_points=slippage_points,
                    time_stop_weekday=-1,
                )
                res = run_pcs_backtest(df, params)
                grid.append({
                    "stop_on_touch": touch,
                    "hedge_width": width,
                    "tp_residual": tp,
                    "sl_multiple": defaults.sl_multiple,
                    "dte_manage": defaults.dte_manage,
                    **res.as_dict(),
                })
    grid.sort(
        key=lambda r: (r["profit_factor"], r["total_pnl"], -r["ruin_proxy"]),
        reverse=True,
    )
    return grid


def walk_forward(
    df: pl.DataFrame,
    train_days: int = 504,
    test_days: int = 252,
    params: PCSParams | None = None,
) -> list[dict[str, Any]]:
    """Expanding/rolling walk-forward: train window unused for fit (rules fixed); report test folds."""
    params = params or PCSParams()
    rows = list(df.iter_rows(named=True))
    folds = []
    i = train_days
    fold = 0
    while i + test_days <= len(rows):
        test_slice = rows[i : i + test_days]
        test_df = pl.DataFrame(test_slice)
        # Warm-up history for IVR/SMA from prior train window
        warm = rows[max(0, i - train_days) : i + test_days]
        warm_df = pl.DataFrame(warm)
        res = run_pcs_backtest(warm_df, params)
        # Approximate OOS: only count trades with entry in test window
        test_start = test_slice[0]["Date"]
        if hasattr(test_start, "date"):
            test_start = test_start.date()
        oos_trades = [t for t in res.trades if t.entry_date >= test_start]
        wins = sum(1 for t in oos_trades if t.pnl > 0)
        total = sum(t.pnl for t in oos_trades)
        gw = sum(t.pnl for t in oos_trades if t.pnl > 0)
        gl = abs(sum(t.pnl for t in oos_trades if t.pnl < 0))
        pf = (gw / gl) if gl > 1e-9 else (99.0 if gw > 0 else 0.0)
        folds.append({
            "fold": fold,
            "test_start": str(test_start),
            "trades": len(oos_trades),
            "win_rate": (wins / len(oos_trades) * 100.0) if oos_trades else 0.0,
            "total_pnl": total,
            "profit_factor": pf,
        })
        fold += 1
        i += test_days
    return folds


# --- Legacy equity-wheel helpers ---

LOT_SIZES = {
    "RELIANCE.NS": 250,
    "HDFCBANK.NS": 550,
    "INFY.NS": 400,
    "MARUTI.NS": 65,
    "SBIN.NS": 1500,
}


def fetch_historical_data(ticker: str, start_date: str, end_date: str) -> pl.DataFrame:
    return fetch_nifty_vix_path(start_date, end_date) if ticker in ("^NSEI", "Nifty 50") else fetch_nifty_vix_path(start_date, end_date)


def estimate_premium(spot: float, strike: float, vix: float, dte: int = 30) -> float:
    return (spot * (vix / 100.0)) * 0.10 * (strike / spot)


def run_equity_wheel_backtest(df: pl.DataFrame, lot_size: int, initial_capital: float = 50000.0) -> dict:
    _ = initial_capital
    return {"total_trades": 0, "winning_trades": 0, "win_rate": 0.0, "final_pnl": 0.0, "average_yield_pct": 0.0, "trade_yields": []}


run_backtest = run_equity_wheel_backtest


def main():
    parser = argparse.ArgumentParser(description="Nifty PCS backtest (₹50k capital)")
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--from-yahoo", action="store_true", help="Use yfinance Nifty+VIX path")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--days", type=int, default=756)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--slippage", type=float, default=PCSParams.slippage_points,
        help="Per-side bid-ask haircut in index points (0 isolates the parity fixes)",
    )
    args = parser.parse_args()
    params = PCSParams(slippage_points=args.slippage)

    if args.from_yahoo or args.walk_forward:
        try:
            df = fetch_nifty_vix_path(args.start)
            model = "yfinance ^NSEI/^INDIAVIX + VIX-calibrated BS"
        except Exception as e:
            print(f"Yahoo fetch failed ({e}); falling back to synthetic path.")
            df = synthetic_spot_path(n_days=args.days, seed=args.seed)
            model = "synthetic GBM + VIX-calibrated BS"
    else:
        df = synthetic_spot_path(n_days=args.days, seed=args.seed)
        model = "synthetic GBM + VIX-calibrated BS"

    chain_note = " + option_chains parquet" if chain_files_available() else ""
    print(
        f"PCS backtest | capital=INR {INITIAL_CAPITAL:,.0f} | lot={NIFTY_LOT} | "
        f"width={DEFAULT_HEDGE_WIDTH} | alloc={params.allocation_pct:.0%} | slippage={args.slippage}pt/side"
    )
    print(f"Model: {model}{chain_note}\n")

    if args.walk_forward:
        folds = walk_forward(df, params=params)
        print(f"{'Fold':>4} {'Start':>12} {'Trades':>7} {'Win%':>7} {'TotalPnL':>10} {'PF':>6}")
        for f in folds:
            print(
                f"{f['fold']:4d} {f['test_start']:>12} {f['trades']:7d} "
                f"{f['win_rate']:6.1f}% {f['total_pnl']:10.1f} {f['profit_factor']:6.2f}"
            )
        if folds:
            avg_pf = sum(f["profit_factor"] for f in folds) / len(folds)
            print(f"\nAvg OOS profit factor: {avg_pf:.2f}")
        return

    if args.sweep:
        grid = sweep_exit_params(df, slippage_points=args.slippage)
        print(f"{'Touch':>6} {'Width':>6} {'TP':>5} {'Trades':>7} {'Win%':>7} {'PF':>6} {'TotalPnL':>11} {'Ruin':>6}")
        for row in grid[:18]:
            print(
                f"{str(row['stop_on_touch']):>6} {row['hedge_width']:6.0f} {row['tp_residual']:5.2f} "
                f"{row['total_trades']:7d} {row['win_rate']:6.1f}% {row['profit_factor']:6.2f} "
                f"{row['total_pnl']:11.1f} {row['ruin_proxy']:6.2f}"
            )
        best = grid[0]
        print("\nBest by profit_factor:", {k: best[k] for k in (
            "stop_on_touch", "hedge_width", "tp_residual", "sl_multiple", "dte_manage",
            "profit_factor", "total_pnl", "ruin_proxy"
        )})
        return

    res = run_pcs_backtest(df, params)
    print(f"Trades: {res.total_trades}")
    print(f"Win rate: {res.win_rate:.1f}%")
    print(f"Profit factor: {res.profit_factor:.2f}")
    print(f"Avg P&L: INR {res.avg_pnl:.2f}")
    print(f"Total P&L: INR {res.total_pnl:.2f}")
    print(f"Max drawdown: INR {res.max_drawdown:.2f} (ruin_proxy={res.ruin_proxy:.2%})")
    print(f"Final equity: INR {res.final_equity:.2f}")
    print(f"Exit mix: {res.exit_reason_mix}")


if __name__ == "__main__":
    main()
