# HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
_Updated: 2026-10-17 night · context at 61%_

## Goal
Run Phase A: A1→A2→A3→A4, then E1→E2→A6→E4→A5→E3. Paper only. No deploy, no .env changes, no OOS runs.

## Status
- Pushed: A1, A3, A2 (3d28844) + graphify 1479271.
- **A4 in progress** (plan line 81). `research/index_changes.py` + `tests/test_index_changes.py` (11 pass), both
  untracked (`git add -N`). pyproject.toml/uv.lock: pdfplumber in optional `research` extra (uncommitted).
- Evaluator round 1 (ab933766d906abff3): all fixed (EFFECTIVE regex, mkdir, fetch 404, IREDA revocation
  REVOKED+BSE HAND, EXCLUDED dict of 14 index-name-table exclusion PDFs → HAND, REVIEWED set + facts["index_list"]
  flag → report "not yet read" list). run4 clean.
- Evaluator round 2 (adf36d864c83d633b) FINDINGS, all now fixed in code, run5 rebuilding → scratchpad run5.txt:
  1. Smallcap 100 header "(Formerly …)" 11 words → header word count ignores parentheticals; report lists
     duplicate serials per (url,index,side,serial) (should be 0 now; 2016-H1 MIDCAP100 should drop 25→8).
  2. 17102016 mixed preamble (A annual review / C Cairn amalgamation) → `clauses`/`clause_kind` per A./B./C.
     preamble clause; target header takes its clause's kind when clauses disagree. PROSE lookahead now allows `and`.
  3. Re-announced pending changes (07032017 SBI pull-forward, 2020-03-16 SHREECEM, 2018-03-06, 2017-08-29) →
     `merge_repeats`: keep first announcement, take later effective, new column `rescheduled_by`; report lists them.
  4. review_check now per index: complete = NEXT50, NIFTY500, MIDCAP(100|150) present with kind scheduled or
     criteria_revision; NO_CHANGE = 2010-H2 N500/MIDCAP (18082010 review had no such sections — checked).
  5. ind_prs02032012 (S&P CNX 500 change, 2012-03-07) unserved, no archive.org copy → MISSING_TARGET, report names it.
- Round 3 is the LAST evaluator round (cap 3). If findings remain → stop and tell the user.

## Decisions
- announced = PDF date (fallback listing date); announced_time null.
- criteria_revision rows at a semi-annual review count as review rows (2016-02); E1 should include them.
- Dummy zero-price inclusions skipped (holders receive shares). BSE 2024-03-19 = ad_hoc.
- E1/E2/E4 must use `ca_flag_n[t1] > ca_flag_n[t0]` to drop windows (A2 amendment 3).

## Tried and failed
- pdftotext (xpdf 4.00) → pdfplumber. Read tool can't render PDFs (no poppler): pdfplumber `to_image`.
- Commit hook: evaluator runs each diff separately, paged (`sed -n`), graphify via `grep '^diff --git'`;
  history snapshots `git add -N`'d → `git reset .claude/handoff/history/` before commit.
- Windows python: C:/... paths for scratchpad.

## Commands
- `uv run --extra research pytest -q tests/test_index_changes.py`
- rebuild: `PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run --extra research python -m research.index_changes`

## Round 3 (aa7a555a6326acdec) = FINDINGS → review cap reached; STOPPED, reported to user, nothing committed
run6 (dup serials 0, 18/18, 16/16, Cairn ad_hoc) looked clean but:
1. clause_kind regression: 18022020 clause "A. Revision of eligibility criteria … rebalancing of NIFTY 500" →
   all 40 N500 rows of the Feb-2020 review labelled ad_hoc. Fix idea: only apply clause_kind when release has no
   group lines / clause must name the index as a list item, not in criteria prose; review_check per release.
2. Opposite-side cancellations not handled: 19032020 (YESBANK Midcap100/150 add cancelled, PVR instead),
   12032020 (SHILPAMED stays N500, GAYAPROJ out). Self-join (index,symbol) opposite side, announced in
   (announced, effective] finds 3 pairs → drop/REVOKED + report check.
3. 2021-H2 N500/MIDCAP150 rows carry announced=2021-09-15 (restatement); names on scanned 08-23 list should be 08-23.
4. Minor: duplicate `k =` line in merge_repeats; 19032020 per-row effective differs Midcap100 vs 150.

