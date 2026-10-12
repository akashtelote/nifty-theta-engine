# HANDOFF — capital 50k -> 200k + doc refresh + push
_Updated: 2026-10-12_

## Goal
Capital default 200000 in code/.env.example/docs/tests, refresh stale docs, commit everything (incl. user's staged graphify-out + CLAUDE.md), push, deploy safely.

## Status
- Done: settings.py/.env.example/backtest.py/tests/docs (CLAUDE, ARCHITECTURE, WHEEL manual, ROADMAP, ISSUE_LOG) edited; 162 tests pass; graphify updated.
- In progress: independent-evaluator gate over all dirty files, then commit, push, deploy.

## Decisions
- ALLOCATION_PCT_PER_TRADE stays 0.25 (server pins it): at 200k = ~50k budget = 7 lots (max loss ~45.5k). Flag to user.
- test_stress 0.25-vs-0.15 equivalence + brick tests pinned to CAP_50K (only true at 50k).
- Server .env already 200000/0.25/TP 0.25: no .env change.

## Commands
- Deploy: `ssh oracle "cd ~/nifty-theta-engine && git pull && docker compose build && docker compose up -d"` (NOT deploy.sh: it downs before build)
- Gate: evaluator needs `git diff HEAD -- <file>` per file; `git add -N` untracked.

## Next step
1. Evaluator PASS -> `git commit -a` (all) -> push -> deploy -> verify container settings + :8502.
