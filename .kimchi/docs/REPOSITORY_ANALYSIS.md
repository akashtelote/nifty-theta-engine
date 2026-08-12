# Nifty Theta Engine - Repository Analysis Document

**Generated:** 2026-06-19  
**Project:** Iron Shield Credit Spread Engine (Nifty Theta Engine)  
**Type:** Algorithmic Options Trading System for NSE F&O Market

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Directory Structure](#2-directory-structure)
3. [Entry Points](#3-entry-points)
4. [Core Module (`core/`)](#4-core-module-core)
5. [Strategies Module (`strategies/`)](#5-strategies-module-strategies)
6. [Config Module (`config/`)](#6-config-module-config)
7. [Dashboard Module (`dashboard.py`)](#7-dashboard-module-dashboardpy)
8. [Backtest Module (`backtest.py`)](#8-backtest-module-backtestpy)
9. [Deployment Files](#9-deployment-files)
10. [Database Schema](#10-database-schema)
11. [Environment Configuration](#11-environment-configuration)
12. [State Machine Logic](#12-state-machine-logic)
13. [Risk Management & Guardrails](#13-risk-management--guardrails)
14. [API Integration & Authentication](#14-api-integration--authentication)
15. [Deployment Architecture](#15-deployment-architecture)

---

## 1. Project Overview

**Project Name:** Nifty Theta Engine (also known as "Iron Shield Credit Spread Engine")

**Purpose:** An autonomous, containerized production trading system that executes risk-defined Bull Put Credit Spreads on the National Stock Exchange of India (NSE) F&O market. The system dynamically filters market regimes via the India VIX index, calculates real-time margin-scaled lot positioning, and exposes a decoupled analytics interface.

**Core Functionality:**
- Automated selling of Out-of-The-Money (OTM) Put Credit Spreads
- Two-leg execution sequence (Long Hedge Put filled first, then Short Put)
- Dynamic position sizing based on available margin and risk allocation
- State machine-driven strategy execution (IDLE → STAGE_1_CSP → STAGE_2_CC)
- Real-time monitoring and alerting via Discord webhooks
- PostgreSQL-backed persistence for strategy state
- Streamlit analytics dashboard for portfolio visualization

**Technology Stack:**
- Python 3.11+ (primary language)
- Polars (high-performance DataFrames for option chain processing)
- PostgreSQL (state persistence)
- Redis (centralized token bus)
- APScheduler (scheduled job orchestration)
- Streamlit (analytics dashboard)
- Docker/Podman (containerization)
- Upstox API (trading execution)

---

## 2. Directory Structure

```
nifty-theta-engine/
├── .claudeignore             # Claude AI configuration exclusions
├── .dockerignore             # Docker build exclusions
├── .env                      # Environment variables (contains secrets)
├── .env.example              # Example environment template
├── .github/                  # GitHub workflows
│   └── workflows/
│       └── auto-merge.yml    # Auto-merge workflow
├── .gitignore                # Git exclusions
├── .python-version           # Python version specification
├── .venv/                    # Virtual environment (not committed)
├── .kimchi/                  # Agent working directory
│   ├── docs/                 # Documentation (this file)
│   └── ferments/             # Agent fermentation files
├── ARCHITECTURE.md           # Architectural audit document
├── backtest.py               # Offline simulation laboratory
├── config/                   # Configuration module
│   ├── __init__.py
│   ├── settings.py           # Settings (timeouts, webhook URL)
│   └── token.json            # API token storage
├── core/                     # Core engine logic
│   ├── __init__.py
│   ├── auth.py               # Upstox API authentication handler
│   ├── client.py             # Resilient HTTP client with rate limiting
│   ├── loader.py             # Nifty 500 ticker fetcher
│   ├── notifier.py           # Discord webhook integration
│   ├── scheduler.py          # APScheduler daemon
│   └── smart_money.py        # Institutional activity tracker
├── dashboard.py              # Streamlit Analytics Command Center
├── data/                     # Runtime data storage
│   └── .gitkeep              # Persists SQLite/Parquet files
├── deploy.sh                 # Linux deployment script
├── deploy.ps1                # PowerShell deployment script
├── deploy.bat                # Batch deployment script
├── docker-compose.yml        # Multi-container orchestration
├── Dockerfile                # Container image definition
├── init_nifty_schema.sql     # PostgreSQL schema initialization
├── logs/                     # Log files
│   └── .gitkeep
├── main.py                   # Main bot daemon entry point
├── pyproject.toml            # Project dependencies (uv)
├── README.md                 # Project documentation
├── strategies/               # Trading strategies
│   ├── __init__.py
│   └── wheel_strategy.py     # Core State Machine implementation
├── uv.lock                   # Locked dependency versions
└── WHEEL_STRATEGY_MANUAL.md  # Strategy operation manual
```

---

## 3. Entry Points

### 3.1 `main.py` - Bot Daemon Entry Point

**Purpose:** Unified CLI for the Indian Trading Bot system.

**Commands:**
| Command | Description |
|---------|-------------|
| `auth` | Generate or refresh the Upstox API token |
| `screen` | Run the Smart Money Filter to find institutional whales |
| `trade` | Run a simulated paper trade or live trade |
| `start` | Start the daily APScheduler daemon |

**Key Functions:**
- `main()` - Parses CLI arguments and dispatches to appropriate handler
- `run_trade(args)` - Executes simulated paper trade or live trade via `UpstoxClient`

**Usage Examples:**
```bash
uv run main.py auth          # Authenticate with Upstox
uv run main.py screen        # Screen for institutional activity
uv run main.py trade RELIANCE BUY 100 2500.50  # Paper/live trade
uv run main.py start         # Start the scheduler daemon
```

---

### 3.2 `dashboard.py` - Streamlit Analytics Dashboard

**Purpose:** Decoupled analytics web interface that reads from PostgreSQL persistence layer.

**Features:**
- **Global Summary Metrics:** Active positions, Total Realized PnL, IDLE states, CSP/CC stage counts
- **Active Positions Table:** Real-time view of open positions with strike, expiry, entry price
- **Visual Breakdown:** Bar charts for PnL by symbol and stage distribution
- **Historical Trade Ledger:** Completed trades with realized PnL

**Database Connection:**
- Reads from `wheel_state` table via PostgreSQL
- Connection string: `DATABASE_URL` env var (default: `postgresql://wheelbot:securepassword@localhost:5432/wheeldb`)
- Cached with 60-second TTL via `@st.cache_data(ttl=60)`

**Access:** Port 8501 (internal) mapped to 8502 (external in docker-compose)

---

### 3.3 `backtest.py` - Offline Simulation Laboratory

**Purpose:** Standalone backtesting engine using Polars and yfinance for historical strategy evaluation.

**Key Functions:**

| Function | Signature | Purpose |
|----------|-----------|---------|
| `fetch_historical_data` | `(ticker, start_date, end_date) → pl.DataFrame` | Fetches historical OHLCV data for a ticker and India VIX |
| `estimate_premium` | `(spot, strike, vix, dte=30) → float` | Simplified Black-Scholes premium estimation |
| `run_backtest` | `(df, lot_size, initial_capital=500000) → dict` | Simulates wheel strategy on historical data |

**Entry Logic (VIX-based OTM selection):**
- VIX < 13: 6% OTM
- VIX 13-18: 10% OTM
- VIX > 18: 15% OTM

**Exit Logic:**
- 30-day time stop
- Win: Spot > short_strike (expires worthless)
- Loss: Spot ≤ short_strike (calculate loss)

**Portfolio Symbols:** RELIANCE.NS, HDFCBANK.NS, INFY.NS, MARUTI.NS, SBIN.NS

**Backtest Period:** 2021-01-01 to 2026-01-01

**Output Metrics:**
- Total trades, winning trades, win rate
- Final PnL in INR
- Average yield percentage
- Per-trade yield list

---

## 4. Core Module (`core/`)

### 4.1 `auth.py` - Upstox Authentication Handler

**Purpose:** Manages Upstox API token lifecycle with Redis-based centralized token bus for multi-bot coordination.

**Key Constants:**
```python
TOKEN_FILE = "data/token.json"
TOKEN_MAX_AGE_SECONDS = 12 * 3600  # 12 hours
TOKEN_FORCE_REFRESH_GUARD_SECONDS = 300  # 5 minutes (prevents OTP spam)
```

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `get_current_timestamp()` | Returns UTC ISO timestamp |
| `get_centralized_token()` | Fetches token from Redis (`upstox:active_token`) |
| `_delete_centralized_token()` | Deletes token from Redis |
| `_save_centralized_token(token)` | Saves token to Redis |
| `authenticate_and_save_token(force_refresh=False)` | Main auth entry point with fallback logic |

**Authentication Flow:**
1. If `force_refresh=True`, delete Redis token and skip fetch
2. Attempt to fetch token from Redis centralized bus
3. If Redis has token → return it (avoids killing other sessions)
4. If Redis fails → execute legacy TOTP login (WARNING: kills other sessions)
5. Save new token to both local file and Redis
6. Return access token

**Environment Variables Required:**
- `UPSTOX_USER_ID`
- `UPSTOX_PASSWORD`
- `UPSTOX_PIN_CODE`
- `UPSTOX_TOTP_SECRET`
- `UPSTOX_API_KEY`
- `UPSTOX_API_SECRET`
- `UPSTOX_REDIRECT_URI`

---

### 4.2 `client.py` - Resilient HTTP Client

**Purpose:** Centralized Upstox API client with built-in rate limiting, token self-healing, and comprehensive error handling.

**Key Features:**
- **Rate Limit Handling:** Automatic retry on HTTP 429 with `Retry-After` header
- **Token Self-Healing:** Auto-detects 401 responses and re-authenticates
- **Redis Token Sync:** Fetches fresh tokens from Redis if local token is dead
- **Circuit Breaker:** Returns mock data when `MOCK_MARKET=True`

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `__init__()` | Initialize client, load/fetch access token |
| `_make_authenticated_request(method, url, **kwargs)` | Central auth request handler with 401 self-healing |
| `_get_instrument_token(symbol, exchange)` | Lookup instrument token from NSE F&O master CSV |
| `get_available_margin()` | Fetch live available cash/equity margin |
| `get_order_status(order_id)` | Check order fill status |
| `get_india_vix()` | Fetch current India VIX price |
| `get_market_quote_ltp(symbol)` | Get last traded price for any symbol |
| `place_order(symbol, side, quantity, price)` | Place order by symbol name |
| `place_order_by_key(instrument_key, side, quantity, price)` | Place order by instrument key |
| `get_option_chain(symbol, expiry_date)` | Fetch full option chain as Polars DataFrame |
| `cancel_order(order_id)` | Cancel pending limit order |

**Instrument Token Caching:**
- Downloads NSE F&O instruments from `https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz`
- Caches locally for 24 hours
- Uses FileLock to prevent race conditions during download

**Option Chain DataFrame Schema:**
```python
{
    "instrument_key": pl.Utf8,  # e.g., "NSE_FO|NIFTY22000PE"
    "type": pl.Utf8,            # "CE" or "PE"
    "strike": pl.Float64,       # Strike price
    "expiry": pl.Utf8,          # "YYYY-MM-DD"
    "bid": pl.Float64,          # Bid price
    "ask": pl.Float64,          # Ask price
    "last_price": pl.Float64    # Last traded price
}
```

**Environment Variables:**
- `MOCK_MARKET`: Return fake data for testing (default: "False")
- `PAPER_TRADE`: Route to paper trade mode (default: "True")

---

### 4.3 `notifier.py` - Discord Webhook Integration

**Purpose:** Sends rich embed notifications to Discord via webhook for runtime telemetry.

**Embed Colors:**
| Level | Color Code | Use Case |
|-------|------------|----------|
| INFO | 3447003 (Blue) | Successful order placements |
| WARNING | 16776960 (Yellow) | LTP fetch failures, insufficient funds |
| ERROR | 16711680 (Red) | Critical failures, manual intervention required |

**Method:**
```python
Notifier().send_notification(title: str, message: str, level: str = "INFO")
```

---

### 4.4 `scheduler.py` - APScheduler Daemon

**Purpose:** Orchestrates the daily trade cycle and exit evaluation using APScheduler with Asia/Kolkata timezone.

**Scheduled Jobs:**

| Job | Trigger | Description |
|-----|---------|-------------|
| `_run_daily_wheel` | Friday 15:15 IST | Entry trigger for new credit spread positions |
| `_run_exits` | Mon-Fri 9:00-15:00 IST (hourly) | Exit evaluation for active positions |
| Heartbeat | End of daily wheel | Dead Man's Snitch ping to `HEARTBEAT_URL` |

**Configuration:**
```python
TARGET_SYMBOLS = {"Nifty 50": {"allocation_pct": 1.0}}
LOT_SIZES = {"Nifty 50": 25}
```

**Execution Flow:**
1. Iterate over `TARGET_SYMBOLS`
2. Create `WheelStateMachine` instance
3. Call `execute_daily_cycle()` for each symbol
4. Send Discord notifications on errors
5. Send heartbeat ping if configured

---

### 4.5 `smart_money.py` - Institutional Activity Tracker

**Purpose:** Tracks institutional buying/selling activity using NSE Bulk and Block deals data to calculate "Whale Scores."

**Key Class:** `SmartMoneyFilter`

**Institutional Keywords:**
```python
['FUND', 'CAPITAL', 'BANK', 'ADVISORS', 'INSURANCE', 'ASSET', 'INVESTMENT', 'PENSION']
```

**Data Fetching (Multi-stage Fallback):**
1. **jugaad-data:** Direct Python library access (currently disabled due to NSE blocking)
2. **HTTP:** Direct requests to NSE archives (`nsearchives.nseindia.com`)
3. **Playwright:** Browser automation for JavaScript-rendered content

**Metadata Caching:**
- Fetches Nifty 500 metadata from yfinance
- Caches to `data/equity_metadata.json`
- Refreshes if older than 7 days or on Sunday

**Whale Score Calculation:**
```python
whale_score = 1 if institutional_net_buying > 0.5% of shares_outstanding else 0
```

**Output:** `data/whale_scores.json` with symbols as keys and score (0/1) as values

---

### 4.6 `loader.py` - Nifty 500 Ticker Fetcher

**Purpose:** Fetches the official Nifty 500 constituent list from NSE.

**Function:**
```python
get_nifty500_tickers() → list[str]
```

**Source:** `https://archives.nseindia.com/content/indices/ind_nifty500list.csv`

**Returns:** List of ticker symbols (e.g., `['RELIANCE', 'HDFCBANK', 'INFY', ...]`)

---

## 5. Strategies Module (`strategies/`)

### 5.1 `wheel_strategy.py` - Wheel Strategy State Machine

**Purpose:** Implements the core options wheel strategy with Bull Put Credit Spreads and Covered Calls.

**Key Class:** `WheelStateMachine`

#### State Machine States

| State | Description |
|-------|-------------|
| `IDLE` | Bot holds cash, waiting for daily cycle trigger |
| `STAGE_1_CSP` | Cash Secured Put / Put Credit Spread active |
| `STAGE_2_CC` | Covered Call (shares assigned, selling calls) |
| `CLOSED` | Position closed, awaiting reset to IDLE |

#### State Transitions

```
IDLE → STAGE_1_CSP: Daily cycle triggered, VIX safe, funds available
STAGE_1_CSP → IDLE: Worthless expiration (OTM), profit taken (50% rule), or DTE ≤ 3 defensive buyback
STAGE_1_CSP → STAGE_2_CC: Assignment (ITM at expiration)
STAGE_2_CC → STAGE_2_CC: Call expired worthless (hold shares, sell new call)
STAGE_2_CC → IDLE: Shares called away (ITM)
```

#### Key Methods

| Method | Purpose |
|--------|---------|
| `__init__()` | Initialize state machine, connect to PostgreSQL |
| `_load_state()` | Load state from `index_spread_state` table |
| `_save_state(symbol)` | Persist state to PostgreSQL |
| `ensure_symbol_state(symbol)` | Initialize default state for new symbols |
| `_select_target_put(chain_df, spot_price, ...)` | Select Short and Long Put for credit spread |
| `_select_target_call(chain_df, spot_price, cost_basis, ...)` | Select Call option for covered call |
| `execute_daily_cycle(symbol, quantity_shares, symbol_config)` | Main entry logic for new positions |
| `check_exits()` | Evaluate active positions for exit triggers |

#### Execution Sequence (Credit Spread)

1. **Load state** from PostgreSQL
2. **Fetch LTP** for symbol
3. **Get option chain** from Upstox
4. **Select target puts** via `_select_target_put`:
   - Filter PE options with DTE 10-42 days
   - Target 1% OTM for short strike
   - Select hedge strike 100 points below
   - Verify bid-ask spread < 15%
5. **Dynamic position sizing:**
   ```python
   BUDGET = 20000.0
   required_capital_per_lot = (short_strike - long_strike) * lot_size
   num_lots = math.floor(BUDGET / required_capital_per_lot)
   final_quantity = num_lots * lot_size
   ```
6. **Execute Leg 1 (Hedge):** BUY Long Put at Ask price
7. **Verify fill** (3 retries, 5-second intervals)
8. **Execute Leg 2 (Short):** SELL Short Put at Bid price
9. **Verify fill** (3 retries, 5-second intervals)
10. **Update state** to `STAGE_1_CSP`

#### Exit Conditions

| Condition | Trigger | Action |
|-----------|---------|--------|
| Take Profit | Cost to close ≤ 20% of initial credit | Buy to close Short, Sell to close Long |
| Stop Loss | Cost to close ≥ 200% of initial credit OR spot ≤ short strike | Defensive exit |
| Time Stop | Thursday ≥ 15:00 IST | Market order exit |

#### Database Schema (index_spread_state)

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | TEXT | Primary key (e.g., "Nifty 50") |
| `current_stage` | TEXT | Current state (IDLE, STAGE_1_CSP, etc.) |
| `short_instrument_key` | TEXT | Short option instrument key |
| `short_strike` | DOUBLE | Short option strike price |
| `short_entry_price` | DOUBLE | Short option entry price |
| `short_order_id` | TEXT | Short order ID |
| `long_instrument_key` | TEXT | Long (hedge) option instrument key |
| `long_strike` | DOUBLE | Long option strike price |
| `long_entry_price` | DOUBLE | Long option entry price |
| `long_order_id` | TEXT | Long order ID |
| `quantity` | INTEGER | Position size in shares |
| `net_credit_received` | DOUBLE | Initial net credit |
| `trade_date` | TEXT | Trade entry date |
| `expiry_date` | TEXT | Option expiration date |
| `lifetime_realized_pnl` | DOUBLE | Cumulative realized P&L across all closed trades for this symbol (not just the current trade); per-trade P&L is in `trade_history.realized_pnl` |

---

## 6. Config Module (`config/`)

### 6.1 `settings.py`

**Purpose:** Global configuration constants loaded from environment variables.

**Settings:**
| Constant | Source | Default | Purpose |
|----------|--------|---------|---------|
| `CONNECTION_TIMEOUT` | `CONNECTION_TIMEOUT` env | 10.0s | API connection timeout |
| `READ_TIMEOUT` | `READ_TIMEOUT` env | 30.0s | API read timeout |
| `WEBHOOK_URL` | `WEBHOOK_URL` env | None | Discord webhook URL |

### 6.2 `token.json`

**Purpose:** Local token storage for Upstox API access token.

**Structure:**
```json
{
    "access_token": "FAKE_TOKEN"
}
```

**Note:** Should never be committed to version control. Token is managed by `auth.py`.

---

## 7. Dashboard Module (`dashboard.py`)

**Purpose:** Streamlit-based analytics dashboard for monitoring wheel strategy performance.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ Wheel Strategy Analytics Dashboard                          │
├─────────────────────────────────────────────────────────────┤
│ Global Summary Metrics                                      │
│ [Active Positions] [Total Realized PnL] [IDLE] [CSP] [CC]   │
├─────────────────────────────────────────────────────────────┤
│ Active Positions Table                                      │
│ symbol | stage | instrument_key | strike | expiry | price   │
├─────────────────────────────────────────────────────────────┤
│ Visual Breakdown                                            │
│ [PnL by Symbol]          │ [Stage Distribution]            │
├─────────────────────────────────────────────────────────────┤
│ Historical Trade Ledger                                     │
│ Completed trades with realized PnL                          │
└─────────────────────────────────────────────────────────────┘
```

**Data Source:** PostgreSQL `index_spread_state` table

**Caching:** 60-second TTL with `@st.cache_data(ttl=60)`

---

## 8. Backtest Module (`backtest.py`)

**Purpose:** Offline historical simulation of the wheel strategy.

**Key Functions:**

### `fetch_historical_data(ticker, start_date, end_date) → pl.DataFrame`
- Downloads ticker OHLCV from yfinance
- Downloads India VIX from yfinance
- Merges on Date with forward-fill for missing data
- Returns DataFrame with columns: `Date`, `Spot_Price`, `VIX`

### `estimate_premium(spot, strike, vix, dte=30) → float`
- Simplified premium formula: `(spot * (vix / 100.0)) * 0.10 * (strike / spot)`
- Used for backtest entry simulation

### `run_backtest(df, lot_size, initial_capital=500000) → dict`
- Simulates wheel strategy on provided DataFrame
- Entry: VIX-based OTM selection
- Exit: 30-day time stop
- Returns: `{total_trades, winning_trades, win_rate, final_pnl, average_yield_pct, trade_yields}`

**Usage:**
```python
# Run for single ticker
df = fetch_historical_data("RELIANCE.NS", "2021-01-01", "2026-01-01")
results = run_backtest(df, lot_size=250)

# Run for full portfolio
for ticker in ["RELIANCE.NS", "HDFCBANK.NS", "INFY.NS", "MARUTI.NS", "SBIN.NS"]:
    df = fetch_historical_data(ticker, "2021-01-01", "2026-01-01")
    results = run_backtest(df, LOT_SIZES[ticker])
```

---

## 9. Deployment Files

### 9.1 `Dockerfile`

**Base Image:** `python:3.11-slim`

**Key Steps:**
1. Install `tzdata` for timezone support
2. Install `uv` from astral-sh official image (fast package manager)
3. Copy `pyproject.toml` and `uv.lock`
4. Run `uv sync --frozen --no-dev` to create `.venv`
5. Add `.venv` to PATH
6. Copy application code
7. Set CMD to `python main.py start`

### 9.2 `docker-compose.yml`

**Services:**

| Service | Image | Ports | Purpose |
|---------|-------|-------|---------|
| `db` | `postgres:15-alpine` | None (internal) | PostgreSQL persistence |
| `upstox_wheel_bot` | Built from Dockerfile | 8000 | Main trading daemon |
| `dashboard` | `nifty_wheel_base:latest` | 8502:8501 | Streamlit analytics |

**Health Check:** `db` uses `pg_isready` with 5s interval/timeout

**Dependencies:** Both bot and dashboard wait for `db` to be healthy

### 9.3 `deploy.sh`, `deploy.ps1`, `deploy.bat`

Platform-specific deployment scripts (Linux, PowerShell, Batch).

---

## 10. Database Schema

### `init_nifty_schema.sql`

```sql
DROP TABLE IF EXISTS wheel_state;

CREATE TABLE index_spread_state (
    symbol TEXT PRIMARY KEY,
    current_stage TEXT,
    short_instrument_key TEXT,
    short_strike DOUBLE PRECISION,
    short_entry_price DOUBLE PRECISION,
    short_order_id TEXT,
    long_instrument_key TEXT,
    long_strike DOUBLE PRECISION,
    long_entry_price DOUBLE PRECISION,
    long_order_id TEXT,
    quantity INTEGER,
    net_credit_received DOUBLE PRECISION,
    trade_date TEXT,
    expiry_date TEXT,
    lifetime_realized_pnl DOUBLE PRECISION
);
```

**Note:** Schema uses `ON CONFLICT (symbol) DO UPDATE` for upsert semantics.

---

## 11. Environment Configuration

### Required Environment Variables

| Variable | Example | Purpose |
|----------|---------|---------|
| `UPSTOX_API_KEY` | `your_api_key` | Upstox API key |
| `UPSTOX_SECRET_KEY` | `your_secret` | Upstox secret |
| `UPSTOX_REDIRECT_URI` | `http://localhost:8000/callback` | OAuth redirect |
| `UPSTOX_USER_ID` | `your_user_id` | Upstox login ID |
| `UPSTOX_PASSWORD` | `your_password` | Upstox password |
| `UPSTOX_PIN_CODE` | `1234` | Upstox PIN |
| `UPSTOX_TOTP_SECRET` | `BASE32SECRET` | TOTP authenticator secret |
| `DATABASE_URL` | `postgresql://wheelbot:password@localhost:5432/wheeldb` | PostgreSQL connection |
| `REDIS_URL` | `redis://host.docker.internal:6379/0` | Redis connection |
| `VIX_MAX_THRESHOLD` | `25.0` | VIX circuit breaker threshold |
| `ALLOCATION_PCT_PER_TRADE` | `0.15` | Position sizing allocation % |
| `MOCK_MARKET` | `False` | Use mock data for testing |
| `PAPER_TRADE` | `True` | Paper trade mode |
| `DISCORD_WEBHOOK_URL` | `https://discord.com/api/webhooks/...` | Discord notifications |
| `WEBHOOK_URL` | `https://discord.com/api/webhooks/...` | Alternative webhook var |
| `HEARTBEAT_URL` | `https://nosnch.in/your_snitch_token` | Dead man's snitch |
| `CONNECTION_TIMEOUT` | `10.0` | API connection timeout |
| `READ_TIMEOUT` | `30.0` | API read timeout |

---

## 12. State Machine Logic

### Full State Transition Diagram

```
┌──────────┐                    ┌─────────────────┐
│          │   Friday 15:15     │                 │
│   IDLE   │ ─────────────────► │  STAGE_1_CSP    │
│          │   VIX < 0.75       │  (Credit Spread)│
└──────────┘                    └────────┬────────┘
       ▲                                  │
       │                                  │
       │ ┌────────────────────────────────┼────────────────────────────────┐
       │ │                                │                                │
       │ │                         Short Put Expires                       │
       │ │                         (ITM - Assigned)                        │
       │ │                                ▼                                │
       │ │                         ┌─────────────────┐                     │
       │ │                         │                 │                     │
       │ │                         │  STAGE_2_CC     │                     │
       │ │                         │  (Covered Call) │                     │
       │ │                         └────────┬────────┘                     │
       │ │                                  │                               │
       │ │                                  │ Call Expires                  │
       │ │                                  │ (ITM - Called Away)           │
       │ │                                  ▼                               │
       │ │                                                                   │
       │ │                                                                   │
       │ │                                                                   │
       │ │              Short Put Expires                                    │
       │ │              (OTM - Worthless)                                    │
       │ │                                                                   │
       │ │                                                                   │
       │ │              Profit Taken                                         │
       │ │              (50% Rule)                                           │
       │ │                                                                   │
       │ │              DTE ≤ 3 Defensive                                    │
       │ │              Buyback                                              │
       │ │                                                                   │
       └─┴───────────────────────────────────────────────────────────────────┘
```

---

## 13. Risk Management & Guardrails

### 13.1 VIX Circuit Breaker
- ML-based VIX spike probability (if `vix_prob >= 0.75`, abort trade)
- Falls back to static threshold (`VIX_MAX_THRESHOLD`)

### 13.2 Bid-Ask Spread Guardrail
- Pre-trade slippage check: `spread_pct = (ask - bid) / bid`
- Abort if `spread_pct > 0.15` or bid is zero

### 13.3 Position Sizing
- Dynamic lot calculation: `num_lots = floor(BUDGET / required_capital_per_lot)`
- Abort if `num_lots == 0` (insufficient capital)

### 13.4 Order Fill Verification
- 3 retries with 5-second intervals
- Cancel pending orders if not filled
- Manual intervention alerts for dangling positions

### 13.5 Exit Rules
- **Take Profit:** Cost to close ≤ 20% of initial credit
- **Stop Loss:** Cost to close ≥ 200% of initial credit OR spot breaches short strike
- **Time Stop:** Thursday ≥ 15:00 IST

---

## 14. API Integration & Authentication

### 14.1 Upstox API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v3/user/get-funds-and-margin` | GET | Fetch available margin |
| `/v2/order/details` | GET | Get order status |
| `/v2/order/place` | POST | Place new order |
| `/v2/order/cancel` | DELETE | Cancel order |
| `/v2/option/contract` | GET | Get option contract list |
| `/v2/option/chain` | GET | Get option chain |
| `/v2/market-quote/ltp` | GET | Get last traded price |

### 14.2 Token Management Strategy

```
┌─────────┐     GET      ┌─────────┐
│   Bot   │ ───────────► │  Redis  │
│         │              │ (Token  │
└─────────┘              │  Bus)   │
    │                    └─────────┘
    │                         │
    │ Token Missing           │ Token Found
    │/Expired                 │
    ▼                         ▼
┌─────────┐              ┌─────────┐
│  TOTP   │              │  Use    │
│  Login  │              │  Token  │
│ (Kills  │              │         │
│ Sessions)              └─────────┘
└─────────┘
```

---

## 15. Deployment Architecture

### Container Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Bridge Network                    │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │     db       │    │ upstox_wheel │    │  dashboard   │  │
│  │  (postgres)  │    │    _bot      │    │ (streamlit)  │  │
│  │              │    │              │    │              │  │
│  │  wheel_state │    │  Scheduler   │    │  Analytics   │  │
│  │    table     │◄──►│  + Wheel     │    │    Web UI    │  │
│  │              │    │  Strategy    │    │              │  │
│  └──────────────┘    └──────┬───────┘    └──────▲───────┘  │
│                             │                      │       │
│                             │      ┌───────────────┘       │
│                             │      │                       │
│                             ▼      │                       │
│                      ┌──────────┐  │                       │
│                      │  Redis   │◄─┘                       │
│                      │ (Token   │                          │
│                      │   Bus)   │                          │
│                      └──────────┘                          │
│                             ▲                              │
│                             │                              │
│                      ┌──────┴───────┐                      │
│                      │ host.docker. │                      │
│                      │   internal   │                      │
│                      └──────────────┘                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                   ┌────────────────────┐
                   │   Upstox API       │
                   │   (External)       │
                   └────────────────────┘
```

### Port Mapping

| Service | Internal Port | External Port | URL |
|---------|--------------|---------------|-----|
| upstox_wheel_bot | 8000 | 8000 | OAuth redirect |
| dashboard | 8501 | 8502 | http://localhost:8502 |

---

## File Summary Table

| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | ~60 | CLI entry point |
| `backtest.py` | ~170 | Historical simulation |
| `dashboard.py` | ~90 | Streamlit analytics |
| `core/auth.py` | ~160 | Authentication |
| `core/client.py` | ~450 | API client |
| `core/notifier.py` | ~40 | Discord alerts |
| `core/scheduler.py` | ~90 | Job orchestration |
| `core/smart_money.py` | ~350 | Institutional tracking |
| `core/loader.py` | ~25 | Nifty 500 fetcher |
| `strategies/wheel_strategy.py` | ~420 | Strategy state machine |
| `config/settings.py` | ~15 | Configuration |
| `docker-compose.yml` | ~60 | Container orchestration |
| `Dockerfile` | ~25 | Image build |

---

## Notes

- This is a **production trading system** with real financial risk
- All deployments should use proper secret management (not `.env` files in production)
- Paper trading mode (`PAPER_TRADE=True`) should be used for testing
- Manual intervention alerts indicate critical states requiring human attention
- The ML pipeline components mentioned in ARCHITECTURE.md have been removed from the current codebase