# Graph Report - nifty-theta-engine  (2026-10-18)

## Corpus Check
- 121 files · ~106,489 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1644 nodes · 2880 edges · 108 communities (97 shown, 11 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 79 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `0c9a2220`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- e2_momentum.py
- equity.py
- TestWebSocketMonitor
- WheelStateMachine
- index_changes.py
- patch
- SmartMoneyFilter
- datetime
- test_engine.py
- TestStartWsMonitor
- TestReconciliation
- ivr.py
- conftest.py
- WebSocketMonitor
- Nifty Theta Engine
- round_trip_fees
- Assert-LastExit
- main
- indian-trading-bot
- Enhancements
- Profitability Roadmap
- Nifty Theta Engine - Repository Analysis Document
- UpstoxClient
- 5.1 `wheel_strategy.py` - Wheel Strategy State Machine
- TestDebouncedRealtimeTick
- dashboard.py
- 4. Core Module (`core/`)
- 13. Risk Management & Guardrails
- patch
- 3. Entry Points
- 8. Backtest Module (`backtest.py`)
- 9. Deployment Files
- README.md
- 14. API Integration & Authentication
- 15. Deployment Architecture
- 6. Config Module (`config/`)
- AGENTS.md
- phase_b.py
- metrics.py
- bhavcopy.py
- TestActiveInstrumentKeys
- test_sizing.py
- PCSParams
- synthetic_spot_path
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- test_stage6.py
- HANDOFF — TP retune 0.50 -> 0.25 + deploy
- scheduler.py
- e1_inclusion.py
- Task: Take nifty-theta-engine from "paper experiment" to "evidence-backed or killed"
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)
- report
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- corp_actions.py
- Pre-registration v2: Bull Put Credit Spread on real Nifty chains
- iv.py
- Equity and futures hypotheses (E1–E4): research plan and pre-registration
- Next hypotheses after the PCS FAIL — research plan
- run_dev.py
- Pre-registration: Bull Put Credit Spread on real Nifty option chains
- Phase B measurement result — DEV 2019–2023 — all three hypotheses FAIL
- HANDOFF — Phase B measurement study (docs/plans/20261017-next-hypotheses-plan.md)
- HANDOFF — E1–E4 equity/futures research plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- DEV result: real-chain Bull Put Credit Spread (pre-registration d4dfd86 + amendment A1)
- HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)
- HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)
- HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)
- HANDOFF — Phase A infra for docs/plans/20261017-next-hypotheses-plan.md
- HANDOFF — Phase A infra for docs/plans/20261017-next-hypotheses-plan.md
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- Real-chain PCS v2 — OOS result: **FAIL**
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- backtest.py
- test_auth.py
- engine.py
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- TestAvailableMargin
- Settings
- test_exit_sequencing.py
- .check_exits
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
- TestFillQualityCapture
- test_costs.py
- ._select_target_put
- in_event_blackout
- put_delta
- main.py
- TestVixCircuitBreaker
- TestExitThresholdCache
- .active_instrument_keys
- .refresh_exit_thresholds

## God Nodes (most connected - your core abstractions)
1. `UpstoxClient` - 53 edges
2. `WheelStateMachine` - 53 edges
3. `PCSParams` - 37 edges
4. `run()` - 30 edges
5. `run_pcs_backtest()` - 29 edges
6. `round_trip_fees()` - 28 edges
7. `Settings` - 21 edges
8. `WebSocketMonitor` - 21 edges
9. `build()` - 20 edges
10. `Nifty Theta Engine - Repository Analysis Document` - 19 edges

## Surprising Connections (you probably didn't know these)
- `TestCostsReducePnl` --uses--> `PCSParams`  [INFERRED]
  tests/test_costs.py → backtest.py
- `TestRoundTripFees` --uses--> `PCSParams`  [INFERRED]
  tests/test_costs.py → backtest.py
- `TestStrikeBandParity` --uses--> `PCSParams`  [INFERRED]
  tests/test_costs.py → backtest.py
- `TestExitParameterization` --uses--> `PCSParams`  [INFERRED]
  tests/test_profitability.py → backtest.py
- `TestMidweekEntry` --uses--> `PCSParams`  [INFERRED]
  tests/test_profitability.py → backtest.py

## Import Cycles
- None detected.

## Communities (108 total, 11 thin omitted)

