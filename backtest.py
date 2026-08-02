"""Put Credit Spread (PCS) backtest harness matching live exit/entry rules.

Uses a synthetic Black–Scholes-style option model on Nifty-like spot paths because
full historical NSE option chains are not bundled. Documented limitation (PROF-007):
results are relative (for parameter ranking), not absolute live expectancy.

Capital ceiling: ₹50,000 (one-lot width × lot must fit).

Run:
    uv run python backtest.py
    uv run python backtest.py --sweep
    uv run python -c "from backtest import run_pcs_backtest, synthetic_spot_path; ..."

Legacy equity-wheel helpers remain as ``run_equity_wheel_backtest`` / ``fetch_historical_data``.
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

# Align with production lot / capital constraint
NIFTY_LOT = 25
INITIAL_CAPITAL = 50_000.0
DEFAULT_HEDGE_WIDTH = 100.0


@dataclass
class PCSParams:
    tp_residual: float = 0.25
    sl_multiple: float = 2.0
    time_stop_weekday: int = 3  # Thursday
    otm_pct: float = 0.01
    hedge_width: float = DEFAULT_HEDGE_WIDTH
    target_delta: float = 0.18
    min_credit_width: float = 0.12
    entry_weekday: int = 4  # Friday
    dte_entry: int = 21
    vix_max: float = 25.0
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
    """Generate trading-day spot + VIX path (no weekends)."""
    rng = np.random.default_rng(seed)
    rows = []
    spot = start_spot
    vix = 15.0
    d = date(2022, 1, 3)
    for _ in range(n_days):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        # Mean-reverting VIX
        vix = float(np.clip(vix + 0.15 * (15.0 - vix) + rng.normal(0, 0.8), 10.0, 35.0))
        vol = vix / 100.0
        daily_ret = (mu - 0.5 * vol * vol) / 252.0 + vol * rng.normal() / math.sqrt(252.0)
        spot = float(spot * math.exp(daily_ret))
        rows.append({"Date": d, "Spot_Price": spot, "VIX": vix})
        d += timedelta(days=1)
    return pl.DataFrame(rows)


def _round_strike(x: float, step: float = 50.0) -> float:
    return round(x / step) * step


def _select_strikes(spot: float, vix: float, params: PCSParams) -> tuple[float, float, float] | None:
    """Return (short_strike, long_strike, credit_per_share) or None if capital/guards fail."""
    if vix > params.vix_max:
        return None
    if params.hedge_width * params.lot_size > params.initial_capital:
        return None

    t = params.dte_entry / 365.0
    vol = vix / 100.0
    # Search OTM puts near target delta
    best = None
    ceiling = spot * (1.0 - params.otm_pct)
    for k in np.arange(_round_strike(ceiling), _round_strike(spot * 0.92) - 1, -50.0):
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
        # Fallback: fixed 1% OTM
        short_k = _round_strike(spot * (1.0 - params.otm_pct))
        long_k = short_k - params.hedge_width
        credit = bs_put_price(spot, short_k, t, vol) - bs_put_price(spot, long_k, t, vol)
        if credit <= 0 or params.hedge_width * params.lot_size > params.initial_capital:
            return None
        return short_k, long_k, credit
    return best[1], best[2], best[3]


def _cost_to_close(spot: float, short_k: float, long_k: float, dte: int, vix: float) -> float:
    t = max(dte, 0) / 365.0
    vol = vix / 100.0
    return bs_put_price(spot, short_k, t, vol) - bs_put_price(spot, long_k, t, vol)


def run_pcs_backtest(df: pl.DataFrame, params: PCSParams | None = None) -> BacktestResult:
    """Simulate Friday PCS entries with TP / SL / time-stop / expiry exits under ₹50k."""
    params = params or PCSParams()
    if params.hedge_width * params.lot_size > params.initial_capital:
        raise ValueError(
            f"width×lot {params.hedge_width * params.lot_size} exceeds capital {params.initial_capital}"
        )

    equity = params.initial_capital
    peak = equity
    max_dd = 0.0
    trades: list[TradeRecord] = []
    in_trade = False
    short_k = long_k = credit = 0.0
    entry_d: date | None = None
    expiry_d: date | None = None

    rows = list(df.iter_rows(named=True))
    for i, row in enumerate(rows):
        spot = float(row["Spot_Price"])
        vix = float(row["VIX"])
        d = row["Date"]
        if hasattr(d, "date"):
            d = d.date()

        if not in_trade:
            if d.weekday() != params.entry_weekday:
                continue
            if equity < params.hedge_width * params.lot_size:
                continue
            sel = _select_strikes(spot, vix, params)
            if sel is None:
                continue
            short_k, long_k, credit = sel
            entry_d = d
            expiry_d = d + timedelta(days=params.dte_entry)
            in_trade = True
            continue

        assert entry_d is not None and expiry_d is not None
        dte = (expiry_d - d).days
        ctc = _cost_to_close(spot, short_k, long_k, max(dte, 0), vix)
        reason = None
        if ctc <= params.tp_residual * credit:
            reason = "Take Profit"
        elif ctc >= params.sl_multiple * credit or spot <= short_k:
            reason = "Stop Loss"
        elif d.weekday() == params.time_stop_weekday and d > entry_d:
            # Daily bar ≈ Thursday close (live: Thu ≥ 15:00 IST)
            reason = "Time Stop"
        if dte <= 0 and reason is None:
            reason = "Expiry"
            ctc = max(ctc, 0.0)

        if reason is None:
            continue

        pnl = (credit - ctc) * params.lot_size
        # Cap loss at max risk
        max_loss = (params.hedge_width - credit) * params.lot_size
        pnl = max(pnl, -max_loss)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        trades.append(
            TradeRecord(entry_d, d, short_k, long_k, credit, pnl, reason)
        )
        in_trade = False

    wins = sum(1 for t in trades if t.pnl > 0)
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
        exit_reason_mix=dict(mix),
        trades=trades,
        final_equity=equity,
    )


def sweep_exit_params(df: pl.DataFrame | None = None) -> list[dict[str, Any]]:
    """Grid-search TP/SL under ₹50k; returns ranked rows by total_pnl then win_rate."""
    df = df if df is not None else synthetic_spot_path()
    grid = []
    for tp in (0.15, 0.20, 0.25, 0.30):
        for sl in (1.5, 2.0, 2.5):
            params = PCSParams(tp_residual=tp, sl_multiple=sl)
            res = run_pcs_backtest(df, params)
            grid.append({
                "tp_residual": tp,
                "sl_multiple": sl,
                **res.as_dict(),
            })
    grid.sort(key=lambda r: (r["total_pnl"], r["win_rate"]), reverse=True)
    return grid


# --- Legacy equity-wheel helpers (retained for reference) ---

LOT_SIZES = {
    "RELIANCE.NS": 250,
    "HDFCBANK.NS": 550,
    "INFY.NS": 400,
    "MARUTI.NS": 65,
    "SBIN.NS": 1500,
}


def fetch_historical_data(ticker: str, start_date: str, end_date: str) -> pl.DataFrame:
    import yfinance as yf

    asset_df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    vix_df = yf.download("^INDIAVIX", start=start_date, end=end_date, progress=False)
    asset_close = asset_df[["Close"]].reset_index()
    vix_close = vix_df[["Close"]].reset_index()
    asset_close.columns = ["Date", "Spot_Price"]
    vix_close.columns = ["Date", "VIX"]
    pl_asset = pl.from_pandas(asset_close)
    pl_vix = pl.from_pandas(vix_close)
    if pl_asset.schema["Date"] != pl.Date:
        try:
            pl_asset = pl_asset.with_columns(pl.col("Date").dt.date())
        except Exception:
            pl_asset = pl_asset.with_columns(pl.col("Date").cast(pl.Date))
    if pl_vix.schema["Date"] != pl.Date:
        try:
            pl_vix = pl_vix.with_columns(pl.col("Date").dt.date())
        except Exception:
            pl_vix = pl_vix.with_columns(pl.col("Date").cast(pl.Date))
    merged_df = pl_asset.join(pl_vix, on="Date", how="left")
    merged_df = merged_df.with_columns([
        pl.col("Spot_Price").fill_null(strategy="forward"),
        pl.col("VIX").fill_null(strategy="forward"),
    ])
    return merged_df.select(["Date", "Spot_Price", "VIX"])


def estimate_premium(spot: float, strike: float, vix: float, dte: int = 30) -> float:
    return (spot * (vix / 100.0)) * 0.10 * (strike / spot)


def run_equity_wheel_backtest(df: pl.DataFrame, lot_size: int, initial_capital: float = 50000.0) -> dict:
    """Deprecated equity CSP toy model; capital default now ₹50k."""
    _ = initial_capital
    days_in_trade = 0
    in_trade = False
    short_strike = 0.0
    long_strike = 0.0
    net_credit = 0.0
    realized_pnl = 0.0
    total_trades = 0
    winning_trades = 0
    trade_yields = []

    for row in df.iter_rows(named=True):
        spot = row.get("Spot_Price")
        vix = row.get("VIX")
        if spot is None or vix is None or np.isnan(spot) or np.isnan(vix):
            continue
        if not in_trade:
            if vix < 13:
                otm = 0.06
            elif 13 <= vix <= 18:
                otm = 0.10
            else:
                otm = 0.15
            short_strike = spot * (1 - otm)
            long_strike = short_strike * 0.98
            net_credit = estimate_premium(spot, short_strike, vix)
            in_trade = True
            days_in_trade = 0
            total_trades += 1
        else:
            days_in_trade += 1
            if days_in_trade == 30:
                margin_blocked = (short_strike - long_strike) * lot_size
                if spot > short_strike:
                    winning_trades += 1
                    trade_pnl_rupees = net_credit * lot_size
                else:
                    loss = (short_strike - long_strike) - net_credit
                    trade_pnl_rupees = -loss * lot_size
                realized_pnl += trade_pnl_rupees
                trade_yields.append((trade_pnl_rupees / margin_blocked) * 100 if margin_blocked else 0.0)
                in_trade = False
                days_in_trade = 0

    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "win_rate": win_rate,
        "final_pnl": realized_pnl,
        "average_yield_pct": float(np.mean(trade_yields)) if trade_yields else 0.0,
        "trade_yields": trade_yields,
    }


# Back-compat alias
run_backtest = run_equity_wheel_backtest


def main():
    parser = argparse.ArgumentParser(description="Nifty PCS backtest (₹50k capital)")
    parser.add_argument("--sweep", action="store_true", help="Run TP/SL parameter sweep")
    parser.add_argument("--days", type=int, default=756, help="Synthetic path length")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    df = synthetic_spot_path(n_days=args.days, seed=args.seed)
    print(f"PCS backtest | capital=INR {INITIAL_CAPITAL:,.0f} | lot={NIFTY_LOT} | width={DEFAULT_HEDGE_WIDTH}")
    print("Model: synthetic GBM spot + BS put premiums (no historical option chain).\n")

    if args.sweep:
        grid = sweep_exit_params(df)
        print(f"{'TP':>5} {'SL':>5} {'Trades':>7} {'Win%':>7} {'AvgPnL':>10} {'TotalPnL':>10} {'MaxDD':>10}  ExitMix")
        for row in grid[:12]:
            print(
                f"{row['tp_residual']:5.2f} {row['sl_multiple']:5.1f} {row['total_trades']:7d} "
                f"{row['win_rate']:6.1f}% {row['avg_pnl']:10.1f} {row['total_pnl']:10.1f} "
                f"{row['max_drawdown']:10.1f}  {row['exit_reason_mix']}"
            )
        best = grid[0]
        print("\nBest by total_pnl:", {k: best[k] for k in ("tp_residual", "sl_multiple", "win_rate", "total_pnl", "max_drawdown")})
        return

    res = run_pcs_backtest(df, PCSParams())
    print(f"Trades: {res.total_trades}")
    print(f"Win rate: {res.win_rate:.1f}%")
    print(f"Avg P&L: INR {res.avg_pnl:.2f}")
    print(f"Total P&L: INR {res.total_pnl:.2f}")
    print(f"Max drawdown: INR {res.max_drawdown:.2f}")
    print(f"Final equity: INR {res.final_equity:.2f}")
    print(f"Exit mix: {res.exit_reason_mix}")


if __name__ == "__main__":
    main()
