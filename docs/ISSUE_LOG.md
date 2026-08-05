# Issue Log

Known issues, bugs, technical debt, and planned enhancements in the Nifty Theta Engine.

Last updated: 2026-08-06

Profitability / expectancy work is tracked separately in [`PROFITABILITY_ROADMAP.md`](PROFITABILITY_ROADMAP.md) (`PROF-*` stages under a ₹50,000 capital constraint).

---

## Critical

### ISS-001: Dashboard queries non-existent table `wheel_state` — FIXED

**Status:** Fixed — dashboard now queries `index_spread_state` with correct column schema.

---

### ISS-002: No trade history persistence — FIXED

**Status:** Fixed — `trade_history` table added to schema; `_archive_trade()` called before state reset on position close. Dashboard Historical Trade Ledger now queries `trade_history`.

---

### ISS-003: Dangling hedge on short leg failure has no automated recovery — FIXED

**Status:** Fixed — `_unwind_hedge()` method auto-sells Leg 1 if Leg 2 fails, with Discord alerts and fill verification.

---

## High

### ISS-004: Hardcoded budget ignores actual margin — FIXED

**Status:** Fixed — budget now uses `client.get_available_margin() * allocation_pct` with `ALLOCATION_PCT_PER_TRADE` env var.

---

### ISS-005: Exit time stop uses system clock, not IST — FIXED

**Status:** Fixed — time stop now uses `datetime.now(pytz.timezone('Asia/Kolkata'))`.

---

### ISS-006: Exit orders use price=0.0 but order type is LIMIT — FIXED

**Status:** Fixed — `place_order_by_key` auto-selects `MARKET` order type when `price=0.0`.

---

### ISS-007: No VIX circuit breaker in daily entry flow — FIXED

**Status:** Fixed — VIX check at start of `execute_daily_cycle` aborts if VIX exceeds `VIX_MAX_THRESHOLD` (env var, default 25.0).

---

### ISS-008: No exit verification after closing orders — FIXED

**Status:** Fixed — state only updates to CLOSED when both exit orders verified complete; sends Discord alert on verification failure.

---

## Medium

### ISS-009: DB connections opened and closed per operation — FIXED

**Status:** Fixed — replaced per-call `psycopg2.connect()` with `SimpleConnectionPool(1, 5)`.

---

### ISS-010: LOT_SIZES duplicated in two files — FIXED

**Status:** Fixed — `LOT_SIZES` moved to `config/settings.py`, imported by both `wheel_strategy.py` and `scheduler.py`.

---

### ISS-011: No APScheduler job persistence — FIXED

**Status:** Fixed — `_check_missed_entry()` on startup detects missed Friday entry and runs it.

---

### ISS-012: Token snippet logged in plaintext — FIXED

**Status:** Fixed — changed from `logger.info` to `logger.debug`.

---

### ISS-013: Redis connection created on every call — FIXED

**Status:** Fixed — shared `get_redis_client()` singleton in `config/settings.py`.

---

### ISS-014: `init_nifty_schema.sql` drops wrong table — FIXED

**Status:** Fixed — removed stale `DROP TABLE IF EXISTS wheel_state`.

---

## Low

### ISS-015: `ARCHITURE.md` is misspelled — NOT AN ISSUE

**Status:** File is correctly named `ARCHITECTURE.md` on disk. The only misspelled reference was in the issue log itself.

---

### ISS-016: README still references SQLite3 — FIXED

**Status:** Fixed — all SQLite3 references replaced with PostgreSQL.

---

### ISS-017: Unused dependencies in pyproject.toml — FIXED

**Status:** Fixed — removed `backtrader`, `backtrader2`, `scikit-learn`, `xgboost`, `pandas`, `podman-compose`, `joblib`, `jugaad-data`, `playwright`.

---

### ISS-018: Paper trade returns static order ID — FIXED

**Status:** Fixed — now generates `PAPER_{uuid4().hex[:8]}` unique IDs per order.

---

### ISS-019: Backtest uses simplified premium model — DEFERRED

**Status:** Acceptable for rough estimates. Would require historical options data or proper Black-Scholes implementation for accuracy.

---

### ISS-020: `execution/` module is empty — FIXED

**Status:** Fixed — removed empty directory.

---

## Enhancements

### ENH-001: No test suite — FIXED

**Status:** Fixed — `tests/` now covers state machine, exit sequencing, scheduler, client, auth, settings, and profitability logic (`test_wheel_strategy.py`, `test_exit_sequencing.py`, `test_scheduler.py`, `test_client.py`, `test_auth.py`, `test_settings.py`, `test_stage6.py`, `test_profitability.py`, `test_ws_monitor.py`).

---

### ENH-002: No position reconciliation on startup — FIXED

**Status:** Fixed — `reconcile_positions()` in `strategies/wheel_strategy.py:271`, called from `core/scheduler.py:324` on startup.

---

### ENH-003: No concurrency guard against double-entry — FIXED

**Status:** Fixed — `pg_try_advisory_lock(hashtext(symbol))` in `strategies/wheel_strategy.py:672` around entry execution.

---

### ENH-004: Pure MARKET exits risk slippage on illiquid strikes — FIXED

**Status:** Fixed — `_execute_exit` places `LIMIT` orders priced at live quote ± `EXIT_SLIPPAGE_BUFFER_PCT` (marketable-limit), not `MARKET`.

---

### ENH-005: No real-time WebSocket monitoring — FIXED

**Status:** Fixed — `ws_monitor.py` rewritten to use SDK's `MarketDataStreamerV3` (protobuf + auto-reconnect). Subscribes to Nifty 50 index LTP, debounced spot-breach detection (5s confirmation), exits via sequenced `_execute_exit`. Scheduler wires `on_realtime_tick` callback and refreshes subscriptions after position changes. Hourly poll kept as backstop. Live-only (gated by `PAPER_TRADE`/`MOCK_MARKET`).

---

### ENH-006: No config validation — FIXED

**Status:** Fixed — `config/settings.py` uses `pydantic_settings.BaseSettings` to validate configuration at startup.

---

### ENH-007: No CI/CD pipeline — FIXED

**Status:** Fixed — `.github/workflows/ci.yml` runs `ruff check`, `pytest`, and coverage on every push/PR to `main`.

---

### ENH-008: Exit legs placed simultaneously risk naked short — FIXED

**Status:** Fixed — exit orders now sequenced cover-first: buy-to-close short → verify fill → sell-to-close hedge. BTC failure leaves spread intact; STC failure after BTC fill closes position safely. P&L now uses real fill prices via `get_order_fill_price()` with fallback to theoretical cost.

---

### ENH-009: Exit P&L uses theoretical quotes, not real fills — FIXED

**Status:** Fixed — `UpstoxClient.get_order_fill_price()` reads `average_price` from `/v2/order/details`. `_execute_exit` computes P&L from actual fills when available; falls back to pre-trade cost-to-close for paper trades.

---

## Feature Gaps

These are not bugs but missing capabilities worth tracking:

| Gap | Impact | Priority |
|-----|--------|----------|
| No automated rollover after exit | Manual re-entry needed after defensive close | Medium |
| No Greeks-based exit logic | Exits purely price-based, ignoring delta/gamma | Medium |
| No multi-expiry support | One position per symbol at a time | Low |

Profitability-oriented gaps (real-time paper exits, PCS backtest, strike selection, exit param sweeps, entry timing, dashboard MTM/telemetry) are staged in [`PROFITABILITY_ROADMAP.md`](PROFITABILITY_ROADMAP.md).