### Community 0 - "e2_momentum.py"
Cohesion: 0.12
Nodes (33): fy_tax(), _last_on(), load(), median_padded(), metrics(), month_bounds(), months_back(), _plus_year() (+25 more)

### Community 1 - "equity.py"
Cohesion: 0.13
Nodes (27): build(), _fetch(), main(), months(), parse(), DataFrame, date, Path (+19 more)

### Community 2 - "TestWebSocketMonitor"
Cohesion: 0.20
Nodes (4): Tests for the SDK-backed WebSocketMonitor wrapper., connect() is async — subscribing before the open event hits a dead socket., Only autoReconnectStopped means we're actually offline., TestWebSocketMonitor

### Community 3 - "WheelStateMachine"
Cohesion: 0.16
Nodes (9): date, Loads state from the PostgreSQL database and parses it into the nested…, Initializes the Wheel Strategy State Machine. Safely connects to the PostgreSQL…, Total max loss (width x qty - credit received) across open spreads., Compares DB state against broker positions on startup. Alerts on mismatches., Place a limit entry with limited requotes toward the marketable price. BUY…, Allow at most one same-week re-entry after Take Profit., After exits, attempt one same-week re-entry when IDLE after Take Profit… (+1 more)

### Community 4 - "index_changes.py"
Cohesion: 0.08
Nodes (48): build(), cancel_pairs(), candidates(), fetch(), index_label(), lines(), listing(), merge_repeats() (+40 more)

### Community 5 - "patch"
Cohesion: 0.12
Nodes (19): _make_active_state(), _make_tp_chain(), patch, If BTC order times out (stays pending), cancel it and keep the spread., If BTC order is rejected by exchange, keep the spread intact., When BTC fills but STC fails, short is covered — only a benign long put remains., BTC fills, STC placement fails → archive trade, alert about residual long put., BTC fills, STC times out → close position (short covered), alert for manual… (+11 more)

### Community 6 - "SmartMoneyFilter"
Cohesion: 0.10
Nodes (16): get_nifty500_tickers(), Fetches the latest Nifty 500 tickers from NSE indices CSV., DataFrame, date, Fetches Nifty 500 metadata from yfinance and caches it., Attempt to fetch deals using jugaad-data., Attempt to fetch deals using direct HTTP requests to NSE archives., Attempt to fetch deals using Playwright. (+8 more)

### Community 7 - "datetime"
Cohesion: 0.15
Nodes (22): Macro / NSE event blackout calendar for PCS entry skips (PROF-018). Dates are…, get_redis_client(), _acquire_refresh_lock(), authenticate_and_save_token(), _delete_centralized_token(), get_centralized_token(), get_current_timestamp(), _mirror_token_locally() (+14 more)

