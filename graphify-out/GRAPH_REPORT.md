# Graph Report - nifty-theta-engine  (2026-08-05)

## Corpus Check
- 43 files · ~33,206 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 647 nodes · 1049 edges · 41 communities (35 shown, 6 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 49 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `60273127`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- backtest.py
- UpstoxClient
- WebSocketMonitor
- WheelStateMachine
- auth.py
- _make_active_state
- SmartMoneyFilter
- scheduler.py
- test_wheel_strategy.py
- TestStartWsMonitor
- vix_regime_otm
- ivr.py
- conftest.py
- TestExitParameterization
- Nifty Theta Engine
- init_nifty_schema.sql
- deploy.sh script
- indian-trading-bot
- Enhancements
- Profitability Roadmap
- Nifty Theta Engine - Repository Analysis Document
- test_auth.py
- 5.1 `wheel_strategy.py` - Wheel Strategy State Machine
- test_exit_sequencing.py
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
1. `UpstoxClient` - 47 edges
2. `WheelStateMachine` - 36 edges
3. `PCSParams` - 22 edges
4. `WebSocketMonitor` - 21 edges
5. `run_pcs_backtest()` - 20 edges
6. `Settings` - 20 edges
7. `Nifty Theta Engine - Repository Analysis Document` - 19 edges
8. `TestWebSocketMonitor` - 17 edges
9. `authenticate_and_save_token()` - 15 edges
10. `SmartMoneyFilter` - 15 edges

## Surprising Connections (you probably didn't know these)
- `TestExitParameterization` --uses--> `PCSParams`  [INFERRED]
  tests/test_profitability.py → backtest.py
- `TestVixRegimeMapping` --uses--> `PCSParams`  [INFERRED]
  tests/test_profitability.py → backtest.py
- `TestIVR` --uses--> `PCSParams`  [INFERRED]
  tests/test_stage6.py → backtest.py
- `TestExitParameterization` --uses--> `Settings`  [INFERRED]
  tests/test_profitability.py → config/settings.py
- `TestVixRegimeMapping` --uses--> `Settings`  [INFERRED]
  tests/test_profitability.py → config/settings.py

## Import Cycles
- None detected.

## Communities (41 total, 6 thin omitted)

### Community 0 - "backtest.py"
Cohesion: 0.05
Nodes (56): Any, BacktestResult, bs_put_delta(), bs_put_price(), _cost_to_close(), fetch_historical_data(), fetch_nifty_vix_path(), main() (+48 more)

### Community 1 - "UpstoxClient"
Cohesion: 0.10
Nodes (13): Fetches available cash/equity margin for position sizing. Mock market returns a…, Fetches current open positions from Upstox., Fetches the status of a specific order., Fetches the current India VIX to serve as a market panic circuit breaker., Initialize with Redis-first token resolution (see authenticate_and_save_token).…, Returns the average fill price for a completed order, or None., Cancels an open order on the Upstox exchange., UpstoxClient (+5 more)

### Community 2 - "WebSocketMonitor"
Cohesion: 0.05
Nodes (18): Real-time LTP monitor using the Upstox SDK's MarketDataStreamerV3. The SDK…, SDK exhausted its retries — this is the real 'we are offline' signal., Record the desired subscription set and apply it if the socket is up., Socket up (first connect or SDK auto-reconnect) — resubscribe from scratch., WebSocketMonitor, Tests for the real-time WebSocket exit monitor and debounced tick handler., Tests for the SDK-backed WebSocketMonitor wrapper., Tests for WheelStateMachine.active_instrument_keys(). (+10 more)

### Community 3 - "WheelStateMachine"
Cohesion: 0.09
Nodes (18): DataFrame, date, Execute a sequenced exit: buy-to-close short FIRST, then sell-to-close hedge.…, Evaluate active positions for Take Profit, Stop Loss, and Time Stop conditions., Saves the state for a specific symbol to the PostgreSQL database., Compares DB state against broker positions on startup. Alerts on mismatches., Ensures that a symbol has the default state initialized. If it doesn't exist in…, Initializes the Wheel Strategy State Machine. Safely connects to the PostgreSQL… (+10 more)

### Community 4 - "auth.py"
Cohesion: 0.08
Nodes (33): Macro / NSE event blackout calendar for PCS entry skips (PROF-018). Dates are…, get_redis_client(), _acquire_refresh_lock(), authenticate_and_save_token(), _delete_centralized_token(), get_centralized_token(), get_current_timestamp(), _mirror_token_locally() (+25 more)

### Community 5 - "_make_active_state"
Cohesion: 0.15
Nodes (15): _make_active_state(), _make_tp_chain(), patch, If BTC order times out (stays pending), cancel it and keep the spread., If BTC order is rejected by exchange, keep the spread intact., BTC fills, STC placement fails → archive trade, alert about residual long put., Standard STAGE_1_CSP state for exit tests., BTC fills, STC times out → close position (short covered), alert for manual… (+7 more)

### Community 6 - "SmartMoneyFilter"
Cohesion: 0.11
Nodes (16): get_nifty500_tickers(), Fetches the latest Nifty 500 tickers from NSE indices CSV., DataFrame, date, Fetches Nifty 500 metadata from yfinance and caches it., Attempt to fetch deals using jugaad-data., Attempt to fetch deals using direct HTTP requests to NSE archives., Attempt to fetch deals using Playwright. (+8 more)

### Community 7 - "scheduler.py"
Cohesion: 0.13
Nodes (24): Notifier, _check_missed_entry(), _live_access_token(), _notify_ws_fallback(), _on_ws_connected(), _on_ws_runtime_error(), Tear down and reconnect with a fresh token. Scheduled Mon–Fri 08:55 IST…, Refresh the WS monitor's thresholds and subscriptions after position changes. (+16 more)

### Community 8 - "test_wheel_strategy.py"
Cohesion: 0.08
Nodes (10): patch, When Leg 2 placement fails, Leg 1 should be unwound., Verify budget is derived from margin, not hardcoded., TestEnsureSymbolState, TestExitVerification, TestExpiryAutoClose, TestHedgeUnwinding, TestPositionSizing (+2 more)

### Community 9 - "TestStartWsMonitor"
Cohesion: 0.10
Nodes (8): Tests for scheduler WebSocket start gating and Discord fallback alerts., Only a real socket open clears the flag — and tells Discord we're back., Hourly re-arm retries must not fire a Discord alert per attempt., Overnight-expired token must be refreshed before the WS handshake., _reset_ws_state(), TestLiveAccessToken, TestRestartWsMonitor, TestStartWsMonitor

### Community 10 - "vix_regime_otm"
Cohesion: 0.33
Nodes (3): Map VIX → (action, otm_pct). action: 'enter' | 'skip' - None VIX → enter at…, vix_regime_otm(), TestVixRegimeMapping

### Community 11 - "ivr.py"
Cohesion: 0.16
Nodes (14): compute_ivr(), _ensure_data_dir(), fetch_india_vix_history(), ivr_allows_entry(), load_cached_vix_closes(), India VIX percentile (IVR) helper with short-TTL file cache. Used by entry…, Return (allowed, ivr, reason)., Return percentile of current_vix within history (0–100). None if insufficient… (+6 more)

### Community 12 - "conftest.py"
Cohesion: 0.25
Nodes (10): fixture, mock_client(), mock_db_pool(), mock_notifier(), Keep Stage-6 entry filters from blocking unit tests (unless a test overrides)., Provides a mock UpstoxClient that returns controllable values., Provides a mock connection pool., Provides a WheelStateMachine with all external dependencies mocked. (+2 more)

### Community 14 - "Nifty Theta Engine"
Cohesion: 0.05
Nodes (35): Architectural Audit, Data Persistence & Schema (PostgreSQL), Infrastructure Topology (docker-compose.yml), Orchestration (core/scheduler.py), The Execution Engine (strategies/wheel_strategy.py), The ML Pipeline (ml_service/) — historical / not wired to live entry, Architecture, Commands (+27 more)

### Community 23 - "Enhancements"
Cohesion: 0.06
Nodes (36): Critical, ENH-001: No test suite, ENH-002: No position reconciliation on startup, ENH-003: No concurrency guard against double-entry, ENH-004: Pure MARKET exits risk slippage on illiquid strikes, ENH-005: No real-time WebSocket monitoring — FIXED, ENH-006: No config validation — env vars parsed scattered with silent defaults, ENH-007: No CI/CD pipeline (+28 more)

### Community 24 - "Profitability Roadmap"
Cohesion: 0.06
Nodes (31): Chosen defaults (after Stage 6), PROF-001: Formalize ₹50k capital ceiling, PROF-002: Sync strategy docs to actual code, PROF-003: Enable real-time exits in paper mode, PROF-004: Discord alert on WebSocket fallback, PROF-005: PCS backtest harness matching live rules, PROF-006: Parameterize TP / SL / time-stop / DTE manage, PROF-007: Sweep and pick default exit params under ₹50k (+23 more)

### Community 25 - "Nifty Theta Engine - Repository Analysis Document"
Cohesion: 0.15
Nodes (13): 10. Database Schema, 11. Environment Configuration, 12. State Machine Logic, 1. Project Overview, 2. Directory Structure, 7. Dashboard Module (`dashboard.py`), File Summary Table, Full State Transition Diagram (+5 more)

### Community 26 - "test_auth.py"
Cohesion: 0.18
Nodes (5): Redis-first Upstox token resolution., Two bots share one Upstox login — a second TOTP would kill the winner's session., TestAuthenticatePrefersRedis, TestClientInitPrefersAuthResolver, TestCrossBotRefreshLock

### Community 27 - "5.1 `wheel_strategy.py` - Wheel Strategy State Machine"
Cohesion: 0.25
Nodes (8): 5.1 `wheel_strategy.py` - Wheel Strategy State Machine, 5. Strategies Module (`strategies/`), Database Schema (index_spread_state), Execution Sequence (Credit Spread), Exit Conditions, Key Methods, State Machine States, State Transitions

### Community 28 - "test_exit_sequencing.py"
Cohesion: 0.25
Nodes (7): Tests for sequenced exit legs (cover-first) and real-fill P&L accuracy. Exit…, When BTC fills but STC fails, short is covered — only a benign long put remains., P&L must use actual fill prices, not theoretical pre-trade quotes., Verify exits place BTC (buy short) first, then STC (sell hedge)., TestExitLegSequencing, TestRealFillPnl, TestStcFailureAfterBtcFill

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
- **130 isolated node(s):** `deploy.sh script`, `trade_history`, `index_spread_state`, `indian-trading-bot`, `Table of Contents` (+125 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `UpstoxClient` connect `UpstoxClient` to `TestAvailableMargin`, `WheelStateMachine`, `auth.py`, `_make_active_state`, `scheduler.py`, `test_auth.py`, `test_exit_sequencing.py`, `dashboard.py`?**
  _High betweenness centrality (0.160) - this node is a cross-community bridge._
- **Why does `WheelStateMachine` connect `WheelStateMachine` to `UpstoxClient`, `auth.py`, `conftest.py`, `scheduler.py`?**
  _High betweenness centrality (0.085) - this node is a cross-community bridge._
- **Why does `WebSocketMonitor` connect `WebSocketMonitor` to `scheduler.py`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `UpstoxClient` (e.g. with `WheelStateMachine` and `TestAuthenticatePrefersRedis`) actually correct?**
  _`UpstoxClient` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `WheelStateMachine` (e.g. with `UpstoxClient` and `Notifier`) actually correct?**
  _`WheelStateMachine` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `PCSParams` (e.g. with `TestExitParameterization` and `TestMidweekEntry`) actually correct?**
  _`PCSParams` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `WebSocketMonitor` (e.g. with `TestActiveInstrumentKeys` and `TestDebouncedRealtimeTick`) actually correct?**
  _`WebSocketMonitor` has 4 INFERRED edges - model-reasoned connections that need verification._