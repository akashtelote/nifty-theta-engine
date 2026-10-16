# Pre-registration: Bull Put Credit Spread on real Nifty option chains

_Written 2026-10-16, BEFORE any real-data backtest has been run or any result read. Status: **APPROVED by user 2026-10-16 — FROZEN.**
Once approved this file is frozen; any later change is a new dated amendment, never an edit._

Engine and metrics: `research/engine.py`, `research/metrics.py` (tested on synthetic chains only: `tests/test_engine.py`).
Data: NSE F&O bhavcopy 2019-01-01 .. 2026-10-16 (`research/`, Phase 2). Question: does a strategy family near the live bot (not identical: live uses delta 0.18, 3% risk on ₹2L, a spot<=short-strike stop, a Thu 15:00 time stop and VIX/IVR/event gates) have a
real, after-cost, after-tax edge? A clear FAIL is an acceptable outcome and leads to a shutdown recommendation.

## 1. Windows (fixed)
- **DEV**: entries 2019-01-01 .. 2023-12-31. All selection happens here.
- **OOS**: entries 2024-01-01 .. latest data. Touched exactly once, for the single DEV winner, behind a lock file
  (`data/bhavcopy/OOS_RUN.lock`, created before the run; if it exists the run refuses). A crash after lock creation
  still counts as the one run.

## 2. Strategy and engine rules (all fixed)
- One position at a time, entered on the last trading day of each ISO week, nearest expiry whose DTE is inside the band.
  Staggered/overlapping entries are NOT tested (data does not support honest margin accounting for them).
- Short put: liquid OTM strike (multiple of 50, >=50 contracts, settle >= 1.0) with Black-76 delta (r=0, IV from the put's own
  settle, put-call-parity forward) closest to target. Long put = short strike − width.
- Gates: spot (parity-forward proxy) >= SMA50; natural credit/width >= 0.15. No VIX gate and no event blackout (VIX/events are not in bhavcopy).
- Execution: legs fill at settle ∓ slippage per leg (sell at settle−slip, buy at settle+slip). Exits are decided on a day's
  settle and executed at the NEXT trading day's settle ± slip. Expiry cash-settles at intrinsic with no exit orders
  (exit brokerage removed; exercise STT charged if the long put is ITM).
- Fees: `config.settings.round_trip_fees` (date-aware STT, exchange, stamp, SEBI, IPFT, GST, ₹20/order) on entry-date regime.
- Sizing: `core.sizing.risk_lots`, equity0 = ₹20,00,000, per-trade max loss <= 2% of realised equity, portfolio <= 8%.
  **User replied "approved" to this doc and to this question (2026-10-16)**: the live bot runs ₹2L at 3%; ₹20L/2% is used because 75-lot-era sizes give 0 lots at ₹2L,
  and results are reported as % of equity and per-lot so they scale.
- Trades still open at the end of data are dropped (reported as a count).

## 3. Grid (54 configs = the multiple-comparison trial count)
| Axis | Values |
|---|---|
| width | 100, 200, 300 |
| short delta | 0.15, 0.20, 0.25 |
| exit mode | `stop2x` (TP at 25% residual credit, SL at 2× credit) · `mgmt` (no premium stop; exit at delta>=0.40 or DTE<=1; TP 25%) · `hold` (TP 25%, else hold to expiry; defined risk) |
| DTE band | 3–10 (weekly) · 10–17 (second weekly) |

Selection uses slippage 0.5 only. No other parameter (TP, SL multiple, SMA length, min credit/width) is varied.

## 4. DEV winner rule
Candidates must satisfy on DEV @ slip 0.5: n >= 100 trades, PF >= 1.2 even at slip 1.0, max DD <= 25%, worst trade <= 3.5% of equity0.
Winner = highest Calmar (CAGR / max DD) among candidates; ties → smaller width, then lower delta, then `hold` < `mgmt` < `stop2x`.
**No candidate → STOP: verdict FAIL, OOS is never run.** DEV results for all 54 configs are published (not just the winner).

## 5. Metrics reported (every run)
n, win rate, PF and expectancy per trade each with a 95% percentile bootstrap CI (i.i.d. trades, 5000 resamples, seed 12345),
CAGR, max drawdown (incl. intratrade worst mid-mark), worst trade / ISO week / month, return on max-loss capital,
after-tax P&L (30% on annual FY profit, no loss carry-forward — conservative), total fees, at slippage 0.25 / 0.5 / 1.0.
Benchmark: NIFTYBEES price CAGR over the same window (price only; dividends excluded, which slightly flatters the strategy).
Stress windows reported separately for the winner: 2020-02-01..2020-03-31, 2024-06-04 (±5 trading days), and the 5 largest Nifty gap-down days.

## 6. Frozen PASS criteria (OOS, winner config; ALL must hold)
1. n >= 40 OOS trades (fewer = INCONCLUSIVE = not a pass).
2. PF >= 1.30 at slip 0.5, and PF > 1.0 at slip 1.0.
3. Lower bound of the 95% CI of per-trade expectancy > 0 at slip 0.5.
4. Max drawdown <= 20% of equity.
5. Worst single trade <= 3.5% of equity0; worst ISO week <= 6%.
6. After-tax CAGR (slip 0.5) > NIFTYBEES price CAGR over the OOS window AND >= 7%.
7. No stress window loses more than 8% of equity.
8. DEV→OOS consistency: OOS PF >= 0.7 × DEV PF (guards against a fitted winner).

## 7. After the result
- FAIL or INCONCLUSIVE: write up honestly with all numbers, recommend shutting the strategy down. No rescue tuning, no re-run on OOS.
- PASS: proceed to Phase 4 (paper default set to the winner with approval, live-vs-backtest tracking, capital ramp runbook, kill switch).
  A PASS is evidence, not proof: 54 trials, one OOS period, settle-proxy fills.

## 8. Known limitations (declared up front)
Settle ≠ 15:15 traded price; no bid/ask; no VIX/event gates; parity-forward spot proxy; r=0; fees use entry-date regime;
i.i.d. bootstrap ignores volatility clustering (CIs are optimistic); noisy settle on thin strikes (liquid strikes only).

## 9. Amendment A1 (2026-10-16, before any real-data run; no PASS number changed)
Independent review of the engine on synthetic data found mechanical defects; fixed and tested, no result seen:
- Deep-ITM puts whose settle is at/below parity intrinsic count as delta 1.0 (the `mgmt` delta exit was silently disabled).
- A TP/stop/manage decided the day before expiry now executes on expiry day at settle ± slip with exit orders and fees (previously became a free cash-settle). So `mgmt` DTE<=1 exits on expiry day.
- Sizing equity is capped at equity0 (as live caps at MAX_CAPITAL), so "worst trade <= 3.5% of equity0" is not penalised by compounding.
- Criterion 6 "after-tax CAGR" = (equity0 + after-tax P&L) vs equity0 over the window; metrics now emit it, worst trade/week as % of equity0, and a count of entries dropped for being open at end of data. Stress-window loss % is computed from `window()` trades' summed P&L / equity0.
- Bootstrap CI returns NaN when every resample is degenerate (all-winner window).
