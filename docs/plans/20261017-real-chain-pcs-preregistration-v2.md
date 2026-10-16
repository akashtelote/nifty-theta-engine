# Pre-registration v2: Bull Put Credit Spread on real Nifty chains

_Written 2026-10-17 after DEV v1 was run and read (docs/plans/20261016-real-chain-pcs-dev-result.md) but BEFORE any v2 run and before OOS (2024-01-01 →) was ever touched.
Status: **APPROVED by user 2026-10-17 ("proceed") — FROZEN. No v2 backtest had been run at approval.**_

## 0. Honest status of the evidence
v2 is **not** independent of DEV: it is designed from what v1 DEV showed (credit gate suppresses trades; `hold` beat `stop2x`/`mgmt`; delta 0.25 was the only delta that traded).
So DEV can only *select* within v2, never *validate* it. The sole validation is the untouched OOS window, used once. Cumulative trial count = 54 (v1) + 32 (v2) = **86**; any PASS is discounted accordingly (§6 criterion 9).
Engine, metrics, fees, fills, windows: unchanged from `d4dfd86` + amendment A1 (code frozen; only the grid and the credit gate differ). Everything in v1 §1, §2, §5 applies unless stated here.

## 1. Hypothesis
Under realistic fills a 100–200-wide Nifty put spread at delta 0.25–0.30, held to expiry (or stopped at 2× credit), earns a positive after-cost, after-tax return with bounded loss, once the live bot's 0.15 credit/width floor (which v1 showed blocks most entries at net-of-slippage prices) is relaxed. Falsifiable by the criteria in §6.

## 2. Grid (32 configs)
| Axis | Values |
|---|---|
| width | 100, 200 (300 dropped: ≤25 trades in v1 DEV) |
| short delta | 0.25, 0.30 (0.15 dropped: 0 trades; 0.20 dropped: ≤14 trades) |
| min credit/width | 0.08, 0.12 (live 0.15 retained only as v1) |
| exit mode | `hold` (TP 25% residual, else expiry), `stop2x` (TP 25%, SL 2× credit) (`mgmt` dropped: worse in v1 DEV) |
| DTE band | 3–10, 10–17 |
Selection slippage 0.5; slip 0.25/1.0 reported. Nothing else varied.

## 3. DEV winner rule (as v1 §4, same thresholds)
n ≥ 100, PF ≥ 1.2 at slip 1.0, max DD ≤ 25%, worst trade ≤ 3.5% of equity0 → highest Calmar; ties: smaller width, lower delta, higher min_cw, `hold` < `stop2x`, 3–10 before 10–17. **No candidate → FAIL, OOS never run, strategy shut down (no v3).**
Additional DEV requirement (new): the winner's loss in 2020-02-01..2020-03-31 must be ≤ 8% of equity0.

## 4. OOS
2024-01-01 → latest data, once, lock file `data/bhavcopy/OOS_RUN.lock` (created before the run; presence blocks reruns).

## 5. Metrics
As v1 §5 incl. after-tax CAGR, stress windows (Feb–Mar 2020 in DEV; 4 Jun 2024 ±5 trading days and 5 largest gap-down days in OOS), NIFTYBEES price CAGR benchmark, dropped-open-trade count.

## 6. Frozen PASS criteria (OOS, winner; ALL must hold)
Criteria 1–8 identical to v1 §6 (n ≥ 40; PF ≥ 1.30 @0.5 and > 1.0 @1.0; expectancy 95% CI lower bound > 0; max DD ≤ 20%; worst trade ≤ 3.5% and worst week ≤ 6% of equity0; after-tax CAGR > NIFTYBEES price CAGR and ≥ 7%; no stress window loss > 8%; OOS PF ≥ 0.7 × DEV PF), plus:
9. Multiple-testing discount (86 trials): OOS PF lower 95% CI bound > 1.0.
Nothing is loosened relative to v1.

## 7. After the result
FAIL/INCONCLUSIVE → write up, recommend shutting the strategy down; no further registrations. PASS → Phase 4 per the plan (paper default change with approval, tracking report, capital ramp, kill switch); a PASS is evidence not proof (86 trials, one OOS period, settle-proxy fills, no VIX/event gates).

## 8. Limitations
The credit gate is applied after slippage, so each slippage level trades a different entry set; "PF ≥ 1.2 at slip 1.0" is measured on that set, not on the slip-0.5 trades (as registered). As v1 §8, plus design-from-DEV contamination (§0). Lowering the credit floor means accepting thinner premium per unit of risk; the live bot's 0.15 floor would need a deliberate change if v2 passes.

## 9. Amendment A2 (2026-10-17, mechanical, before any v2 result was produced)
The first v2 DEV run crashed (`expiry day missing from data`) on expiry 2023-06-29 (Bakri Id holiday): NSE settles such a series on the previous trading day and the bhavcopy relabels it with that earlier date (2023-06-28). `research/engine.py::_walk` now settles on the last trading day before a non-trading listed expiry, reading the relabelled series. Rules, grid, gates, criteria and DEV/OOS split are unchanged; no result had been seen. v1 trades never hit this path (to be re-confirmed by re-running the v1 grid and diffing against `dev_grid.csv`). Test: `test_holiday_shifted_expiry_settles_on_previous_trading_day`.
