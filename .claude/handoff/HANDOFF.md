# HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
_Updated: 2026-10-17 ~19:30 · context ~65%_

## Goal
Run Phase A: A1→A2→A3→A4, then E1→E2→A6→E4→A5→E3. Paper only. No deploy, no .env changes, no OOS runs.

## Status
- Pushed: plan, A1 loader, A3 indices, T-bill, stock ID, A1 coverage report dbbe85f (+ graphify a23c6cc).
- **A2 done in code, awaiting evaluator then commit**: `research/corp_actions.py`, `research/ca_manual.csv`
  (header only), `tests/test_corp_actions.py` (22 pass; full suite 284), plan A2 row + Amendments §3.
  - User approved (a) window-drop rule, then option (c): also flag demerger/scheme gaps and resumptions.
  - `rows` has `ca_flag` / `ca_flag_n`. Flag sources:
    - detector 59;
    - ex-day outliers 8 (|r−1| > 0.25);
    - unresolved rights 16;
    - `schemes()` 165 (gap > 10% after f, NSE demerg/sch/arrang/amalg filing ≤ 10d before);
    - `stale()` 876 (previous row more than 20 sessions back).
    - Total: 1,110 sessions / 504 stocks.
  - The report lists 134 large unflagged gaps, left in as real moves (post-2009 mostly ETF unit splits).
  - Gate rerun after (c): PASS (45 days, 0.9778), recorded in plan §3.
  - .playwright-mcp/ deleted (BSE browsing leftovers).

## Decisions (and why)
- Manual CSV takes split/bonus with factor f only, and needs an NSE/BSE URL. Left empty: no hit is confirmed.
- Large gaps that are not flagged stay in, so real crashes are not removed (avoids flattering the backtest).
- E1/E2/E4 must use `ca_flag_n[t1] > ca_flag_n[t0]` to drop windows.

## Tried and failed
- Python heredocs via Bash collapse `\\`. Use raw strings or Write.
- BSE bulk DefaultData window query is incomplete; use per-scrip (via playwright; Akamai blocks curl).
- The commit hook missed files when the evaluator's diff output was long and got truncated. Tell the evaluator to
  run each diff as a separate call, paged with `sed -n` ranges, and to show `git diff HEAD -- graphify-out | grep '^diff --git'`.

## Next step
1. Run `graphify update .`, `git add -N` history + graphify cache, then dispatch the evaluator.
2. On PASS: `git reset .claude/handoff/history/`, commit A2 + plan + HANDOFF, then a Graphify commit, then push.
3. A4, then E1 (apply the ca_flag_n window rule).
