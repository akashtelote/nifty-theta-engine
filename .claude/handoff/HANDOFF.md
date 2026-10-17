# HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
_Updated: 2026-10-17 · context ~71%_

## Goal
Run Phase A of the plan: A1→A2→A3→A4, then E1→E2→A6→E4→A5→E3. Paper only. No deploy, no .env changes, no OOS runs.

## Status
- Plan 6245d8b, A1 9b8b1b9 and A3 indices **bb353e9** are all pushed.
- **The A1 download is running in the background** (task b4bi3c2kg) into `data/equity/`. It was at about 2019-12 at the last check.
  - It is resumable: `uv run python -m research.equity 2005-01-01 2026-09-30`.
- After "proceed", option 2 (the Nifty T-bill index) turned out not to be served by niftyindices, so I fell back to
  **RBI SDMX `YIELD_TB_RN`, 15–91 day bucket, monthly**. Stored at `data/benchmarks/tbill_15to91_monthly.parquet`:
  361 rows, 1996-04→2026-06, contiguous from 2005-01.
- **The following is uncommitted, and the evaluator's round-1 findings on it are fixed:**
  - `research/benchmarks.py`: `parse_tbill` (rejects duplicates and nulls; months must be contiguous from TBILL_FROM=2005-01-31) and `fetch_tbill` (raises on no rows), both via `TBILL_URL`.
  - `tests/test_benchmarks.py`: 5 tests, all passing.
  - The plan doc has a new "Amendments" section at the end:
    - (1) Nifty 500 price from niftyindices; **2005–2010 is not yet checked**, and is to be checked against equity days once A1 completes.
    - (2) The risk-free rate is the T-bill yield_pct/1200 for the same month, carried forward from June 2026 for July–September 2026. Gate 1's Sharpe and gate 2's excess both use returns minus the risk-free rate.

## Decisions
- Commit gate: one `git diff HEAD -- <file>` per file; the reply must start with a bare `PASS` line. `git add -N` the untracked files. Review the history snapshots in `.claude/handoff/history/` (`git add -N` them), then `git reset` them; never commit them. The hook also re-checks HANDOFF.md if it changes after review.
- E3 sizing straddling a product switch: size on the contract held at the fill.
- `research.*` imports: use `uv run python -c` without `-I`.

## Update 13:5x — T-bill committed 879452a (pushed, user told). Now: permanent stock ID
- New `research/stock_id.py` + `tests/test_stock_id.py` (5 pass), add -N'd, uncommitted.
  - Node = ISIN or SYM:<symbol> (pre 2011-06-22).
  - ISIN→ISIN: strict next session.
  - SYM→ISIN and SYM→SYM: nearest match within SYM_GAP=60 sessions.
  - Sessions are days with ≥10% of the median row count; this drops the 2010-05-16 and 2012-11-11 specials.
  - Requires b.first > a.last, so there are no cycles; an earlier version without it hung the tests.
  - Ambiguous links are dropped.
  - perm_id is the chain's tail node.
  - Symbol-change list cached at data/equity_ref/symbolchange.csv (gitignored).
- Real data to 2022: 2124 links, 0 ambiguous, 0 duplicate (date, perm_id) rows. Unlinked at the switch: BINANICEM, ESSARSHIP, TV-18, WINDSOR, FTCPOF5YDV.
- Evaluator round 1 FINDINGS fixed: SYM gap was too strict, special sessions, docstring overpromised the report. **Round 2 next**, then commit and push.
- Coverage report (still to build after the download) must list every link with `missing`, SYM nodes with long internal gaps, and the ISIN→ISIN near misses (DRCSYSTEMS, INTEGRA, 3 ETFs).

## Next step
1. Evaluator round 2 on stock_id.py, test_stock_id.py and HANDOFF.md; commit and push.
2. After the download: the 2005–2010 benchmark gap check, the coverage report, then A2.
