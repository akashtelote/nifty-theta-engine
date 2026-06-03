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
  - Accounting: `realized_pnl`
- **Application Parsing:** Within `strategies/wheel_strategy.py`, the flat SQL records are packed/unpacked into a nested Python dictionary to maintain strategy logic compatibility.

## The ML Pipeline (ml_service/)

- **Weekend Retraining:** The ML pipeline handles periodic retraining of the VIX regime prediction model.
- **Data Ingestion:** A scheduled job (`_scheduled_ml_retraining`) uses **Polars** to securely fetch and join NIFTY 50 and India VIX macro data. Polars `LazyFrame`s are utilized for high-performance, out-of-core feature generation.
- **Model Training:** The pipeline transforms the Polars dataframes into Pandas immediately before ingestion into an **XGBoost (`XGBClassifier`)** model to predict volatility spikes.
- **Artifact Serialization:** Once training completes, the model is serialized into an artifact named `xgb_vix_regime_v1.pkl` using Scikit-Learn's `joblib`.
- **Inference Worker:** Daily during market hours, the bot utilizes the `VixRegimePredictor` to deserialize the `.pkl` artifact, ingest the last 40 days of market data via Polars, and output a spike probability (`vix_prob`).

## The Execution Engine (strategies/wheel_strategy.py)

- **Treasury & Position Sizing Engine:** The bot dynamically scales its positions based on required margin and predefined risk allocations rather than full notional share value. The sizing sequence operates as follows:
  1. **Capital Initialization:** The bot actively fetches live available margin from the Upstox API (`/v3/user/get-funds-and-margin`). If running in mock market mode, it bypasses the API and hardcodes the balance to ₹5,00,000.0.
  2. **Target Capital:** It computes the capital allocated to the specific trade by multiplying the available margin by the symbol's configured `allocation_pct` (e.g., ₹5,00,000 * 0.10 = ₹50,000).
  3. **Required Margin Per Lot:** For defined-risk credit spreads, the margin is calculated as the spread width multiplied by the standard lot size: `(short_strike - long_strike) * lot_size` (e.g., ₹20 wide * 400 shares = ₹8,000).
  4. **Lot Sizing:** The engine determines the maximum number of full lots it can trade by dividing the target capital by the required margin per lot, strictly flooring the result (`math.floor()`).
  5. **Edge Case (Insufficient Capital):** If the calculated number of lots is zero (i.e., the target capital is less than the margin required for a single lot), the engine immediately aborts the trade, logs a warning, and sends a Discord alert to prevent executing invalid trades or risking unsupported positions.
- **VIX Circuit Breaker:** The bot dynamically uses the output (`vix_prob`) from the ML predictor. If `vix_prob` is >= 0.75, the bot aborts the trade cycle and stays in cash. For probabilities < 0.75, `vix_prob` dictates the Out-of-The-Money (OTM) percentage target for Put options (e.g., < 0.30 = 2% OTM, 0.30-0.60 = 3% OTM, > 0.60 = 4% OTM).
- **Slippage Guardrails:** Before executing any option legs, the engine calculates the bid-ask spread `((ask - bid) / bid)`. If the spread exceeds 15% or the bid is missing/zero, the trade is aborted to protect against severe slippage.
- **Dynamic Profit-Taking (50% Rule):** During the `STAGE_1_CSP` (Credit Spread) phase, the engine tracks the initial net credit received. If the real-time cost to close the spread drops to <= 50% of the initial credit, the bot automatically buys back the short put and sells the long put, logging realized profit and resetting the state to `IDLE`.

## Orchestration (core/scheduler.py)

- **APScheduler Daemon:** Time-based triggers for both execution and retraining are handled by `apscheduler.schedulers.background.BackgroundScheduler`.
- **Timezone Management:** The scheduler uses the `pytz` library and internally anchors to the `'Asia/Kolkata'` timezone, ensuring accurate and precise Cron firing regardless of the container's UTC system time.
- **Daily Trade Cycle:** The primary bot logic (`_run_daily_wheel`) is triggered via a `CronTrigger` strictly at **15:15 IST**, Monday through Friday.
- **Weekend ML Compute:** The ML retraining pipeline (`_scheduled_ml_retraining`) is configured to run at **02:00 IST every Saturday** to ensure fresh weights are ready before Monday.
- **Heartbeat:** At the very end of the daily cycle, a Dead Man's Snitch-style heartbeat GET request ensures system uptime visibility.