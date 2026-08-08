# Graph Report - nifty-theta-engine  (2026-08-06)

## Corpus Check
- 44 files · ~37,592 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 690 nodes · 1162 edges · 41 communities (37 shown, 4 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 63 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `df37e00f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- backtest.py
- UpstoxClient
- WebSocketMonitor
- WheelStateMachine
- auth.py
- test_exit_sequencing.py
- SmartMoneyFilter
- scheduler.py
- ._get_instrument_token
- TestStartWsMonitor
- vix_regime_otm
- ivr.py
- conftest.py
- Settings
- Nifty Theta Engine
- patch
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

## God Nodes (most connected - your core abstractions)
1. `UpstoxClient` - 50 edges
2. `WheelStateMachine` - 48 edges
3. `PCSParams` - 28 edges
4. `run_pcs_backtest()` - 23 edges
5. `Settings` - 21 edges
6. `WebSocketMonitor` - 21 edges
7. `Nifty Theta Engine - Repository Analysis Document` - 19 edges
8. `TestWebSocketMonitor` - 17 edges
9. `round_trip_fees()` - 16 edges
10. `synthetic_spot_path()` - 15 edges

## Surprising Connections (you probably didn't know these)
- `TestRoundTripFees` --uses--> `PCSParams`  [INFERRED]
  tests/test_costs.py → backtest.py
- `TestExitParameterization` --uses--> `PCSParams`  [INFERRED]
  tests/test_profitability.py → backtest.py
- `TestSettingsProfitDefaults` --uses--> `PCSParams`  [INFERRED]
  tests/test_profitability.py → backtest.py
- `TestVixRegimeMapping` --uses--> `PCSParams`  [INFERRED]
  tests/test_profitability.py → backtest.py
- `TestIVR` --uses--> `PCSParams`  [INFERRED]
  tests/test_stage6.py → backtest.py

## Import Cycles
- None detected.

## Communities (41 total, 4 thin omitted)

### Community 0 - "backtest.py"
Cohesion: 0.05
Nodes (56): Any, BacktestResult, bs_put_delta(), bs_put_price(), _cost_to_close(), fetch_historical_data(), fetch_nifty_vix_path(), main() (+48 more)

### Community 1 - "UpstoxClient"
Cohesion: 0.25
Nodes (6): UpstoxClient, TestOrderStatusWithDynamicIds, TestOrderType, TestPaperOrderIds, Tests for UpstoxClient.get_order_fill_price()., TestGetOrderFillPrice

### Community 2 - "WebSocketMonitor"
Cohesion: 0.06
Nodes (13): Real-time LTP monitor using the Upstox SDK's MarketDataStreamerV3. The SDK…, SDK exhausted its retries — this is the real 'we are offline' signal., Record the desired subscription set and apply it if the socket is up., Socket up (first connect or SDK auto-reconnect) — resubscribe from scratch., WebSocketMonitor, Tests for the SDK-backed WebSocketMonitor wrapper., Tests for WheelStateMachine.active_instrument_keys()., Tests for the in-memory exit threshold cache. (+5 more)

### Community 3 - "WheelStateMachine"
Cohesion: 0.07
Nodes (21): DataFrame, date, Returns all instrument keys that should be monitored in real-time., Populate/refresh the in-memory exit threshold cache from current state., Handle a real-time LTP tick. Debounces breach detection. Strike touch is this…, Loads state from the PostgreSQL database and parses it into the nested…, Execute a sequenced exit: buy-to-close short FIRST, then sell-to-close hedge.…, Evaluate active positions for Take Profit, Stop Loss, and Time Stop conditions. (+13 more)

### Community 4 - "auth.py"
Cohesion: 0.07
Nodes (32): get_redis_client(), _acquire_refresh_lock(), authenticate_and_save_token(), _delete_centralized_token(), get_centralized_token(), get_current_timestamp(), _mirror_token_locally(), Keep local token.json in sync with the shared bus. (+24 more)

### Community 5 - "test_exit_sequencing.py"
Cohesion: 0.11
Nodes (22): _make_active_state(), _make_tp_chain(), patch, Tests for sequenced exit legs (cover-first) and real-fill P&L accuracy. Exit…, If BTC order times out (stays pending), cancel it and keep the spread., If BTC order is rejected by exchange, keep the spread intact., When BTC fills but STC fails, short is covered — only a benign long put remains., BTC fills, STC placement fails → archive trade, alert about residual long put. (+14 more)

### Community 6 - "SmartMoneyFilter"
Cohesion: 0.11
Nodes (16): get_nifty500_tickers(), Fetches the latest Nifty 500 tickers from NSE indices CSV., DataFrame, date, Fetches Nifty 500 metadata from yfinance and caches it., Attempt to fetch deals using jugaad-data., Attempt to fetch deals using direct HTTP requests to NSE archives., Attempt to fetch deals using Playwright. (+8 more)

### Community 7 - "scheduler.py"
Cohesion: 0.06
Nodes (35): Macro / NSE event blackout calendar for PCS entry skips (PROF-018). Dates are…, Total rupee cost of one spread round trip: brokerage + STT + txn + GST.…, round_trip_fees(), Notifier, _check_missed_entry(), _live_access_token(), _notify_ws_fallback(), _on_ws_connected() (+27 more)

### Community 8 - "._get_instrument_token"
Cohesion: 0.13
Nodes (8): DataFrame, Download/refresh the Upstox NSE instruments master (24h TTL, lock-protected).…, Current F&O lot size for `symbol`, straight from the instruments master. There…, Looks up the real instrument token from the Upstox NSE equities master file.…, Fetches the last traded price for the given symbol., Places an order or routes a paper trade., Places an order or routes a paper trade using an instrument key., Fetches the option chain for a given symbol and optional expiry date. Returns a…

### Community 9 - "TestStartWsMonitor"
Cohesion: 0.10
Nodes (8): Tests for scheduler WebSocket start gating and Discord fallback alerts., Only a real socket open clears the flag — and tells Discord we're back., Hourly re-arm retries must not fire a Discord alert per attempt., Overnight-expired token must be refreshed before the WS handshake., _reset_ws_state(), TestLiveAccessToken, TestRestartWsMonitor, TestStartWsMonitor

### Community 10 - "vix_regime_otm"
Cohesion: 0.39
Nodes (3): Map VIX → (action, otm_pct). action: 'enter' | 'skip' - None VIX → enter at…, vix_regime_otm(), TestVixRegimeMapping

### Community 11 - "ivr.py"
Cohesion: 0.16
Nodes (14): compute_ivr(), _ensure_data_dir(), fetch_india_vix_history(), ivr_allows_entry(), load_cached_vix_closes(), India VIX percentile (IVR) helper with short-TTL file cache. Used by entry…, Return (allowed, ivr, reason)., Return percentile of current_vix within history (0–100). None if insufficient… (+6 more)

### Community 12 - "conftest.py"
Cohesion: 0.25
Nodes (10): fixture, mock_client(), mock_db_pool(), mock_notifier(), Keep Stage-6 entry filters from blocking unit tests (unless a test overrides)., Provides a mock UpstoxClient that returns controllable values., Provides a mock connection pool., Provides a WheelStateMachine with all external dependencies mocked. (+2 more)

### Community 13 - "Settings"
Cohesion: 0.10
Nodes (16): nifty_lot_size(), Lot size the live bot would actually trade, from the same instruments master.…, BaseSettings, lot_size_from_master(), Read the current F&O lot size for `symbol` from the Upstox instruments master.…, Settings, patch, STOP_ON_STRIKE_TOUCH=False must not exit on a touch, but the credit multiple… (+8 more)

### Community 14 - "Nifty Theta Engine"
Cohesion: 0.05
Nodes (35): Architectural Audit, Data Persistence & Schema (PostgreSQL), Infrastructure Topology (docker-compose.yml), Orchestration (core/scheduler.py), The Execution Engine (strategies/wheel_strategy.py), The ML Pipeline (ml_service/) — historical / not wired to live entry, Architecture, Commands (+27 more)

### Community 15 - "patch"
Cohesion: 0.21
Nodes (6): patch, When Leg 2 placement fails, Leg 1 should be unwound., Verify budget is derived from margin, not hardcoded., TestExitVerification, TestHedgeUnwinding, TestPositionSizing

### Community 23 - "Enhancements"
Cohesion: 0.06
Nodes (36): Critical, ENH-001: No test suite — FIXED, ENH-002: No position reconciliation on startup — FIXED, ENH-003: No concurrency guard against double-entry — FIXED, ENH-004: Pure MARKET exits risk slippage on illiquid strikes — FIXED, ENH-005: No real-time WebSocket monitoring — FIXED, ENH-006: No config validation — FIXED, ENH-007: No CI/CD pipeline — FIXED (+28 more)

### Community 24 - "Profitability Roadmap"
Cohesion: 0.06
Nodes (33): Chosen defaults (after Stage 6), PROF-001: Formalize ₹50k capital ceiling, PROF-002: Sync strategy docs to actual code, PROF-003: Enable real-time exits in paper mode, PROF-004: Discord alert on WebSocket fallback, PROF-005: PCS backtest harness matching live rules, PROF-006: Parameterize TP / SL / time-stop / DTE manage, PROF-007: Sweep and pick default exit params under ₹50k (+25 more)

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

## Knowledge Gaps
- **130 isolated node(s):** `deploy.sh script`, `indian-trading-bot`, `Table of Contents`, `1. Project Overview`, `2. Directory Structure` (+125 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `UpstoxClient` connect `UpstoxClient` to `TestAvailableMargin`, `WheelStateMachine`, `auth.py`, `test_exit_sequencing.py`, `scheduler.py`, `._get_instrument_token`, `test_auth.py`, `dashboard.py`?**
  _High betweenness centrality (0.142) - this node is a cross-community bridge._
- **Why does `WheelStateMachine` connect `WheelStateMachine` to `backtest.py`, `UpstoxClient`, `test_exit_sequencing.py`, `scheduler.py`, `conftest.py`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Why does `WebSocketMonitor` connect `WebSocketMonitor` to `TestDebouncedRealtimeTick`, `scheduler.py`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `UpstoxClient` (e.g. with `WheelStateMachine` and `TestAuthenticatePrefersRedis`) actually correct?**
  _`UpstoxClient` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `WheelStateMachine` (e.g. with `UpstoxClient` and `Notifier`) actually correct?**
  _`WheelStateMachine` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `PCSParams` (e.g. with `TestCostsReducePnl` and `TestRoundTripFees`) actually correct?**
  _`PCSParams` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `Settings` (e.g. with `TestExitParameterization` and `TestMidweekEntry`) actually correct?**
  _`Settings` has 13 INFERRED edges - model-reasoned connections that need verification._