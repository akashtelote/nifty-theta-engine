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

## Next step
1. Check run9, diff vs run8 (only voided rows gone + 2013 redate).
2. Evaluator round 5 → PASS → reset history, commit, graphify update + commit, push. Then E1. FINDINGS → stop, report.
