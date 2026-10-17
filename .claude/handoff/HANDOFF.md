# HANDOFF — Phase B measurement study (docs/plans/20261017-next-hypotheses-plan.md)
_Updated: 2026-10-17 · context ~60%_

## Goal
Phase B on DEV 2019-2023 decides H1/H2/H3. Done when the result doc is committed and pushed and the user has the verdict
(user decision point). No deploy; the paper bot is untouched.

## Status
- Phase A committed and pushed (2f6e619).
- Phase B run: research/phase_b.py, tests/test_phase_b.py, docs/plans/20261017-phase-b-measurement-result.md.
  **All three FAIL** (H1: no top-quintile CI > 0; H2: pooled n=74, CI [-9.7, 21.8]; H3: no bucket cheap).
- Evaluator round 1 findings fixed (held=False voided dates, iv30 on unfiltered surface, B1 gap CIs, dropped-pair count); re-run, verdicts unchanged.
- Next: evaluator round 2, then commit, push, and report to the user.

## Decisions
- Proxy payoff uses |S_T - K| (ATM strike), not |S_T - F|; S_T = index close on the expiry session (matches the
  bhavcopy settle exactly on 204 expiries).
- Cluster bootstrap by expiry; alpha 0.05/3; event 1-day CI clusters by session.
- Stop branch per the plan: no new signals or gates after seeing the results.

## Commands
- `PYTHONIOENCODING=utf-8 uv run python -m research.phase_b` (~1-2 min; reads the cached surface parquet).

## Next step
1. Evaluator -> commit explicit paths -> push.
2. Report to the user: null result, project stops options-premium research unless they want a new pre-registered idea.