## User said "proceed" → fixing round-3 findings, then round 4 (user-approved beyond cap)
Done in code (10 tests pass): criteria clauses skipped in `clauses`; EFFECTIVE matches with was/were in prior 60
chars ignored; `cancel_pairs` (build returns 3-tuple; report lists cancelled); review_check per release (best
release per half); RESTATED (2021-08-23 lists read from scan pp.3-6) re-dates 15092021 rows; dead `k` removed.
run6 backup: scratchpad/changes_run6.parquet. run7 → scratchpad/run7.txt.
NB: python heredocs turned "\b"/"\n" into control chars — check `grep -c $'\x08'` after scripted edits.

run8 (scratchpad/run8.txt): DEV 18/18, 2019+ 16/16, dup 0, mixed-kind 0, cancelled 6 rows, 21 moved. review_check
stayed per half (2014-08-26 Midcap review is a separate release) + new report list of releases mixing kinds.
Diff vs run6 = only intended: 18022020 N500 → scheduled; 6 cancelled rows gone; 76 rows 2021-09-15 → 08-23.

## Round 4 (a6ce901bf4dba0199) = FINDINGS (round-3 items all verified fixed) → STOPPED, asked user
1. 2020 March review voided by ind_prs13052020 ("…Feb 18, Mar 12, Mar 19 … shall stand null and void" except N50/Bank);
   re-run 2020-06-10. 95 rows (18022020/12032020/19032020, effective 03-27) are phantom; keep 16032020 accelerations
   (eff 03-19). Title filter RELEVANT drops 23032020/25032020 "Deferment", 13052020 "reconstitution". PDFs in
   scratchpad/dl/. Fix: VOID set (hand-listed, like REVOKED) or widen RELEVANT.
2. ind_prs13112013 "Revised Index re-balancing date" not fetched: 2013-11-07 N500 rows eff 11-15 → should be 11-18.

## User said "proceed" → round-4 fixes + round 5 (approved beyond cap)
Done (11 tests pass): VOIDED + REDATED constants, `void_and_redate` after merge_repeats, before cancel_pairs; build's
3rd return = left-out rows with `why` (voided|cancelled); report hand-coded note names both. Did NOT widen RELEVANT:
full-listing scan (scratchpad/full_listing.csv) found only 13112013/23032020/25032020/13052020 as change-relevant
skipped releases, all now handled by hand. run8 backup: scratchpad/changes_run8.parquet; run9 → scratchpad/run9.txt.
Expect: ~95 voided rows, 2020-H1 still complete via 2020-06-10, 4 rows 2013-11-07 effective 11-18.