### Community 8 - "test_engine.py"
Cohesion: 0.22
Nodes (21): Chain, Per-day frames of liquid-enough Nifty options with point-in-time lot sizes; dte…, Parity-forward of the nearest expiry with dte >= 2 (proxy for spot; only used…, run(), _call(), crash(), make_chain(), Phase 3 engine + metrics tests on SYNTHETIC chains only (never real result… (+13 more)

### Community 9 - "TestStartWsMonitor"
Cohesion: 0.10
Nodes (8): Tests for scheduler WebSocket start gating and Discord fallback alerts., Only a real socket open clears the flag — and tells Discord we're back., Hourly re-arm retries must not fire a Discord alert per attempt., Overnight-expired token must be refreshed before the WS handshake., _reset_ws_state(), TestLiveAccessToken, TestRestartWsMonitor, TestStartWsMonitor

### Community 11 - "ivr.py"
Cohesion: 0.16
Nodes (14): compute_ivr(), _ensure_data_dir(), fetch_india_vix_history(), ivr_allows_entry(), load_cached_vix_closes(), India VIX percentile (IVR) helper with short-TTL file cache. Used by entry…, Return (allowed, ivr, reason)., Return percentile of current_vix within history (0–100). None if insufficient… (+6 more)

### Community 12 - "conftest.py"
Cohesion: 0.22
Nodes (12): fixture, mock_client(), mock_db_pool(), mock_notifier(), _pin_backtest_lot_size(), Keep Stage-6 entry filters from blocking unit tests (unless a test overrides)., Pin the backtest contract size so tests never depend on a downloaded file.…, Provides a mock UpstoxClient that returns controllable values. (+4 more)

### Community 13 - "WebSocketMonitor"
Cohesion: 0.13
Nodes (5): Real-time LTP monitor using the Upstox SDK's MarketDataStreamerV3. The SDK…, SDK exhausted its retries — this is the real 'we are offline' signal., Record the desired subscription set and apply it if the socket is up., Socket up (first connect or SDK auto-reconnect) — resubscribe from scratch., WebSocketMonitor

### Community 14 - "Nifty Theta Engine"
Cohesion: 0.05
Nodes (36): Architectural Audit, Data Persistence & Schema (PostgreSQL), Infrastructure Topology (docker-compose.yml), Orchestration (core/scheduler.py), The Execution Engine (strategies/wheel_strategy.py), The ML Pipeline (ml_service/) — historical / not wired to live entry, Architecture, Commands (+28 more)

### Community 15 - "round_trip_fees"
Cohesion: 0.13
Nodes (13): exercise_stt(), date, _rate(), Rate in force on `on`; None means today (live / paper)., STT paid by the BUYER of an option that expires ITM (cash-settled), on…, Total rupee cost of one spread round trip: brokerage + STT + txn + stamp + SEBI…, round_trip_fees(), stt_sell_rate() (+5 more)

### Community 23 - "Enhancements"
Cohesion: 0.05
Nodes (38): 2026-10-16 Phase 2: real option-chain data (`research/`), 2026-10-16 review fixes (plan: 20261016_plan.md, Phase 1), Critical, ENH-001: No test suite — FIXED, ENH-002: No position reconciliation on startup — FIXED, ENH-003: No concurrency guard against double-entry — FIXED, ENH-004: Pure MARKET exits risk slippage on illiquid strikes — FIXED, ENH-005: No real-time WebSocket monitoring — FIXED (+30 more)

### Community 24 - "Profitability Roadmap"
Cohesion: 0.06
Nodes (35): Chosen defaults (after Stage 6), Minimum viable capital, PROF-001: Formalize ₹50k capital ceiling, PROF-002: Sync strategy docs to actual code, PROF-003: Enable real-time exits in paper mode, PROF-004: Discord alert on WebSocket fallback, PROF-005: PCS backtest harness matching live rules, PROF-006: Parameterize TP / SL / time-stop / DTE manage (+27 more)

### Community 25 - "Nifty Theta Engine - Repository Analysis Document"
Cohesion: 0.15
Nodes (13): 10. Database Schema, 11. Environment Configuration, 12. State Machine Logic, 1. Project Overview, 2. Directory Structure, 7. Dashboard Module (`dashboard.py`), File Summary Table, Full State Transition Diagram (+5 more)

### Community 26 - "UpstoxClient"
Cohesion: 0.06
Nodes (25): fetch_data_safe(), DataFrame, Download/refresh the Upstox NSE instruments master (24h TTL, lock-protected).…, Current F&O lot size for `symbol`, straight from the instruments master. There…, Looks up the real instrument token from the Upstox NSE equities master file.…, Fetches available cash/equity margin for position sizing. Mock market returns a…, Wraps API calls in try-except blocks to catch timeouts and return None instead…, Fetches current open positions from Upstox. (+17 more)

### Community 27 - "5.1 `wheel_strategy.py` - Wheel Strategy State Machine"
Cohesion: 0.25
Nodes (8): 5.1 `wheel_strategy.py` - Wheel Strategy State Machine, 5. Strategies Module (`strategies/`), Database Schema (index_spread_state), Execution Sequence (Credit Spread), Exit Conditions, Key Methods, State Machine States, State Transitions

### Community 28 - "TestDebouncedRealtimeTick"
Cohesion: 0.20
Nodes (5): Tests for on_realtime_tick with debounce logic., Debounce: a single breach tick should NOT trigger exit., STOP_ON_STRIKE_TOUCH=False must make the real-time monitor inert, debounce…, If exit is already running for a symbol, skip further ticks., TestDebouncedRealtimeTick

### Community 29 - "dashboard.py"
Cohesion: 0.38
Nodes (6): cache_data, _fetch_cost_to_close(), load_data(), load_trade_history(), DataFrame, Best-effort live cost-to-close; returns None if quotes unavailable.

### Community 30 - "4. Core Module (`core/`)"
Cohesion: 0.29
Nodes (7): 4.1 `auth.py` - Upstox Authentication Handler, 4.2 `client.py` - Resilient HTTP Client, 4.3 `notifier.py` - Discord Webhook Integration, 4.4 `scheduler.py` - APScheduler Daemon, 4.5 `smart_money.py` - Institutional Activity Tracker, 4.6 `loader.py` - Nifty 500 Ticker Fetcher, 4. Core Module (`core/`)

### Community 31 - "13. Risk Management & Guardrails"
Cohesion: 0.33
Nodes (6): 13.1 VIX Circuit Breaker, 13.2 Bid-Ask Spread Guardrail, 13.3 Position Sizing, 13.4 Order Fill Verification, 13.5 Exit Rules, 13. Risk Management & Guardrails

### Community 32 - "patch"
Cohesion: 0.21
Nodes (6): patch, When Leg 2 placement fails, Leg 1 should be unwound., Verify budget is derived from margin, not hardcoded., TestExitVerification, TestHedgeUnwinding, TestPositionSizing

### Community 33 - "3. Entry Points"
Cohesion: 0.50
Nodes (4): 3.1 `main.py` - Bot Daemon Entry Point, 3.2 `dashboard.py` - Streamlit Analytics Dashboard, 3.3 `backtest.py` - Offline Simulation Laboratory, 3. Entry Points

### Community 34 - "8. Backtest Module (`backtest.py`)"
Cohesion: 0.50
Nodes (4): 8. Backtest Module (`backtest.py`), `estimate_premium(spot, strike, vix, dte=30) → float`, `fetch_historical_data(ticker, start_date, end_date) → pl.DataFrame`, `run_backtest(df, lot_size, initial_capital=500000) → dict`

### Community 35 - "9. Deployment Files"
Cohesion: 0.50
Nodes (4): 9.1 `Dockerfile`, 9.2 `docker-compose.yml`, 9.3 `deploy.sh`, `deploy.ps1`, `deploy.bat`, 9. Deployment Files

### Community 36 - "README.md"
Cohesion: 0.40
Nodes (4): External Webhooks & Telemetry, Required: Postgres connection (no default), Risk Matrix & Treasury Parameters, Upstox API Credentials

### Community 37 - "14. API Integration & Authentication"
Cohesion: 0.67
Nodes (3): 14.1 Upstox API Endpoints, 14.2 Token Management Strategy, 14. API Integration & Authentication

### Community 38 - "15. Deployment Architecture"
Cohesion: 0.67
Nodes (3): 15. Deployment Architecture, Container Architecture, Port Mapping

### Community 39 - "6. Config Module (`config/`)"
Cohesion: 0.67
Nodes (3): 6.1 `settings.py`, 6.2 `token.json`, 6. Config Module (`config/`)

### Community 41 - "phase_b.py"
Cohesion: 0.06
Nodes (60): load(), DataFrame, date, Point-in-time macro event calendar (Phase A5 of docs/plans/20261017-next-…, Add `session`: the first NSE trading day whose close reflects the event (null…, with_session(), constant_maturity(), ATM IV at a fixed horizon by linear interpolation in total variance (v^2 t)… (+52 more)

### Community 42 - "metrics.py"
Cohesion: 0.19
Nodes (18): after_tax_pnl(), benchmark_cagr(), bootstrap_ci(), _cagr(), _fy(), max_drawdown(), profit_factor(), date (+10 more)

### Community 43 - "bhavcopy.py"
Cohesion: 0.07
Nodes (47): fetch_day(), load(), _load_manifest(), parse(), DataFrame, date, Path, Session (+39 more)

### Community 45 - "test_sizing.py"
Cohesion: 0.17
Nodes (18): Risk-based position sizing shared by the live/paper bot and the backtest., Lots such that max loss (width - credit) x lot x lots obeys both caps. Returns…, risk_lots(), _chain(), _enter(), lots(), Risk-based sizing (core/sizing.py) and its wiring into the paper path., test_boundary_exact_fit() (+10 more)

### Community 46 - "PCSParams"
Cohesion: 0.06
Nodes (75): PCSParams, analyse(), _black_swan(), _calm_bull(), capital_ceiling(), _covid_crash(), _dead_vol(), _drift() (+67 more)

### Community 47 - "synthetic_spot_path"
Cohesion: 0.24
Nodes (5): Generate trading-day spot + VIX path (no weekends). Offline CI fixture., synthetic_spot_path(), TestCostsReducePnl, TestPcsBacktest, TestStage6Backtest

### Community 48 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.13
Nodes (14): A6 (user "proceed" 2026-10-18) — plan line 83; E4 at plan lines 239-282, Commands, Decisions, E1 (started 2026-10-18 after user "proceed"), E2 (user "proceed" 2026-10-18) — plan lines 128-168, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step (+6 more)

### Community 49 - "test_stage6.py"
Cohesion: 0.24
Nodes (9): fetch_nifty_closes(), _load_cache(), Spot trend filter using SMA (PROF-018). File-cached yfinance Nifty closes., Skip new short puts when spot < SMA(sma_days)., _save_cache(), sma(), trend_allows_entry(), Stage 6 expectancy helpers: IVR, events, trend, exit defaults. (+1 more)

### Community 50 - "HANDOFF — TP retune 0.50 -> 0.25 + deploy"
Cohesion: 0.20
Nodes (9): Commands, Decisions (and why), Goal, HANDOFF — TP retune 0.50 -> 0.25 + deploy, Key files, Next step, Open questions / risks, Status (+1 more)

### Community 51 - "scheduler.py"
Cohesion: 0.12
Nodes (26): Notifier, _check_missed_entry(), _live_access_token(), _notify_ws_fallback(), _on_ws_connected(), _on_ws_runtime_error(), Tear down and reconnect with a fresh token. Scheduled Mon–Fri 08:55 IST…, Refresh the WS monitor's thresholds and subscriptions after position changes. (+18 more)

### Community 52 - "e1_inclusion.py"
Cohesion: 0.14
Nodes (27): equity_delivery_fees(), Rupee cost of one delivery round trip of one scrip: brokerage, STT (both…, bootstrap(), costed(), drops(), events(), hold(), portfolio() (+19 more)

### Community 53 - "Task: Take nifty-theta-engine from "paper experiment" to "evidence-backed or killed""
Cohesion: 0.18
Nodes (10): Context, Hard rules, How to report, Phase 0: Inventory (no code changes), Phase 1: Correctness and safety fixes, Phase 2: Real historical option data, Phase 3: Pre-registered backtest on real prices, Phase 4: Only if Phase 3 passes (+2 more)

### Community 54 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.29
Nodes (6): Decisions, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Plan for A2 (next), Status

### Community 55 - "HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)"
Cohesion: 0.33
Nodes (5): Goal, Gotchas, HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed), Next, Status

### Community 56 - "report"
Cohesion: 0.07
Nodes (57): check_gaps(), fetch(), fetch_tbill(), load(), _num(), parse(), parse_tbill(), path() (+49 more)

### Community 57 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.13
Nodes (14): A6 (user "proceed" 2026-10-18) — plan line 83; E4 at plan lines 239-282, Commands, Decisions, E1 (started 2026-10-18 after user "proceed"), E2 (user "proceed" 2026-10-18) — plan lines 128-168, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step (+6 more)

### Community 58 - "corp_actions.py"
Cohesion: 0.07
Nodes (61): range, adjust(), annotate(), build(), day_factors(), ex_check(), fetch(), filings_near() (+53 more)

### Community 59 - "Pre-registration v2: Bull Put Credit Spread on real Nifty chains"
Cohesion: 0.15
Nodes (12): 0. Honest status of the evidence, 10. Amendment A3 (2026-10-17, engine data-semantics defect; found while sanity-checking the first v2 DEV output, before OOS), 1. Hypothesis, 2. Grid (32 configs), 3. DEV winner rule (as v1 §4, same thresholds), 4. OOS, 5. Metrics, 6. Frozen PASS criteria (OOS, winner; ALL must hold) (+4 more)

### Community 60 - "iv.py"
Cohesion: 0.16
Nodes (20): black76(), delta(), expiry_row(), implied_vol(), DataFrame, date, EOD implied-vol surface from bhavcopy `close` (Phase A2 of…, Bisection on [1%, 300%]. None outside no-arbitrage bounds (price <= intrinsic… (+12 more)

### Community 61 - "Equity and futures hypotheses (E1–E4): research plan and pre-registration"
Cohesion: 0.17
Nodes (11): 0. Ground rules, A0. Feasibility probe (done 2026-10-17), A-tasks, Amendments, Decision points for the user, E1 — index-inclusion drift (₹2L), E2 — cross-sectional momentum with our own filters (₹2L), E3 — trend-following on futures (₹20L) (+3 more)

### Community 62 - "Next hypotheses after the PCS FAIL — research plan"
Cohesion: 0.17
Nodes (11): 0. Ground rules (lessons from PCS v1/v2), Common steps for each surviving hypothesis, H1 — Volatility-timed short premium, H2 — Event-driven structures, H3 — Buying volatility, Next hypotheses after the PCS FAIL — research plan, Order and stop points, Phase A — shared infrastructure (all three hypotheses need it) (+3 more)

### Community 63 - "run_dev.py"
Cohesion: 0.26
Nodes (10): Config, grid(), Pre-registered v2 DEV grid (docs/plans/20261017-real-chain-pcs-…, eligible(), evaluate(), grid(), Pre-registered DEV grid (docs/plans/20261016-real-chain-pcs-preregistration.md…, index_series() (+2 more)

### Community 64 - "Pre-registration: Bull Put Credit Spread on real Nifty option chains"
Cohesion: 0.18
Nodes (10): 1. Windows (fixed), 2. Strategy and engine rules (all fixed), 3. Grid (54 configs = the multiple-comparison trial count), 4. DEV winner rule, 5. Metrics reported (every run), 6. Frozen PASS criteria (OOS, winner config; ALL must hold), 7. After the result, 8. Known limitations (declared up front) (+2 more)

### Community 65 - "Phase B measurement result — DEV 2019–2023 — all three hypotheses FAIL"
Cohesion: 0.22
Nodes (8): B1 — unconditional variance risk premium, B2 — conditional on signals known at entry (short proxy, pts, mean [98.3% CI]), B3 — events, Caveats, How it was measured, Phase B measurement result — DEV 2019–2023 — all three hypotheses FAIL, Verdict, What this means

### Community 66 - "HANDOFF — Phase B measurement study (docs/plans/20261017-next-hypotheses-plan.md)"
Cohesion: 0.29
Nodes (6): Commands, Decisions, Goal, HANDOFF — Phase B measurement study (docs/plans/20261017-next-hypotheses-plan.md), Next step, Status

### Community 67 - "HANDOFF — E1–E4 equity/futures research plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.29
Nodes (6): A0 probe facts, Decisions, Goal, Gotchas, HANDOFF — E1–E4 equity/futures research plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Status

### Community 68 - "DEV result: real-chain Bull Put Credit Spread (pre-registration d4dfd86 + amendment A1)"
Cohesion: 0.29
Nodes (6): Caveats, Decision needed (user), DEV result: real-chain Bull Put Credit Spread (pre-registration d4dfd86 + amendment A1), Interpretation (not a rescue), Verdict: FAIL on DEV — OOS was NOT run (and per §4 never will be for this registration), What the numbers say (slip 0.5, DEV 2019–2023, ₹20L equity, 2% risk)

### Community 69 - "HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)"
Cohesion: 0.33
Nodes (5): Goal, Gotchas, HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed), Next, Status

### Community 70 - "HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)"
Cohesion: 0.33
Nodes (5): Goal, Gotchas, HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed), Next, Status

### Community 71 - "HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed)"
Cohesion: 0.33
Nodes (5): Decisions, Goal, HANDOFF — 20261016_plan.md (PCS engine: evidence-backed or killed), Next, Status

### Community 72 - "HANDOFF — Phase A infra for docs/plans/20261017-next-hypotheses-plan.md"
Cohesion: 0.33
Nodes (5): Commands, Goal, HANDOFF — Phase A infra for docs/plans/20261017-next-hypotheses-plan.md, Next step, Status (all UNCOMMITTED; commit hook needs independent-evaluator PASS naming every file)

### Community 73 - "HANDOFF — Phase A infra for docs/plans/20261017-next-hypotheses-plan.md"
Cohesion: 0.33
Nodes (5): Commands, Goal, HANDOFF — Phase A infra for docs/plans/20261017-next-hypotheses-plan.md, Next step, Status (UNCOMMITTED; the commit hook needs an evaluator PASS whose transcript has a diff header for every dirty file)

### Community 74 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.33
Nodes (5): Decisions, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Status

### Community 75 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.33
Nodes (5): Decisions, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Status

### Community 76 - "Real-chain PCS v2 — OOS result: **FAIL**"
Cohesion: 0.50
Nodes (3): Known defect in the runner (does not change the verdict), Reading, Real-chain PCS v2 — OOS result: **FAIL**

### Community 77 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.14
Nodes (13): Commands, Decisions, E1 (started 2026-10-18 after user "proceed"), E2 (user "proceed" 2026-10-18) — plan lines 128-168, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Round 3 (aa7a555a6326acdec) = FINDINGS → review cap reached; STOPPED, reported to user, nothing committed (+5 more)

### Community 79 - "backtest.py"
Cohesion: 0.13
Nodes (26): Any, BacktestResult, bs_put_delta(), bs_put_price(), _cost_to_close(), fetch_historical_data(), fetch_nifty_vix_path(), main() (+18 more)

### Community 80 - "test_auth.py"
Cohesion: 0.15
Nodes (6): Redis-first Upstox token resolution., A wrong/missing REDIS_PASSWORD must not look like an outage: the outage…, Two bots share one Upstox login — a second TOTP would kill the winner's session., TestAuthenticatePrefersRedis, TestCrossBotRefreshLock, TestRedisPassword

### Community 81 - "engine.py"
Cohesion: 0.17
Nodes (21): entry_days(), _expiry_value(), _fees(), forward(), _px(), DataFrame, date, Real-chain Bull Put Credit Spread backtest engine (Phase 3). Built and tested… (+13 more)

### Community 82 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.18
Nodes (10): Commands, Decisions, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Round 3 (aa7a555a6326acdec) = FINDINGS → review cap reached; STOPPED, reported to user, nothing committed, Round 4 (a6ce901bf4dba0199) = FINDINGS (round-3 items all verified fixed) → STOPPED, asked user, Status (+2 more)

### Community 83 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.29
Nodes (6): Decisions (and why), Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Status, Tried and failed

### Community 84 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.22
Nodes (8): Commands, Decisions, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Round 3 (aa7a555a6326acdec) = FINDINGS → review cap reached; STOPPED, reported to user, nothing committed, Status, Tried and failed

### Community 85 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.25
Nodes (7): Decisions, Findings so far, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Status, Tried and failed

### Community 86 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.29
Nodes (6): Decisions, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Status, Update 13:5x — T-bill committed 879452a (pushed, user told). Now: permanent stock ID

### Community 87 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.25
Nodes (7): Decisions, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Parser fixes since run1, Status, Tried and failed

### Community 88 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.25
Nodes (7): Decisions, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Parser fixes since run1, Status, Tried and failed

### Community 89 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.29
Nodes (6): Decisions (and why), Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Status, Tried and failed

### Community 90 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.29
Nodes (6): Decisions (and why), Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Status, Tried and failed

### Community 91 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.29
Nodes (6): Decisions (and why), Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Status, Tried and failed

### Community 93 - "Settings"
Cohesion: 0.06
Nodes (24): nifty_lot_size(), Lot size the live bot would actually trade, from the same instruments master.…, BaseSettings, lot_size_from_master(), Read the current F&O lot size for `symbol` from the Upstox instruments master.…, Map VIX → (action, otm_pct). action: 'enter' | 'skip' - None VIX → enter at…, Settings, vix_regime_otm() (+16 more)

### Community 94 - "test_exit_sequencing.py"
Cohesion: 0.14
Nodes (10): _quoted_chain(), Tests for sequenced exit legs (cover-first) and real-fill P&L accuracy. Exit…, Chain whose target spread has a known mid/natural gap. Short 21700 (bid 50 /…, PROF-022: the half-spread must be observable without an entry firing., A resting ask of exactly 0.0 on the short leg must average into mid, not be…, PROF-022: paper entry must not record 0.00 slippage by measuring mid against…, Verify exits place BTC (buy short) first, then STC (sell hedge)., TestExitLegSequencing (+2 more)

### Community 95 - ".check_exits"
Cohesion: 0.22
Nodes (5): Handle a real-time LTP tick. Debounces breach detection. Strike touch is this…, Execute a sequenced exit: buy-to-close short FIRST, then sell-to-close hedge.…, Evaluate active positions for Take Profit, Stop Loss, and Time Stop conditions., Saves the state for a specific symbol to the PostgreSQL database., Ensures that a symbol has the default state initialized. If it doesn't exist in…

### Community 96 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.15
Nodes (12): Commands, Decisions, E1 (started 2026-10-18 after user "proceed"), Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Round 3 (aa7a555a6326acdec) = FINDINGS → review cap reached; STOPPED, reported to user, nothing committed, Round 4 (a6ce901bf4dba0199) = FINDINGS (round-3 items all verified fixed) → STOPPED, asked user (+4 more)

### Community 97 - "HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)"
Cohesion: 0.17
Nodes (11): Commands, Decisions, Goal, HANDOFF — Phase A of E1–E4 plan (docs/plans/20261017-equity-futures-hypotheses-plan.md), Next step, Round 3 (aa7a555a6326acdec) = FINDINGS → review cap reached; STOPPED, reported to user, nothing committed, Round 4 (a6ce901bf4dba0199) = FINDINGS (round-3 items all verified fixed) → STOPPED, asked user, Status (+3 more)

### Community 98 - "TestFillQualityCapture"
Cohesion: 0.18
Nodes (6): Points per leg given up on entry versus the mid we quoted against. Positive =…, PROF-022: realized slippage must survive to trade_history, not just stdout., No mid baseline available -> record no measurement, not a degraded number that…, PROF-022: paper exit must not record 0.00 by comparing natural against itself.…, A resting bid of exactly 0.0 is routine on near-worthless TP puts near expiry —…, TestFillQualityCapture

### Community 99 - "test_costs.py"
Cohesion: 0.31
Nodes (7): date, _round_strike(), _select_strikes(), Tests for the round-trip cost model (config/settings.round_trip_fees) and the…, The backtest's strike search must scan the same OTM band as the live bot's…, test_equity_delivery_fees_dated(), TestStrikeBandParity

### Community 100 - "._select_target_put"
Cohesion: 0.22
Nodes (4): DataFrame, Record the quoted half-spread on the strikes we would trade, without trading.…, Black–Scholes put delta (r=0) using India VIX as σ proxy. Returns value in [-1,…, Select short/long put by target-delta + min credit/width with liquidity guards.…

### Community 101 - "in_event_blackout"
Cohesion: 0.29
Nodes (5): in_event_blackout(), date, True if ``on`` falls within [event - before, event + after] for any event., Guards the calendar data, not the window logic — the Oct 2026 date was wrong…, TestEventBlackout

### Community 102 - "put_delta"
Cohesion: 0.70
Nodes (5): _ncdf(), _put(), put_delta(), |delta| of a put from its price (Black-76, r=0). None if the price cannot be…, test_put_delta_roundtrip()

### Community 103 - "main.py"
Cohesion: 0.67
Nodes (3): main(), Run a simulated paper trade or live trade., run_trade()

## Knowledge Gaps
- **368 isolated node(s):** `indian-trading-bot`, `Goal`, `Status`, `Decisions`, `Tried and failed` (+363 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `UpstoxClient` connect `UpstoxClient` to `TestFillQualityCapture`, `WheelStateMachine`, `patch`, `main.py`, `datetime`, `test_auth.py`, `scheduler.py`, `TestAvailableMargin`, `dashboard.py`, `test_exit_sequencing.py`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Why does `SmartMoneyFilter` connect `SmartMoneyFilter` to `main.py`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `WebSocketMonitor` connect `WebSocketMonitor` to `TestWebSocketMonitor`, `datetime`, `TestExitThresholdCache`, `TestActiveInstrumentKeys`, `scheduler.py`, `TestDebouncedRealtimeTick`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `UpstoxClient` (e.g. with `WheelStateMachine` and `TestAuthenticatePrefersRedis`) actually correct?**
  _`UpstoxClient` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `WheelStateMachine` (e.g. with `UpstoxClient` and `Notifier`) actually correct?**
  _`WheelStateMachine` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `PCSParams` (e.g. with `Scenario` and `TestCostsReducePnl`) actually correct?**
  _`PCSParams` has 15 INFERRED edges - model-reasoned connections that need verification._
- **What connects `indian-trading-bot`, `Goal`, `Status` to the rest of the system?**
  _368 weakly-connected nodes found - possible documentation gaps or missing edges._