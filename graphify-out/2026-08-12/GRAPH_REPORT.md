# Graph Report - nifty-theta-engine  (2026-08-07)

## Corpus Check
- 46 files · ~43,381 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 790 nodes · 1369 edges · 44 communities (39 shown, 5 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 69 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `248fee6a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- backtest.py
- UpstoxClient
- WebSocketMonitor
- WheelStateMachine
- PCSParams
- _make_active_state
- SmartMoneyFilter
- settings.py
- ._get_instrument_token
- TestStartWsMonitor
- scheduler.py
- test_stage6.py
- conftest.py
- Settings
- WHEEL_STRATEGY_MANUAL
- patch
- Assert-LastExit
- deploy.sh script
- indian-trading-bot
- Enhancements
- Profitability Roadmap
- Nifty Theta Engine - Repository Analysis Document
- test_auth.py
- 5.1 `wheel_strategy.py` - Wheel Strategy State Machine
- TestDebouncedRealtimeTick
- dashboard.py
- 4. Core Module (`core/`)
- 13. Risk Management & Guardrails
- TestAvailableMargin
- 3. Entry Points
- 8. Backtest Module (`backtest.py`)
- 9. Deployment Files
- README.md
- 14. API Integration & Authentication
- 15. Deployment Architecture
- 6. Config Module (`config/`)
- AGENTS.md
- test_exit_sequencing.py
- Nifty Theta Engine
- TestExitParameterization

## God Nodes (most connected - your core abstractions)
1. `UpstoxClient` - 52 edges
2. `WheelStateMachine` - 52 edges
3. `PCSParams` - 37 edges
4. `run_pcs_backtest()` - 28 edges
5. `Settings` - 21 edges
6. `WebSocketMonitor` - 21 edges
7. `Nifty Theta Engine - Repository Analysis Document` - 19 edges
8. `round_trip_fees()` - 17 edges
9. `TestWebSocketMonitor` - 17 edges
10. `synthetic_spot_path()` - 15 edges

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

## Communities (44 total, 5 thin omitted)

### Community 0 - "backtest.py"
Cohesion: 0.09
Nodes (37): Any, BacktestResult, bs_put_delta(), bs_put_price(), _cost_to_close(), fetch_historical_data(), fetch_nifty_vix_path(), main() (+29 more)

### Community 1 - "UpstoxClient"
Cohesion: 0.10
Nodes (13): Fetches available cash/equity margin for position sizing. Mock market returns a…, Fetches current open positions from Upstox., Fetches the status of a specific order., Fetches the current India VIX to serve as a market panic circuit breaker., Initialize with Redis-first token resolution (see authenticate_and_save_token).…, Returns the average fill price for a completed order, or None., Cancels an open order on the Upstox exchange., UpstoxClient (+5 more)

### Community 2 - "WebSocketMonitor"
Cohesion: 0.06
Nodes (13): Real-time LTP monitor using the Upstox SDK's MarketDataStreamerV3. The SDK…, SDK exhausted its retries — this is the real 'we are offline' signal., Record the desired subscription set and apply it if the socket is up., Socket up (first connect or SDK auto-reconnect) — resubscribe from scratch., WebSocketMonitor, Tests for the SDK-backed WebSocketMonitor wrapper., Tests for WheelStateMachine.active_instrument_keys()., Tests for the in-memory exit threshold cache. (+5 more)

### Community 3 - "WheelStateMachine"
Cohesion: 0.07
Nodes (22): DataFrame, date, Returns all instrument keys that should be monitored in real-time., Populate/refresh the in-memory exit threshold cache from current state., Handle a real-time LTP tick. Debounces breach detection. Strike touch is this…, Execute a sequenced exit: buy-to-close short FIRST, then sell-to-close hedge.…, Loads state from the PostgreSQL database and parses it into the nested…, Evaluate active positions for Take Profit, Stop Loss, and Time Stop conditions. (+14 more)

### Community 4 - "PCSParams"
Cohesion: 0.05
Nodes (77): PCSParams, parametrize, analyse(), _black_swan(), _calm_bull(), capital_ceiling(), _covid_crash(), _dead_vol() (+69 more)

### Community 5 - "_make_active_state"
Cohesion: 0.13
Nodes (19): _make_active_state(), _make_tp_chain(), patch, If BTC order times out (stays pending), cancel it and keep the spread., If BTC order is rejected by exchange, keep the spread intact., When BTC fills but STC fails, short is covered — only a benign long put remains., BTC fills, STC placement fails → archive trade, alert about residual long put., BTC fills, STC times out → close position (short covered), alert for manual… (+11 more)

### Community 6 - "SmartMoneyFilter"
Cohesion: 0.10
Nodes (16): get_nifty500_tickers(), Fetches the latest Nifty 500 tickers from NSE indices CSV., DataFrame, date, Fetches Nifty 500 metadata from yfinance and caches it., Attempt to fetch deals using jugaad-data., Attempt to fetch deals using direct HTTP requests to NSE archives., Attempt to fetch deals using Playwright. (+8 more)

### Community 7 - "settings.py"
Cohesion: 0.06
Nodes (36): Macro / NSE event blackout calendar for PCS entry skips (PROF-018). Dates are…, get_redis_client(), Total rupee cost of one spread round trip: brokerage + STT + txn + GST.…, round_trip_fees(), _acquire_refresh_lock(), authenticate_and_save_token(), _delete_centralized_token(), get_centralized_token() (+28 more)

### Community 8 - "._get_instrument_token"
Cohesion: 0.13
Nodes (8): DataFrame, Download/refresh the Upstox NSE instruments master (24h TTL, lock-protected).…, Current F&O lot size for `symbol`, straight from the instruments master. There…, Looks up the real instrument token from the Upstox NSE equities master file.…, Fetches the last traded price for the given symbol., Places an order or routes a paper trade., Places an order or routes a paper trade using an instrument key., Fetches the option chain for a given symbol and optional expiry date. Returns a…

### Community 9 - "TestStartWsMonitor"
Cohesion: 0.10
Nodes (8): Tests for scheduler WebSocket start gating and Discord fallback alerts., Only a real socket open clears the flag — and tells Discord we're back., Hourly re-arm retries must not fire a Discord alert per attempt., Overnight-expired token must be refreshed before the WS handshake., _reset_ws_state(), TestLiveAccessToken, TestRestartWsMonitor, TestStartWsMonitor

### Community 10 - "scheduler.py"
Cohesion: 0.12
Nodes (26): Notifier, _check_missed_entry(), _live_access_token(), _notify_ws_fallback(), _on_ws_connected(), _on_ws_runtime_error(), Tear down and reconnect with a fresh token. Scheduled Mon–Fri 08:55 IST…, Refresh the WS monitor's thresholds and subscriptions after position changes. (+18 more)

### Community 11 - "test_stage6.py"
Cohesion: 0.08
Nodes (28): in_event_blackout(), date, True if ``on`` falls within [event - before, event + after] for any event., compute_ivr(), _ensure_data_dir(), fetch_india_vix_history(), ivr_allows_entry(), load_cached_vix_closes() (+20 more)

### Community 12 - "conftest.py"
Cohesion: 0.22
Nodes (12): fixture, mock_client(), mock_db_pool(), mock_notifier(), _pin_backtest_lot_size(), Keep Stage-6 entry filters from blocking unit tests (unless a test overrides)., Pin the backtest contract size so tests never depend on a downloaded file.…, Provides a mock UpstoxClient that returns controllable values. (+4 more)

### Community 13 - "Settings"
Cohesion: 0.07
Nodes (21): nifty_lot_size(), Lot size the live bot would actually trade, from the same instruments master.…, BaseSettings, lot_size_from_master(), Read the current F&O lot size for `symbol` from the Upstox instruments master.…, Map VIX → (action, otm_pct). action: 'enter' | 'skip' - None VIX → enter at…, Settings, vix_regime_otm() (+13 more)

### Community 14 - "WHEEL_STRATEGY_MANUAL"
Cohesion: 0.13
Nodes (15): 1. The Strategy Purpose, 2. The State Machine (IDLE -> STAGE_1_CSP -> STAGE_2_CC), 3. Position Sizing & Capital Math, 4. Alpha & Risk Guardrails, 5. Token Orchestration, A. VIX Regime Gate (OTM scaling + hard skip), B. The Bid-Ask Slippage Guardrail, C. Exit Rules (Take Profit / Stop Loss / Time Stop) (+7 more)

### Community 15 - "patch"
Cohesion: 0.21
Nodes (6): patch, When Leg 2 placement fails, Leg 1 should be unwound., Verify budget is derived from margin, not hardcoded., TestExitVerification, TestHedgeUnwinding, TestPositionSizing

### Community 23 - "Enhancements"
Cohesion: 0.04
Nodes (42): Architectural Audit, Data Persistence & Schema (PostgreSQL), Infrastructure Topology (docker-compose.yml), Orchestration (core/scheduler.py), The Execution Engine (strategies/wheel_strategy.py), The ML Pipeline (ml_service/) — historical / not wired to live entry, Critical, ENH-001: No test suite — FIXED (+34 more)

### Community 24 - "Profitability Roadmap"
Cohesion: 0.06
Nodes (35): Chosen defaults (after Stage 6), Minimum viable capital, PROF-001: Formalize ₹50k capital ceiling, PROF-002: Sync strategy docs to actual code, PROF-003: Enable real-time exits in paper mode, PROF-004: Discord alert on WebSocket fallback, PROF-005: PCS backtest harness matching live rules, PROF-006: Parameterize TP / SL / time-stop / DTE manage (+27 more)

### Community 25 - "Nifty Theta Engine - Repository Analysis Document"
Cohesion: 0.15
Nodes (13): 10. Database Schema, 11. Environment Configuration, 12. State Machine Logic, 1. Project Overview, 2. Directory Structure, 7. Dashboard Module (`dashboard.py`), File Summary Table, Full State Transition Diagram (+5 more)

### Community 26 - "test_auth.py"
Cohesion: 0.18
Nodes (5): Redis-first Upstox token resolution., Two bots share one Upstox login — a second TOTP would kill the winner's session., TestAuthenticatePrefersRedis, TestClientInitPrefersAuthResolver, TestCrossBotRefreshLock

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
Cohesion: 0.50
Nodes (3): External Webhooks & Telemetry, Risk Matrix & Treasury Parameters, Upstox API Credentials

### Community 37 - "14. API Integration & Authentication"
Cohesion: 0.67
Nodes (3): 14.1 Upstox API Endpoints, 14.2 Token Management Strategy, 14. API Integration & Authentication

### Community 38 - "15. Deployment Architecture"
Cohesion: 0.67
Nodes (3): 15. Deployment Architecture, Container Architecture, Port Mapping

### Community 39 - "6. Config Module (`config/`)"
Cohesion: 0.67
Nodes (3): 6.1 `settings.py`, 6.2 `token.json`, 6. Config Module (`config/`)

### Community 41 - "test_exit_sequencing.py"
Cohesion: 0.16
Nodes (9): _quoted_chain(), Tests for sequenced exit legs (cover-first) and real-fill P&L accuracy. Exit…, Chain whose target spread has a known mid/natural gap. Short 21700 (bid 50 /…, PROF-022: the half-spread must be observable without an entry firing., PROF-022: paper entry must not record 0.00 slippage by measuring mid against…, Verify exits place BTC (buy short) first, then STC (sell hedge)., TestExitLegSequencing, TestPaperFillsAreNotFree (+1 more)

### Community 42 - "Nifty Theta Engine"
Cohesion: 0.14
Nodes (14): Architecture, Commands, Conventions, Database, Docker Deployment, Environment Variables, graphify, Key Design Decisions (+6 more)

### Community 43 - "TestExitParameterization"
Cohesion: 0.51
Nodes (3): patch, STOP_ON_STRIKE_TOUCH=False must not exit on a touch, but the credit multiple…, TestExitParameterization

## Knowledge Gaps
- **131 isolated node(s):** `deploy.sh script`, `indian-trading-bot`, `Table of Contents`, `1. Project Overview`, `2. Directory Structure` (+126 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `UpstoxClient` connect `UpstoxClient` to `TestAvailableMargin`, `WheelStateMachine`, `_make_active_state`, `settings.py`, `._get_instrument_token`, `test_exit_sequencing.py`, `scheduler.py`, `test_auth.py`, `dashboard.py`?**
  _High betweenness centrality (0.130) - this node is a cross-community bridge._
- **Why does `WheelStateMachine` connect `WheelStateMachine` to `backtest.py`, `UpstoxClient`, `_make_active_state`, `settings.py`, `test_exit_sequencing.py`, `scheduler.py`, `conftest.py`?**
  _High betweenness centrality (0.108) - this node is a cross-community bridge._
- **Why does `WebSocketMonitor` connect `WebSocketMonitor` to `scheduler.py`, `TestDebouncedRealtimeTick`, `settings.py`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `UpstoxClient` (e.g. with `WheelStateMachine` and `TestAuthenticatePrefersRedis`) actually correct?**
  _`UpstoxClient` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `WheelStateMachine` (e.g. with `UpstoxClient` and `Notifier`) actually correct?**
  _`WheelStateMachine` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `PCSParams` (e.g. with `Scenario` and `TestCostsReducePnl`) actually correct?**
  _`PCSParams` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `Settings` (e.g. with `TestExitParameterization` and `TestMidweekEntry`) actually correct?**
  _`Settings` has 13 INFERRED edges - model-reasoned connections that need verification._