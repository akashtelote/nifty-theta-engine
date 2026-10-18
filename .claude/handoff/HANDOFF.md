# HANDOFF — E1-E4 plan finished (docs/plans/20261017-equity-futures-hypotheses-plan.md)
_Updated: 2026-10-18 · context at 61%_

## Goal
Plan order A1→A2→A3→A4→E1→E2→A6→E4→A5→E3 is COMPLETE. All four hypotheses DEV FAIL -> no OOS (plan: DEV FAIL
stops a hypothesis, no rule changes). Final step: result write-up docs/plans/20261018-equity-futures-result.md.

## Status
- Pushed: E3 9525ba1 (+ graphify ea51820). E1 96cdc63, E2 7b9d1ef, E4 471442c, A5 5164d97, A6 0c9a222.
- E3 DEV FAIL gate 2 CI [-1.07%, 19.67%]; Sharpe 0.69, corr 0.06, MDD 19.7%. 3 evaluator rounds, R3 PASS.
- In progress: result doc written (uncommitted) -> evaluator -> commit -> graphify -> push -> tell user.

## Decisions
- User said "proceed" after E3 report; interpreted as finish the plan (write-up), NOT OOS on a failed DEV.

## Commit workflow
- Evaluator (independent-evaluator, foreground) must print raw `git diff HEAD -- <path>` headers per file;
  `git add -N` untracked files + .claude/handoff/history/ + HANDOFF.auto.md, then `git reset` them before commit.
  Never commit HANDOFF.auto.md, history/, data/token.json, 20261016_plan.md. Msg ends
  "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
- After commit: `graphify update .`; `git checkout -- graphify-out/cache/last_query_stamp`; review; commit
  "Graphify changes"; push.
- Never rerun PCS OOS (data/bhavcopy/OOS_RUN.lock). Never suggest ETFs/MFs/index funds. Paper only, no deploy.

## Next step
1. Evaluator on result doc + HANDOFF.md (+ add -N'd auto/history), commit, graphify, push.
2. Report to user; next direction is the user's call.