run9: 3642 rows, DEV 18/18, 2019+ 16/16; vs run8 only 95 voided rows gone + 4 rows 2013-11-07 → eff 11-18.
Round 5 (acdb0014a747261d8) PASS. **A4 pushed: 1730cd1 + graphify 4f33a65.**
Gate quirk: evaluator must print raw `diff --git` lines unfiltered (summaries / paged views past line 1 don't count).
Graph ingests untracked handoff history notes into graph.json (pre-existing, not fixed).

## E1 (started 2026-10-18 after user "proceed")
- A7 equity delivery fees: config/settings.py tail (`equity_delivery_fees`, dated STT/txn/stamp/service-tax/GST
  schedules + sources) + tests/test_costs.py::test_equity_delivery_fees_dated (15 pass).
- research/e1_inclusion.py (DEV only; OOS rows never loaded) + tests/test_e1_inclusion.py (3 pass).
  Interpretation: one event per (review half, symbol) at highest-priority index; N50->Next50 demotion = N50 removal.
  Per-event notional = Rs2L / kept adds in review. Tax only in portfolio report. Removals futures short not run (no FUTSTK).
- DEV run1 -> scratchpad/e1_run1.txt; outputs data/e1/dev_report.txt, dev_events.parquet.
- Nothing committed yet. Next: read run1, sanity-check, evaluator round 1 (diff settings.py, test_costs.py, new files),
  commit + graphify + push, report DEV PASS/FAIL to user. OOS only on user's go.

- **E1 DONE: DEV FAIL** (net mean -2.09%, 98.75% CI [-4.22%, +0.47%], gross CI spans 0). Pushed 96cdc63 + graphify 8657e67.
  Stopped per plan; waiting on user for E2. No OOS.

## E2 (user "proceed" 2026-10-18) — plan lines 128-168
- Writing research/e2_momentum.py (DEV only, rows <= 2018-12-31) + tests/test_e2_momentum.py.
- Data: corp_actions.build()["rows"] joined with equity.load() series/value on (date, symbol) (both keys unique).
  Benchmarks data/benchmarks/tri_nifty_500.parquet, tri_nifty200_momentum_30.parquet (date, tri).
- Interpretations: monthly returns month-end close to month-end close (NAV0 = Rs2L at Dec-2009 close); held stock's
  flagged session return neutralised (units rescaled) = amendment-3 "drop" inside a portfolio; liquidity median pads
  missing sessions with 0; tax: STCG/LTCG per FY with set-off + carry-forward, paid first session on/after Apr 1,
  final liquidation taxed; cash earns 0; 6-month secondary = t-7m..t-1m month-ends (same skip month).

- run1 (scratchpad/e2_run1.txt; data/e2/dev_report.txt): **DEV FAIL on all 3 gates** — CAGR +10.84% vs N500 TRI
  +9.94% / Mom30 TRI +17.98%; excess CI [-1.235%, +1.655%]; MDD 41.9% (peak 2010-11, trough 2013-12, regime whipsaw).
  Secondary: no-regime +18.14% CI [-0.47%, +2.14%] MDD 34.6%; 6m +6.02%; semi-annual +12.82% MDD 31.0%.
  Neutralised sessions 0 (ca_flag = 693 anomaly rows in DEV, splits already in adj) — checked, plausible.
  Refill candidates restricted to rank <= keep (else a name sold for rank > keep was rebought same session).

- **E2 DONE: DEV FAIL**, pushed 7b9d1ef + graphify 23df2f0, reported.

## A6 (user "proceed" 2026-10-18) — plan line 83; E4 at plan lines 239-282
Probes (scratchpad a6_pw.py, a6_trunc.py): jugaad_data/playwright NOT in venv → `uv run --with playwright`, launch
with executable_path=~/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe (latest pw wants newer build).
Land on https://www.nseindia.com/report-detail/display-bulk-and-block-deals, then page.evaluate(fetch(...)).
- /api/historical/bulk-deals = 503. WORKS: /api/historicalOR/bulk-block-short-deals?optionType=bulk_deals|block_deals
  &from=DD-MM-YYYY&to=DD-MM-YYYY. JSON capped at 70 rows/response (even per day) → use **&csv=true** (full: 2016 bulk
  6261 rows, block 183 = monthly JSON sum). Range ≤1y (2y → 500). Bulk from 2004-01, block from ~2005-11 (empty before).
  CSV header: "Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ","Quantity Traded ","Trade Price / Wght.
  Avg. Price ","Remarks " ; qty "2,50,000"; date "01-MAR-2024". Some early dates are weekends (04-JAN-2004 Sun).
- Shares outstanding: /api/corporate-share-holdings-master?index=equities&symbol=X → only 21 quarters (2021-09+),
  percentages only (counts in XBRL) → no PIT source for DEV → E4 uses the plan's FALLBACK rule.
Plan: research/deals.py — monthly CSV windows 2004-01..2026-09 per kind, raw cache data/deals/raw/{kind}/YYYY-MM.csv,
parse → data/deals/deals.parquet + coverage report (rows/yr/kind, empty months, non-session dates, unmatched symbols).
RESULT (data/deals/report.txt): 254,607 rows (bulk 241,405 / block 13,202), 23 yrs, 0 failures, 0 missing months,
28 empty months (block pre-2005-11 + 6 sporadic), 25 exact dups kept. Off-session from 2005-01-03: 0 (1,153 2004 rows
unchecked — no bhavcopy calendar). Unmatched (date,symbol) vs EQ/BE: 25,828 rows (10.2%), 19,920 of those rows have a symbol never EQ/BE (SME).
Side normalised (B/S/SOLD → BUY/SELL; 3 early rows).
E4 can only trade EQ/BE-matched rows. playwright added to `research` extra.

## Next step
0. Evaluator on deals.py/test/pyproject/uv.lock/HANDOFF → commit A6 + graphify + push → report A6; then E4 (fallback, DEV only).
1. (done) E1 (plan order: E1→E2→A6→E4→A5→E3). Use changes.parquet; one event per add filed under the highest index
   (N50>Next50>Midcap>N500), Next50→N50 = one N50 add, ad hoc reported separately; drop windows with ca_flag rise.
