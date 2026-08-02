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
  scheduler.py           APScheduler daemon (Fri 15:15 entry; hourly + WS exits)
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
- [docs/PROFITABILITY_ROADMAP.md](docs/PROFITABILITY_ROADMAP.md) - Staged profitability work (`PROF-*`, ₹50k capital constraint)

## State Machine

```
IDLE ──[Fri 15:15, VIX safe]──> STAGE_1_CSP (Credit Spread active)
STAGE_1_CSP ──[Take Profit / Stop Loss / DTE|Delta Manage]──> CLOSED
STAGE_1_CSP ──[Assignment]──> STAGE_2_CC (Covered Call)
STAGE_2_CC ──[Called Away]──> IDLE
CLOSED ──[Next cycle / same-week re-entry if TP]──> IDLE
```

Entry gates (Stage 6): VIX≤22, IVR≥50th pct, event blackout clear, spot≥SMA50, min credit/width 0.15.
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
| `MAX_CAPITAL` | Live margin clamp / capital ceiling (default `50000`) |
| `PAPER_CAPITAL` | Paper-trade budget (default `50000`) |
| `WEBHOOK_URL` | Discord webhook for alerts |

## Database

Tables `index_spread_state` (one row per symbol, upsert semantics) and `trade_history` (append-only archive of closed trades). Schema in [init_nifty_schema.sql](init_nifty_schema.sql). The `trade_history` table is auto-created at bot startup if missing.

## Key Design Decisions

- **Hedge-first execution:** Long put (hedge) fills before short put to prevent naked short exposure.
- **₹50k capital ceiling:** `MAX_CAPITAL` / `PAPER_CAPITAL` (default 50000) in `config/settings.py`. Paper uses `PAPER_CAPITAL`; live Upstox margin is clamped to `MAX_CAPITAL`. Budget = `get_available_margin() * allocation_pct`.
- **Friday-only entry (default):** New positions open Fridays at 15:15 IST. Optional mid-week entry via `ALLOW_MIDWEEK_ENTRY` (VIX band gated).
- **Exit monitoring:** Hourly `check_exits` Mon–Fri 9:00–15:00 IST as backstop; WebSocket real-time exits in live and paper when market data is available (`MOCK_MARKET` skips WS).
- **Exit rules:** TP at ≤`TP_RESIDUAL_CREDIT_FRACTION` residual credit (default 0.25); SL at ≥`SL_CREDIT_MULTIPLE`× credit (default 2.0) or spot ≤ short strike; time stop Thu ≥ 15:00 IST. VIX regimes scale OTM via `vix_regime_otm`; hard skip above `VIX_MAX_THRESHOLD` (25). Short put: target delta ≈0.18 + min credit/width; hedge width `HEDGE_WIDTH` (default 100).
- **PCS backtest:** `uv run python backtest.py` (add `--sweep` for TP/SL grid). ₹50k capital; synthetic model documented in module docstring.
- **Single-symbol focus:** Only Nifty 50 at 100% allocation in production.
- **Paper trade default:** `PAPER_TRADE=True` unless explicitly overridden.

## Conventions

- DataFrames use Polars, not Pandas (except Streamlit display via `.to_pandas()`).
- All times in Asia/Kolkata (IST). Logging is forced to IST in `main.py`.
- Token file at `data/token.json` — never commit to VCS.
- Instrument master cached at `data/nse_fo_instruments.csv` (24h TTL, FileLock protected).
- Discord alerts use embed colors: Blue=INFO, Yellow=WARNING, Red=ERROR.

## Testing

Unit tests live under `tests/` (`uv run pytest`). Paper trade mode (`PAPER_TRADE=True`) and mock market mode (`MOCK_MARKET=True`) remain available for manual end-to-end checks.
