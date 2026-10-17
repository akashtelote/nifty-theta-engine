# HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)
_Updated: 2026-10-16_

## Goal
Plan phases 0-4 in 20261016_plan.md. Paper only; no deploy/.env change without asking; Phase 3 needs pre-reg approval before any result is read.

## Status
- Phase 1 DONE: commit 5318f1f pushed AND deployed to Oracle (user approved); bot healthy, dashboard loopback-only (ssh -L 8502:127.0.0.1:8502 oracle). Not yet seen: first sizing decision on live data.
- Phase 2 DONE, awaiting commit (195 tests pass): research/{bhavcopy,reference,quality,execution}.py, tests/test_bhavcopy.py, ISSUE_LOG ISS-R8..R11. Data at data/bhavcopy (gitignored; 1,932 days 2019-01-01..2026-10-16; coverage_report.txt). Legacy==UDiFF on overlap days. Lot rules: 75 (exp<=2021-07-22), 50 (to 2024-04-25), 25 from 2024-04-26; UDiFF rows carry lot. Parity noisy only at thin far strikes (10% bad at 20-29 DTE).
- Slippage levels 0.25/0.5/1.0 pts per leg (research/execution.py).
- NEXT Phase 3: write docs/plans/<ts>-real-chain-pcs-preregistration.md (DEV 2019-2023, OOS 2024->latest; grid width{100,200,300} x delta{.15,.20,.25} x exits{2x stop; no stop+delta/DTE mgmt; hold/TP} ; PASS criteria numbers) and GET USER APPROVAL before running any backtest or reading results. Need a real-chain backtest engine (research/engine.py) first - build/test it on synthetic fixtures only, not on results. Exercise STT must be wired into the engine.

## Gotchas
- Before deploy: confirm server .env sets DATABASE_URL (now required, else bot crashes at start). ALLOCATION_PCT_PER_TRADE in server .env is now ignored (extra=ignore).
- Compose now binds dashboard 127.0.0.1:8502 → user needs ssh tunnel after deploy.
- Hedge width 300 at 2% needs ~₹1M equity.

## Next
1. Evaluator -> commit -> ask user to approve deploy.
2. Phase 2: NSE bhavcopy loader (legacy + UDiFF), point-in-time lot sizes/expiries, data-quality report.
3. Phase 3: pre-reg doc in docs/plans/, user approval, DEV, OOS once behind lock.
