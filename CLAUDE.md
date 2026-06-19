# Nifty Theta Engine

Production algorithmic options trading system that executes Bull Put Credit Spreads on the NSE Nifty 50 index via the Upstox API.

## Quick Reference

- **Language:** Python 3.12+ (managed with `uv`)
- **Database:** PostgreSQL 15 (table: `index_spread_state`)
- **Token Bus:** Redis (`upstox:active_token`)
- **Notifications:** Discord webhooks
- **Scheduler:** APScheduler (Asia/Kolkata timezone)
- **Dashboard:** Streamlit on port 8502
- **Container:** Docker Compose (3 services: db, bot, dashboard)

## Project Layout

```
main.py                  CLI entry point (auth | screen | trade | start)
core/
  auth.py                Upstox token lifecycle (Redis + TOTP fallback)
  client.py              Upstox API client (rate limiting, 401 self-healing)
  scheduler.py           APScheduler daemon (entry on Fri 15:15, exits hourly)
  notifier.py            Discord webhook alerts
  smart_money.py         Institutional whale score tracker
  loader.py              Nifty 500 constituent fetcher
strategies/
  wheel_strategy.py      State machine: IDLE -> STAGE_1_CSP -> STAGE_2_CC -> CLOSED
config/
  settings.py            Env-driven timeouts and webhook URL
execution/               Reserved for execution manager (currently empty)
dashboard.py             Streamlit analytics dashboard
backtest.py              Offline historical simulation (Polars + yfinance)
```

## Architecture

Detailed system architecture, data flow, and component documentation:
- [.kimchi/docs/REPOSITORY_ANALYSIS.md](.kimchi/docs/REPOSITORY_ANALYSIS.md) - Full repository analysis
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture overview
- [WHEEL_STRATEGY_MANUAL.md](WHEEL_STRATEGY_MANUAL.md) - Strategy operation manual
- [docs/ISSUE_LOG.md](docs/ISSUE_LOG.md) - Known issues and technical debt

## State Machine

```
IDLE ──[Fri 15:15, VIX safe]──> STAGE_1_CSP (Credit Spread active)
STAGE_1_CSP ──[Take Profit / Stop Loss / Time Stop]──> CLOSED
STAGE_1_CSP ──[Assignment]──> STAGE_2_CC (Covered Call)
STAGE_2_CC ──[Called Away]──> IDLE
CLOSED ──[Next cycle]──> IDLE
```

## Commands

```bash
uv run main.py auth              # Authenticate with Upstox
uv run main.py screen            # Run institutional activity screen
uv run main.py trade SYMBOL SIDE QTY PRICE  # Paper/live trade
uv run main.py start             # Start scheduler daemon
```

## Running Locally

```bash
# Install dependencies
uv sync

# Start infrastructure
docker compose up -d db

# Start the bot (paper trade mode by default)
uv run main.py start

# Start the dashboard
uv run streamlit run dashboard.py
```

## Docker Deployment

```bash
docker compose up -d --build
```

Services: `db` (PostgreSQL), `upstox_wheel_bot` (trading daemon), `dashboard` (Streamlit UI on :8502).

## Environment Variables

Required in `.env` (see `.env.example`):

| Variable | Purpose |
|----------|---------|
| `UPSTOX_API_KEY` | Upstox API key |
| `UPSTOX_API_SECRET` | Upstox secret |
| `UPSTOX_REDIRECT_URI` | OAuth redirect URL |
| `UPSTOX_USER_ID` | Login user ID |
| `UPSTOX_PASSWORD` | Login password |
| `UPSTOX_PIN_CODE` | PIN code |
| `UPSTOX_TOTP_SECRET` | TOTP authenticator secret |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `PAPER_TRADE` | `True` for paper, `False` for live |
| `MOCK_MARKET` | `True` to use mock data |
| `WEBHOOK_URL` | Discord webhook for alerts |

## Database

Single table `index_spread_state` with upsert semantics (one row per symbol). Schema in [init_nifty_schema.sql](init_nifty_schema.sql).

**Warning:** No trade history table exists. When a position closes and resets, previous trade data is overwritten.

## Key Design Decisions

- **Hedge-first execution:** Long put (hedge) fills before short put to prevent naked short exposure.
- **Budget is hardcoded:** `BUDGET = 20000.0` in `wheel_strategy.py:377`, not derived from margin API.
- **Friday-only entry:** New positions open Fridays at 15:15 IST (15 min before close).
- **Hourly exit checks:** Exits evaluated Mon-Fri 9:00-15:00 on the hour. No real-time WebSocket monitoring.
- **Single-symbol focus:** Only Nifty 50 at 100% allocation in production.
- **Paper trade default:** `PAPER_TRADE=True` unless explicitly overridden.

## Conventions

- DataFrames use Polars, not Pandas (except Streamlit display via `.to_pandas()`).
- All times in Asia/Kolkata (IST). Logging is forced to IST in `main.py`.
- Token file at `data/token.json` — never commit to VCS.
- Instrument master cached at `data/nse_fo_instruments.csv` (24h TTL, FileLock protected).
- Discord alerts use embed colors: Blue=INFO, Yellow=WARNING, Red=ERROR.

## Testing

No test suite currently exists. Paper trade mode (`PAPER_TRADE=True`) and mock market mode (`MOCK_MARKET=True`) serve as manual testing mechanisms.
