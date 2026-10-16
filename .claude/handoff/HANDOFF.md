# HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)
_Updated: 2026-10-16_

## Goal
Plan phases 0-4 in 20261016_plan.md. Paper only; no deploy/.env change without asking; Phase 3 needs pre-reg approval before any result is read.

## Status
- Phase 0 done (status note sent). Server: HEDGE_WIDTH 100, SL 2.0, delta .18, DTE 10-42, STT 0.001, midweek on; only 2 closed paper trades (−₹1,545 lifetime).
- User decision: risk sizing 3% paper default (2% is the ramp rule); backtest should transfer to ~₹20L (option c).
- Phase 1 code done, 183 tests pass, UNCOMMITTED: config/settings.py (date-aware fees, RISK_* settings, DATABASE_URL required), core/sizing.py, wheel_strategy sizing + _open_max_loss, backtest risk sizing, stress.py legacy allocation, dashboard env DB url, compose loopback bind, token.json git rm --cached, docs, tests/test_sizing.py, test_costs.py.
- In progress: independent-evaluator gate, then commit (do NOT deploy; ask user).

## Gotchas
- Before deploy: confirm server .env sets DATABASE_URL (now required, else bot crashes at start). ALLOCATION_PCT_PER_TRADE in server .env is now ignored (extra=ignore).
- Compose now binds dashboard 127.0.0.1:8502 → user needs ssh tunnel after deploy.
- Hedge width 300 at 2% needs ~₹1M equity.

## Next
1. Evaluator -> commit -> ask user to approve deploy.
2. Phase 2: NSE bhavcopy loader (legacy + UDiFF), point-in-time lot sizes/expiries, data-quality report.
3. Phase 3: pre-reg doc in docs/plans/, user approval, DEV, OOS once behind lock.
