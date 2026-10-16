# DEV result: real-chain Bull Put Credit Spread (pre-registration d4dfd86 + amendment A1)

_2026-10-16. Runner: `research/run_dev.py` (executes §3–§4 (grid, eligibility, winner rule); §5 extras are only produced for a winner of the pre-registration). Full 54-row table: `data/bhavcopy/dev_grid.csv` (gitignored data dir)._

## Verdict: FAIL on DEV — OOS was NOT run (and per §4 never will be for this registration)
No config satisfied the registered candidate filter (>=100 trades, PF>=1.2 at slip 1.0, max DD<=25%, worst trade<=3.5%).
The maximum trade count of any config was 98 (6 configs had >=70); 27 of 54 produced **zero** trades.

## What the numbers say (slip 0.5, DEV 2019–2023, ₹20L equity, 2% risk)
- delta 0.15: 0 trades in every width/mode/band. delta 0.20: 0–14 trades. Only delta 0.25 trades regularly (1–98; n≥13 in all but the w300 3–10 rows).
- Cause (diagnostic on 260 entry Fridays, width 100, 3–10 DTE): 86 weeks below SMA50, 12 without SMA/spot data (start of data),
  and of the remaining ~162 the **min credit/width >= 0.15 gate** passed only 2 at delta 0.20 (median credit/width 11.4% after paying
  0.5 pt slippage per leg) and 101 at delta 0.25 (median 15.8%). The gate, not a losing edge, is what suppresses trading.
- The best-looking rows are `hold` at delta 0.25 (e.g. w100 3–10: n=98, win 77.6%, PF 3.53, CAGR 3.2% on ₹20L, DD 1.9%; 10–17 band: n=77, win 96%, PF 30). They fail the filter on sample size (n<100) and are tiny in absolute terms: expectancy ₹3.5–6k per trade, CAGR 3–4% before the stress periods that a hold-to-expiry book with 2% risk per trade is built to absorb. High win rate + no stop + few trades is the classic short-vol profile; DEV's 2019–2023 contains only one big crash (Mar 2020, mostly gated out by the SMA50 rule).
- `mgmt` and `stop2x` modes are worse than `hold` almost everywhere at delta 0.25 (e.g. w100 3–10 mgmt: PF 0.56, DD 10.8%).
- At the registered cost levels, per-trade gross edge after fees is small relative to the capital deployed: best config ~3–4% CAGR, below the 7% PASS floor, before any benchmark comparison.

## Interpretation (not a rescue)
The strategy as registered either does not trade (delta <= 0.20 with a 0.15 credit/width floor) or trades rarely and earns low single-digit returns on risk capital. Nothing here supports going live; a reading of "the edge is hiding behind the gate" is a hypothesis for a **new** registration, not a re-tune of this one.

## Caveats
Settle-based fills (no bid/ask); credit measured net of 2 x slip so the 0.15 gate is conservative vs live quotes; 54 trials; DEV is 2019–2023 only.

## Decision needed (user)
A. Accept the FAIL and shut the strategy down (plan's default). B. Pre-register a v2 before any new run (e.g. drop/lower the credit gate, delta 0.25-0.30 family, staggered entries) — it would consume a fresh trial budget, DEV would be re-used so only the untouched OOS 2024+ can validate it, and OOS remains unseen.
