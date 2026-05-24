# Upstox Algorithmic Options System (Iron Shield Credit Spread Engine)

**An autonomous, containerized production trading system built using Python, Polars, and SQLite3 for the National Stock Exchange of India (NSE) F&O market. It executes risk-defined Bull Put Credit Spreads, dynamically filters market regimes via the India VIX index, calculates real-time margin-scaled lot positioning, and exposes a decoupled analytics interface.**

---

## Table of Contents
1. [System Architecture](#system-architecture)
2. [Core Feature Matrix](#core-feature-matrix)
3. [Project Directory Layout](#project-directory-layout)
4. [Environment Configuration Matrix (.env)](#environment-configuration-matrix-env)
5. [Local Development & Container Deployment](#local-development--container-deployment)

---

## System Architecture

Below is the decoupled data flow pipeline for the Iron Shield Credit Spread Engine:

```text
+---------------------+        +-------------------------+        +---------------------------+
|                     |        |                         |        |                           |
|  Scheduler Daemon   | -----> | Live Funds API Check &  | -----> |  Polars Option Selection  |
|   (APScheduler)     |        |    Risk Validation      |        |      & VIX Regimes        |
|                     |        |                         |        |                           |
+---------------------+        +-------------------------+        +---------------------------+
                                                                                |
                                                                                v
+---------------------+        +-------------------------+        +---------------------------+
|                     |        |                         |        |                           |
| Streamlit UI Node / | <----- |    SQLite3 Ledger       | <----- | Margin-Optimized 2-Leg    |
| Discord Alerting    |        |     Persistence         |        | Order Dispatch Engine     |
|      Gateway        |        |                         |        | (Buy 1st, Sell 2nd)       |
+---------------------+        +-------------------------+        +---------------------------+
```

---

## Core Feature Matrix

### 1. Dynamic Credit Spread Mechanics
Defined-risk entry utilizing an automated **two-leg execution sequence**. The system mandates that the **Long Hedge Put is filled prior to Short Put entry** to enforce margin reduction and ensure risk is strictly capped.

### 2. Treasury & Position Sizing Engine
Live calculation of available cash limits via the Upstox Margin API to scale position lots based on localized risk constraints (**`allocation_pct`**) and exact option contract spread widths.

### 3. Persistence Layer
ACID-compliant **SQLite3 relational engine** tracking active positions, historical cost basis, and global realized metrics. Unpacks flat DB records into nested strategy state objects dynamically.

### 4. Fault Tolerance & Telemetry
Integrated Network Guard managing HTTP 429 rate-limiting backoffs, VIX macro circuit breakers, decoupled multi-channel alerting via **Discord webhooks**, and an external **Dead Man's Snitch heartbeat ping loop** to verify daemon uptime.

### 5. The Lab (Polars Backtester)
Standalone offline simulation laboratory leveraging **Polars lazy frames** and **yfinance** to evaluate performance parameters across historical market cycles. Used for quantitative strategy tuning.

### 6. The Command Center (Analytics Dashboard)
A decoupled **Streamlit web container** serving localized metrics tracking live portfolios, allocation spreads, and performance matrices reading strictly from the decentralized SQLite persistence layer.

---

## Project Directory Layout

```text
.
├── backtest.py           # Standalone offline simulation lab leveraging yfinance and Polars
├── config/               # Global settings, token configuration, and Upstox API keys
├── core/                 # Engine core logic
│   ├── auth.py           # Upstox API authentication handler
│   ├── client.py         # Resilient Upstox HTTP client with built-in rate limit handling
│   ├── scheduler.py      # Main APScheduler daemon triggering the daily cycles
│   └── notifier.py       # Discord Webhook integration for runtime telemetry
├── dashboard.py          # Command Center: Streamlit Analytics Web UI
├── data/                 # SQLite database storage (wheel_state.db) and Parquet fixtures
├── docker-compose.yml    # Main orchestration profile for deploying system containers
├── main.py               # Main bot daemon entry point and runtime initiator
└── strategies/
    └── wheel_strategy.py # Core State Machine: Dynamic Credit Spread and Covered Call logic
```

---

## Environment Configuration Matrix (.env)

Below is a structurally sound sample `.env` configuration file required for system startup.

```env
# Upstox API Credentials
UPSTOX_API_KEY=your_api_key_here
UPSTOX_SECRET_KEY=your_secret_key_here
UPSTOX_REDIRECT_URI=http://localhost:8000/callback

# Risk Matrix & Treasury Parameters
VIX_MAX_THRESHOLD=25.0
ALLOCATION_PCT_PER_TRADE=0.15
MOCK_MARKET=False

# External Webhooks & Telemetry
DISCORD_WEBHOOK_URL=your_discord_webhook_url_here
HEARTBEAT_URL=https://nosnch.in/your_snitch_token
```

---

## Local Development & Container Deployment

### Dependency Management (Local)
This project utilizes [uv](https://github.com/astral-sh/uv) for lightning-fast package management.

To install dependencies locally:
```bash
uv pip install -e .
```
Or to add specific packages:
```bash
uv add <package_name>
```

### Container Deployment Workflow
The complete architecture is structured around standard Linux container engines. You can initiate the entire multi-node environment (Bot Daemon and Streamlit Workspace) via **Podman** or **Docker**.

Start the production nodes in detached mode:
```bash
podman compose up -d --build
```
*(Note: Replace `podman` with `docker` depending on your engine).*

### Accessing the System
- **Bot Daemon Logs:** Inspect daemon operations via `podman compose logs -f bot`
- **Analytics Command Center:** The Streamlit workspace is available locally at **[http://localhost:8501](http://localhost:8501)**
