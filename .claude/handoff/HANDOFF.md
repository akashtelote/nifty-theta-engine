# HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
_Updated: 2026-10-17 · context ~55%_

## Goal
The user said "yes": commit and push the plan, then start Phase A. Order: A1→A2→A3→A4, then E1→E2→A6→E4→A5→E3.
Paper only. No deploy, no .env changes, no OOS runs.

## Status
- Plan: 6245d8b. A1 equity loader: 9b8b1b9. Both pushed.
- **The A1 full download is running in the background** (task b4bi3c2kg, 2005-01-01→2026-09-30).
  - Output goes to `data/equity/`; scratchpad log `equity_dl.log`.
  - It is slow: about 5 months of 2005 done at 07:50. It is resumable: `uv run python -m research.equity 2005-01-01 2026-09-30`.
- **A3 is written but not yet committed:** `research/benchmarks.py` and `tests/test_benchmarks.py` (pass).
  - Data has been fetched to `data/benchmarks/*.parquet`: price OHLC for NIFTY 50/500 and TRI for NIFTY 50, NIFTY 500 and NIFTY200 MOMENTUM 30.
  - Coverage: 2005-01-03 (Momentum 30 from 2005-04-01) → 2026-10-16. No nulls.
  - Zero gaps against F&O trading days 2011–2026. The 2005–2010 check against equity days is still to do.
  - The source is the niftyindices `BackPage` POST (not `ind_close_all`, which starts about 2013). This is documented in the docstring. **Tell the user** about this source substitution.
- **The T-bill is unresolved.** It is used only by E3, which comes last, so it is deferred and must be **flagged to the user**.
  - The DBIE data-api (`https://data-api.dbie.rbihub.in/api/tables/<schema>/<table>/csv`) works, but the auction tables (r113/r307 91-day) are rounded to integers (price "99", yield "05"), so they are useless.
  - The SDMX `financial_markets/yield_tb_rn` (`/rows`) is numeric, but it is a monthly secondary-market 15–91 day yield that ends 2026-06.
  - The RBI Handbook xlsx (Table 217) covers only the last year.
  - Options: the Nifty 91-day T-bill index (niftyindices), SDMX plus a patch, or scraping RBI auction press releases.

## Decisions
- Commit gate: run one `git diff HEAD -- <file>` per file; the reply must be a bare `PASS` line. Run `git add -N` on untracked files first. Run `git add -N` on the history snapshots in `.claude/handoff/history/` for review, then `git reset` them (never commit them).
- Pending: E3 sizing should use the contract that is held at the fill when a product switch happens.
- `research.*` imports need `uv run python -c` without `-I`.

## Next step
1. Pass the evaluator gate on benchmarks.py and test_benchmarks.py (plus the handoff and history snapshots), then commit and push.
2. Tell the user about the A3 source switch and the T-bill blocker. Proceed with E3 last.
3. After the download: coverage report, permanent stock ID (ISIN chain plus `symbolchange.csv`), then A2.
