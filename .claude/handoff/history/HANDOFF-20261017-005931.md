# HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)
_Updated: 2026-10-16_

## Goal
Phases 0-4 of 20261016_plan.md. Paper only; no deploy/.env change without asking.

## Status
- Phases 1 (5318f1f, deployed), 2 (0713cc9, NOT pushed), 3 engine+prereg (d4dfd86) done.
- Prereg APPROVED by user, amendment A1 (mechanical fixes) before any run.
- DEV grid RUN (research/run_dev.py): NO eligible candidate -> FAIL per registered rule; OOS NOT run, never to be run under this registration.
- Cause: min credit/width 0.15 gate leaves 0 trades at delta<=0.20; delta 0.25 hold best (n<=98, CAGR 3-4%). Details docs/plans/20261016-real-chain-pcs-dev-result.md (uncommitted until evaluator PASS).
- User chose B and approved v2 pre-reg (docs/plans/20261017-...-v2.md, frozen). v2 runner: research/run_dev2.py (32 configs). NEXT: commit, run `python -m research.run_dev2` (DEV only), report. OOS only if a winner exists, once, with lock file OOS_RUN.lock (needs a small script; not written). If no winner: FAIL, no v3.

## Decisions
- No rescue tuning; OOS untouched.

## Next
1. Commit v1/v2 docs + run_dev/run_dev2 (keep 20261016_plan.md, HANDOFF.auto, history/, graphify-out out).
2. Act on user's A/B decision. Phase 4 only on PASS.
