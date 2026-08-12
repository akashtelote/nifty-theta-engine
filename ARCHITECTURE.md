# Architectural Audit

This document serves as a living audit of the current production state of the codebase, covering infrastructure topology, data persistence, machine learning pipelines, execution strategies, and orchestration.

## Infrastructure Topology (docker-compose.yml)

- **Container Network:** The project utilizes a Docker Compose setup with three main services running on a shared bridge network.
- **Services:**
  - `postgres_db`: A `postgres:15-alpine` container providing the state persistence layer. It is protected within the network (no exposed host ports) and includes a health check to ensure readiness before dependent services start.
  - `upstox_wheel_bot`: The core execution engine. It builds the base image `upstox_wheel_base:latest` from the local `Dockerfile`.
  - `dashboard`: The Streamlit analytics dashboard running on port 8501.
- **Image Caching & Build Process:**
  - The `upstox_wheel_bot` service uses the `build` directive to compile the Dockerfile and tags the resulting image as `upstox_wheel_base:latest`.
  - The `dashboard` service specifically **does not** include a build block; instead, it explicitly uses the `upstox_wheel_base:latest` image.
  - The `depends_on` structure enforces that `upstox_wheel_bot` must start (and build the image) before `dashboard` attempts to spin up, preventing double-builds and ensuring cache reuse. Both services wait for `postgres_db` to become `service_healthy`.

## Data Persistence & Schema (PostgreSQL)

- **State Persistence:** We migrated from SQLite to a dedicated PostgreSQL database container to handle state management and prevent file-locking bottlenecks.
- **Concurrency & MVCC:** Standard `psycopg2-binary` connections handle read/write operations. Because PostgreSQL natively supports **Multi-Version Concurrency Control (MVCC)**, the bot can constantly write updates to the strategy state while the dashboard can concurrently read data for real-time reporting without locking or blocking each other.
- **Schema Design:** The `wheel_state` table uses a **flat schema** keyed by ticker `symbol`. Fields include:
  - `current_stage`
  - Option legs: `instrument_key`, `strike_price`, `expiry`, `trade_date`, `entry_price`, `order_id`
  - Hedge legs: `hedge_instrument_key`, `hedge_strike_price`, `hedge_entry_price`, `hedge_order_id`
  - Inventory tracking: `assigned_shares`, `average_cost_basis`
  - Accounting: `lifetime_realized_pnl` (cumulative across all closed trades for the symbol, not just the current one — per-trade P&L lives in `trade_history.realized_pnl`)
- **Application Parsing:** Within `strategies/wheel_strategy.py`, the flat SQL records are packed/unpacked into a nested Python dictionary to maintain strategy logic compatibility.

## The ML Pipeline (ml_service/) — historical / not wired to live entry

> **Status:** Live entry uses `vix_regime_otm` (regime-scaled OTM + hard skip above `VIX_MAX_THRESHOLD`). Earlier architecture described weekend XGBoost VIX-regime training; that ML path is **not** called today. See `WHEEL_STRATEGY_MANUAL.md` and PROF-010.

- **Historical design:** Weekend retraining, Polars feature generation, `XGBClassifier`, artifact `xgb_vix_regime_v1.pkl`, daily `vix_prob` inference.
- **Do not assume** `vix_prob`-scaled OTM or a 0.75 probability circuit breaker in current code.

## The Execution Engine (strategies/wheel_strategy.py)

- **Treasury & Position Sizing Engine:** Positions scale from available margin × `allocation_pct`, subject to a hard **₹50,000** ceiling (`MAX_CAPITAL` / `PAPER_CAPITAL`):
  1. **Capital Initialization:** `get_available_margin()` — mock returns a large simulated balance; paper returns `PAPER_CAPITAL` (default ₹50,000); live queries Upstox and **clamps to `MAX_CAPITAL`**.
  2. **Target Capital:** `available_margin × allocation_pct` (production Nifty 50 uses `allocation_pct = 1.0`, so budget ≤ ₹50,000).
  3. **Required Margin Per Lot:** (short_strike - long_strike) * lot_size (hedge width from HEDGE_WIDTH, default **100**; must satisfy width x lot <= MAX_CAPITAL; Nifty lot size **25**).
  4. **Lot Sizing:** math.floor(target_capital / required_per_lot).
  5. **Insufficient Capital:** If lots == 0, abort + Discord alert.
- **VIX Regime Gate:** Skip when India VIX > VIX_MAX_THRESHOLD (default 25.0). Otherwise scale OTM: low VIX -> 1.2%, normal -> 1.0%, elevated -> 1.5%. Short put selected by target delta (~0.18) + min credit/width with liquidity guards.
- **Slippage Guardrails:** Bid-ask ((ask - bid) / bid) must be <= MAX_BID_ASK_SPREAD_PCT (default 15%); missing/zero bid aborts.
- **Exits (check_exits):** Take profit when cost_to_close <= TP_RESIDUAL_CREDIT_FRACTION x initial_credit (default **0.25**); stop loss when cost_to_close >= SL_CREDIT_MULTIPLE x initial_credit (default **2.0**) or spot <= short strike; time stop at TIME_STOP_WEEKDAY/TIME_STOP_HOUR (default Thu >= 15:00 IST). Hourly cron is the backstop; WebSocket tick exits run in live and paper when market data is available (MOCK_MARKET skips WS).

## Orchestration (core/scheduler.py)

- **APScheduler Daemon:** Time-based triggers via BackgroundScheduler (Asia/Kolkata).
- **Weekly Entry:** _run_daily_wheel at **Friday 15:15 IST** (default). Optional mid-week job when ALLOW_MIDWEEK_ENTRY=True.
- **Hourly Exits:** _run_exits / check_exits Mon-Fri 09:00-15:00 on the hour.
- **Real-time Exits:** WebSocket monitor starts for live and paper (skipped under MOCK_MARKET). Discord WARNING on start failure / missing token / streamer error (debounced one alert per failure episode); hourly poll continues.
- **Heartbeat:** Optional Dead Man's Snitch-style GET after the daily cycle when `HEARTBEAT_URL` is set.