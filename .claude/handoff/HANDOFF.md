# HANDOFF — Phase A infra for docs/plans/20261017-next-hypotheses-plan.md
_Updated: 2026-10-17 · context ~15% (post-compaction)_

## Goal
Finish Phase A (A6 only if Phase B passes), commit and push, report to the user, then run the Phase B measurement
study on DEV 2019-2023 only. PCS is dead (OOS FAIL, eb3c5ce). The paper bot is untouched; no deploy.

## Status
- Done, all tested (245+ pass): STT history, lot history, iv.py, rv.py (+NSE patch), events.py/csv, bhavcopy
  3x-404 holiday rule, plan amendments.
- A1 download complete through 2018; manifest has no `error` rows. Do NOT re-fetch holidays: 2013-10-09 and
  2021-03-30 are real archive gaps (fo/mkt bundle only, no settle), documented in the plan; Phase B skips them.
- rv cache rebuilt: 15 sessions without index close (2011-05..2013-01), 5 VIX nulls (2013-14). OOS-A only.
- events.csv: budgets/elections now carry `announced` (ECI dates for elections, 2024-07-06 for the Jul-2024
  budget, date-14d conservative proxy for other budgets). Rewriting events.csv: use a Python csv script, keep LF.
- Evaluator round 3 (ad0727a9128d17ece) findings all addressed; re-review then commit.

## Commands
- `uv run pytest -q` (~52s). Commit command separate from edits; untracked files need `git add -N` first.
- Evaluator: `git diff HEAD -- <explicit paths incl. .claude/handoff/>`.

## Next step
1. Evaluator PASS -> commit explicit paths -> push origin main. No deploy.
2. Report Phase A to the user, then start Phase B on DEV only (decision point after B results).
