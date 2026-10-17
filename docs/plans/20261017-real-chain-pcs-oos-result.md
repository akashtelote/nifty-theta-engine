# Real-chain PCS v2 — OOS result: **FAIL**

_Run 2026-10-17, once (lock `data/bhavcopy/OOS_RUN.lock`), per `20261017-real-chain-pcs-preregistration-v2.md` §4/§6. Raw output: `data/bhavcopy/oos_out_v2.txt` (gitignored). Runner: `research/run_oos.py`._

Config (v2 DEV winner on the A3-corrected engine): width 200, delta 0.25, min credit/width 0.08, hold to expiry, DTE 3–10. OOS window 2024-01-01 → 2026-10-16, no dropped open trades.

| Metric (slip 0.5) | OOS | DEV |
|---|---|---|
| Trades | 72 | 153 |
| Win rate | 70.8% | 86.3% |
| Profit factor | **0.65** (95% CI 0.37–1.35) | 1.45 |
| PF at slip 0.25 / 1.0 | 0.67 / 0.60 | – / 1.36 |
| Expectancy / trade | **−₹1,795** (CI −4,797 … +970) | +₹1,183 |
| Total P&L | −₹1,29,270 on ₹20L | – |
| CAGR (after tax) | −2.4% (−2.5%) | 1.75% (1.19%) |
| Max drawdown | 7.9% | 5.4% |
| Worst trade / week | −1.93% / −1.93% of equity | −1.98% |

Criteria: 1 n≥40 PASS · 2 PF≥1.30 & >1.0 at slip 1.0 **FAIL** · 3 expectancy CI lower >0 **FAIL** · 4 DD≤20% PASS · 5 worst trade/week PASS · 6 after-tax CAGR >benchmark and ≥7% **FAIL** · 7 stress ≤8% loss PASS · 8 OOS PF ≥0.7×DEV PF (1.01) **FAIL** · 9 PF CI lower >1.0 **FAIL**.

**Verdict: FAIL.** Per the frozen doc: write up, recommend shutting the strategy down, no v3 registration.

## Known defect in the runner (does not change the verdict)
The benchmark and "5 largest gap-down days" use a parity-forward index proxy that is unreliable (reported −28%/−25% gap days are artefacts; benchmark CAGR 2.1% looks too low). Criterion 6 fails anyway (strategy after-tax CAGR is negative, floor 7%) and criteria 2, 3, 8, 9 fail on trade data alone, so no pass/fail outcome depends on the proxy except criterion 7, whose PASS was computed on proxy-picked days: it holds by a bound instead (one position at a time, worst trade −1.93% of equity, so any 1-day window holds ≤ ~2 trades ≈ ≤3.9% < 8%). Not re-run (OOS is one-shot).

## Reading
DEV edge (PF 1.45, CI spanning 1) did not survive: OOS PF 0.65 with a negative point-estimate expectancy. A ~71% win rate with 2× width-sized losses and a few-point credit/width floor is the signature of selling cheap tail insurance without a demonstrated edge. Caveats still apply (settle-price fills, no bid/ask, no VIX/event gates), but none would plausibly turn −₹1.3L into the ≥7% after-tax CAGR bar.
