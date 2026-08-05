# Profitability Roadmap

Staged tracker for expectancy improvements to the Nifty put credit spread engine.

Last updated: 2026-08-02

> **Capital constraint:** All sizing, backtests, and live/paper configs must operate within **₹50,000** total capital (`MAX_CAPITAL` / `PAPER_CAPITAL` in [`config/settings.py`](../config/settings.py); paper returns `PAPER_CAPITAL`, live clamps to `MAX_CAPITAL` in [`core/client.py`](../core/client.py)). One-lot margin check: `(spread_width × lot_size) ≤ 50000`.

Related: bug/enhancement debt lives in [`ISSUE_LOG.md`](ISSUE_LOG.md). This file tracks profitability work only (`PROF-*`).

## Status model

| Status | Meaning |
|--------|---------|
| `TODO` | Not started |
| `IN_PROGRESS` | Actively being implemented |
| `DONE` | Merged and verified |
| `BLOCKED` | Waiting on a dependency |
| `DEFERRED` | Intentionally postponed |

## Progress

| Stage | Focus | Issues | Status |
|-------|--------|--------|--------|
| 0 | Baseline constraint and truth | PROF-001, PROF-002 | DONE |
| 1 | Protect downside | PROF-003, PROF-004 | DONE |
| 2 | Measure, then retune exits | PROF-005, PROF-006, PROF-007 | DONE |
| 3 | Higher quality premium | PROF-008, PROF-009 | DONE |
| 4 | Entry timing and regime | PROF-010, PROF-011 | DONE |
| 5 | Execution polish | PROF-012, PROF-013, PROF-014 | DONE |
| 6 | Expectancy levers | PROF-015 … PROF-019 | DONE |

```mermaid
flowchart LR
  S0[Stage0_CapitalDocs] --> S1[Stage1_RealtimeExits]
  S1 --> S2[Stage2_ExitRulesBacktest]
  S2 --> S3[Stage3_StrikeSelection]
  S3 --> S4[Stage4_EntryTimingVIX]
  S4 --> S5[Stage5_FillsAndPolish]
  S5 --> S6[Stage6_ExpectancyLevers]
```

---

## Stage 0 — Baseline constraint and truth

### PROF-001: Formalize ₹50k capital ceiling

**Status:** DONE

**Severity:** High — sizing must not exceed working capital

**Description:** Paper trade uses a hardcoded `50000.0` budget in [`core/client.py`](../core/client.py). Live mode uses Upstox margin uncapped by this ceiling. Formalize `PAPER_CAPITAL` / `MAX_CAPITAL` (or equivalent) in [`config/settings.py`](../config/settings.py), clamp paper and live sizing to ₹50,000, and keep scheduler `allocation_pct` compatible so effective budget never exceeds the ceiling.

**Acceptance criteria:**
- Settings expose an explicit capital ceiling defaulting to `50000`
- Paper and live position sizing both respect the ceiling
- Unit tests cover paper, mock, and live clamp paths
- Docs state the ₹50k constraint

**Verification:** `MAX_CAPITAL` / `PAPER_CAPITAL` in settings (exported); paper returns `min(PAPER_CAPITAL, MAX_CAPITAL)`; live clamps API margin; tests in `tests/test_client.py` + `tests/test_settings.py`.

---

### PROF-002: Sync strategy docs to actual code

**Status:** DONE

**Severity:** Medium — wrong mental model blocks safe tuning

**Description:** [`WHEEL_STRATEGY_MANUAL.md`](../WHEEL_STRATEGY_MANUAL.md) still describes 50% take-profit, DTE≤3 defensive exits, ML VIX regime OTM scaling, and dynamic OTM percents. Live code in [`strategies/wheel_strategy.py`](../strategies/wheel_strategy.py) uses:
- Take profit: `cost_to_close ≤ 0.20 × initial_credit` (≈80% of credit captured)
- Stop loss: `cost_to_close ≥ 2.0 × initial_credit` or spot ≤ short strike
- Time stop: Thursday ≥ 15:00 IST
- VIX: static `VIX_MAX_THRESHOLD` (default 25.0)
- Short put: fixed `otm_pct = 0.01`, hedge width 100 points

**Acceptance criteria:**
- Manual, ARCHITECTURE, and CLAUDE strategy notes match code
- Stale ML / 50% TP / DTE≤3 claims removed or marked historical
- Doc change reviewed against `check_exits` and `_select_target_put`

**Verification:** Manual/ARCHITECTURE/CLAUDE updated to match `check_exits` and `_select_target_put`; ML/50% TP/DTE≤3 marked historical.
---

## Stage 1 — Protect downside

### PROF-003: Enable real-time exits in paper mode

**Status:** DONE

**Severity:** High — hourly-only stops leave gap risk

**Description:** [`core/scheduler.py`](../core/scheduler.py) starts the WebSocket monitor only when `not PAPER_TRADE and not MOCK_MARKET`. Paper mode therefore evaluates stops only on the hourly cron (`mon-fri 9-15`). Enable the real-time path for paper so stop-loss behavior matches intended live protection while still routing paper orders.

**Acceptance criteria:**
- WebSocket (or equivalent tick) exit path runs under `PAPER_TRADE=True` when market data is available
- Paper orders remain non-broker (`PAPER_*` IDs)
- Hourly `check_exits` remains as backstop
- Tests or documented manual paper verification of breach → exit

**Verification:** `_start_ws_monitor()` runs when `MOCK_MARKET=False` regardless of `PAPER_TRADE`; unit tests in `tests/test_scheduler.py`. Paper orders still via `PAPER_*` in client. Hourly `_run_exits` unchanged. Manual: start with `PAPER_TRADE=True MOCK_MARKET=False`, confirm WS log line and that exits still use paper order IDs.

---

### PROF-004: Discord alert on WebSocket fallback

**Status:** DONE

**Severity:** Medium — silent fallback hides unprotected periods

**Description:** When the WS monitor fails to start or drops, the bot logs a warning and falls back to hourly polling. Add an explicit Discord notification so operators know real-time protection is offline.

**Acceptance criteria:**
- Discord WARNING on WS start failure / missing token / monitor stop with fallback
- Hourly poll continues uninterrupted
- No alert spam: debounce or single alert per failure episode

**Verification:** `_notify_ws_fallback` debounces via `_ws_fallback_alerted`; covers missing token, start exception, and streamer `on_error` callback. Tests assert single WARNING per episode.
---

## Stage 2 — Measure, then retune exits

### PROF-005: PCS backtest harness matching live rules

**Status:** DONE

**Severity:** High — cannot tune without measurement

**Description:** [`backtest.py`](../backtest.py) is equity-wheel oriented (stock tickers, simplified premiums). Build or extend a put-credit-spread harness that mirrors live entry (OTM/DTE/width), exits (TP/SL/time stop), and **initial capital ₹50,000**.

**Acceptance criteria:**
- Backtest uses ₹50,000 starting capital
- Rules align with current (or parameterized) live exit/entry logic
- Outputs include win rate, avg P&L, max drawdown, exit-reason mix
- Runnable via documented CLI/`uv run` command

**Verification:** `uv run python backtest.py` and `--sweep`. Synthetic GBM + Black–Scholes puts (no historical NSE chain). Metrics via `BacktestResult`. Tests in `tests/test_profitability.py`.

---

### PROF-006: Parameterize TP / SL / time-stop / DTE manage

**Status:** DONE

**Severity:** High — hardcoded exits block controlled experiments

**Description:** Exit thresholds are hardcoded in `check_exits` (`0.20`, `2.0`, Thursday 15:00). Move them to settings/env (and optionally DTE-based manage) so PROF-007 can sweep without code edits.

**Acceptance criteria:**
- Settings for TP residual credit fraction, SL multiple, time-stop weekday/hour, optional DTE manage
- `check_exits` reads settings only (no magic numbers)
- Defaults preserve current behavior until PROF-007 changes them
- Unit tests cover each trigger path

**Verification:** `TP_RESIDUAL_CREDIT_FRACTION`, `SL_CREDIT_MULTIPLE`, `TIME_STOP_*`, `DTE_MANAGE_THRESHOLD` in settings; exit path tests in `tests/test_profitability.py`.

---

### PROF-007: Sweep and pick default exit params under ₹50k

**Status:** DONE

**Severity:** Medium — depends on PROF-005 and PROF-006

**Description:** Using the PCS harness, sweep exit parameters under the ₹50k capital constraint. Document chosen defaults and rationale in this roadmap (update Status + a short “Chosen defaults” subsection under this issue when done).

**Acceptance criteria:**
- Sweep results recorded (table or linked artifact)
- New defaults committed in settings
- Roadmap updated with chosen values and why
- No default assumes capital > ₹50,000

**Sweep artifact (synthetic, seed=42, ~3y daily bars):**

| TP residual | SL mult | Win% | Total PnL | Max DD |
|-------------|---------|------|-----------|--------|
| 0.30 | 2.5 | 64.7% | 5270 | 3801 |
| 0.15 | 2.5 | 63.3% | 5046 | 3484 |
| 0.20 | 2.5 | 63.3% | 5000 | 3484 |
| 0.25 | 2.5 | 63.3% | 4865 | 3630 |
| 0.30 | 1.5 | 60.7% | 3913 | 2573 |
| **0.20** | **2.0** | 62.7% | 2291 | 4000 |
| **0.25** | **2.0** | 62.7% | 2156 | 4146 |

**Chosen:** TP `0.25`, SL `2.0`, time stop Thu ≥ 15:00. Rationale: earlier TP than legacy `0.20` (locks more winners on synthetic paths where Time Stop otherwise dominates); keep SL at `2.0` as a live-friendly compromise between synthetic PnL (favors 2.5) and drawdown (favors 1.5). Hedge width 100 × lot 25 = ₹2,500 ≪ ₹50k.

**DEFERRED measurement:** Ranking used synthetic GBM + BS premiums — not historical NSE option chains. Re-run `uv run python backtest.py --sweep` when chain data is available before further retunes.

---

## Stage 3 — Higher quality premium

### PROF-008: Delta- or credit/width-based short put selection

**Status:** DONE

**Severity:** High — fixed 1% OTM is a weak edge

**Description:** `_select_target_put` uses hardcoded `otm_pct = 0.01` and nearest strike. Replace with target-delta and/or minimum credit-per-width selection while remaining liquid and within ₹50k margin.

**Acceptance criteria:**
- Selection rule documented (e.g. target delta band or min credit/width)
- Slippage/liquidity guardrails retained (bid present, spread ≤ 15%)
- Fits ₹50k one-lot capital constraint with chosen hedge width
- Unit tests with synthetic chains

**Verification:** BS put-delta approx + `MIN_CREDIT_WIDTH_RATIO` scoring; `MAX_BID_ASK_SPREAD_PCT`; tests in `tests/test_profitability.py`.

---

### PROF-009: Configurable hedge width under ₹50k

**Status:** DONE

**Severity:** Medium — fixed 100-pt width may be suboptimal

**Description:** Hedge is fixed at `short_strike - 100`. Make width configurable and enforce `(width × lot_size) ≤ MAX_CAPITAL` (₹50,000) so sizing never requests unfundable lots.

**Acceptance criteria:**
- Hedge width from settings
- Abort or shrink with clear log if width × lot exceeds capital ceiling
- Tests for valid width and over-budget rejection

**Verification:** `HEDGE_WIDTH` setting; abort log when width×lot > `MAX_CAPITAL`; unit tests for valid/over-budget.

---

## Stage 4 — Entry timing and regime

### PROF-010: Regime-aware OTM / skip logic

**Status:** DONE

**Severity:** Medium — binary VIX gate is crude

**Description:** Entry aborts only when VIX > `VIX_MAX_THRESHOLD`. Evolve to regime-aware OTM width scaling and/or skip logic. Align or retire stale ML VIX docs from PROF-002.

**Acceptance criteria:**
- Documented mapping from VIX (or regime) → OTM aggressiveness or skip
- Behavior covered by tests
- Docs match implementation

**VIX → action mapping (`vix_regime_otm`):**

| Regime | Condition | Action | OTM |
|--------|-----------|--------|-----|
| Low | VIX < 13 | enter | 1.2% |
| Normal | 13 ≤ VIX < 18 | enter | 1.0% |
| Elevated | 18 ≤ VIX ≤ 25 | enter | 1.5% (defensive) |
| Crisis | VIX > 25 | **skip** | — |

---

### PROF-011: Optional non-Friday entry when regime favors it

**Status:** DONE

**Severity:** Medium — Friday-only limits premium opportunities

**Description:** Entry cron is Friday 15:15 IST only. Add an optional path for mid-week entry when IV/regime criteria pass, keeping Friday as the default schedule.

**Acceptance criteria:**
- Feature flag or setting; default remains Friday-only
- Missed-entry / lock logic still prevents double entry
- Compatible with single open position per symbol and ₹50k capital

**Verification:** `ALLOW_MIDWEEK_ENTRY=False` by default; midweek cron + VIX band `[MIDWEEK_VIX_MIN, MIDWEEK_VIX_MAX]`; advisory lock unchanged; missed-entry respects session.

---

## Stage 5 — Execution polish

### PROF-012: Entry fill improvement (mid / requote)

**Status:** DONE

**Severity:** Low–Medium — snapshot bid/ask leaves credit on the table

**Description:** Entries use a single bid/ask snapshot. Improve with mid-price targeting and limited requote/cancel-replace before abort, without violating slippage guardrails.

**Acceptance criteria:**
- Documented entry pricing policy
- Paper mode records theoretical vs achieved credit for comparison
- No naked short: hedge-first sequencing preserved

**Verification:** `ENTRY_USE_MID_PRICE` + `ENTRY_REQUOTE_*`; hedge-first `_place_entry_leg_with_requote`; paper logs theoretical mid/natural vs achieved.

---

### PROF-013: Unrealized / mark-to-market on dashboard

**Status:** DONE

**Severity:** Medium — operators cannot see open P&L quality

**Description:** [`dashboard.py`](../dashboard.py) shows persisted state only. Add unrealized P&L for open `STAGE_1_CSP` from live (or last) option marks.

**Acceptance criteria:**
- Open positions show unrealized P&L and/or cost-to-close
- Degrades gracefully when quotes unavailable
- Does not require capital > ₹50k assumptions

**Verification:** Active positions table shows `cost_to_close` / `unrealized_pnl` or `n/a`.

---

### PROF-014: Closed-trade telemetry for ongoing tuning

**Status:** DONE

**Severity:** Medium — need feedback loop after exits exist

**Description:** `trade_history` is append-only but the dashboard lacks aggregate stats. Surface win rate, average credit, realized P&L, and exit-reason mix to support continued PROF tuning under ₹50k.

**Acceptance criteria:**
- Dashboard (or report) shows aggregates from `trade_history`
- Exit reasons grouped (Take Profit, Stop Loss, Time Stop, Expiry, etc.)
- Empty history shows a clear empty state, not errors

**Verification:** Closed-Trade Telemetry section; empty-state message when no rows.

---

## Stage 6 — Expectancy levers

### PROF-015: Walk-forward measurement

**Status:** DONE

yfinance `^NSEI`/`^INDIAVIX` paths + VIX-calibrated BS; optional `data/option_chains/` parquet/CSV loader; CLI `--walk-forward` / `--sweep` / `--from-yahoo`. Metrics include profit factor and ruin_proxy.

### PROF-016: IVR entry gate

**Status:** DONE

`SKIP_LOW_IVR`, `IVR_LOOKBACK_DAYS`, `IVR_MIN_PERCENTILE` (default 30, was 50 — see PROF-020). Cached VIX history in `data/india_vix_history.json`. Discord INFO on skip.

### PROF-017: Exit policy retune

**Status:** DONE

| Param | Default |
|-------|---------|
| TP residual | **0.50** |
| Time stop | **disabled** (`TIME_STOP_WEEKDAY=-1`) |
| DTE manage | **7** |
| SL multiple | **2.0** |
| Short delta manage | **0.30** |

### PROF-018: Left-tail controls

**Status:** DONE

Event blackout (`config/event_calendar.py`), SMA50 trend filter, `VIX_MAX_THRESHOLD=22`, `MIN_CREDIT_WIDTH_RATIO=0.15`.

### PROF-019: Same-week re-entry + midweek

**Status:** DONE

`ALLOW_SAME_WEEK_REENTRY=True` (cap 1/week via Redis after Take Profit). `ALLOW_MIDWEEK_ENTRY=True` still gated by IVR + event + trend + midweek VIX band.

### PROF-020: IVR gate retune (50 → 30)

**Status:** DONE (2026-08-05)

Triggered by a live `IVR 44.0 < min 50.0` entry skip. Swept `ivr_min` through
`run_pcs_backtest` on real `^NSEI`/`^INDIAVIX` 2021-01 → 2026-08:

| ivr_min | Trades | Win% | PF | Total P&L | Ruin |
|---------|--------|------|------|-----------|------|
| off | 113 | 73.5% | 1.62 | ₹8,397 | 6.0% |
| 25 | 66 | 72.7% | 1.50 | ₹4,324 | 6.0% |
| **30** | 61 | 70.5% | 1.36 | ₹3,058 | 6.0% |
| 40 | 49 | 69.4% | 1.26 | ₹1,878 | 5.4% |
| 50 (old) | 43 | 72.1% | 1.40 | ₹2,399 | 4.0% |

Bootstrap (20k resamples) on per-trade P&L, gate off vs 50: diff `+18.4`,
95% CI `[-101.6, +145.0]`, P(off>on) 61%. **The gate was not selecting better
trades, only fewer** — it discarded 62% of entries whose expectancy was
statistically indistinguishable from those it kept. Gate held VIX below its own
252d median, so low-vol regimes produced long droughts: a 30-consecutive-Friday
blackout 2025-06-20 → 2026-01-16.

Caveats on this evidence:
- n=43 in the gated arm; the sweep is non-monotonic (50 scores above 35/40), so
  individual rows are noise-dominated. Only the trade-count effect is robust.
- Backtest prices at BS(VIX), so IV-richness-vs-realized — what IVR proxies for —
  is only partly modelled. This biases *against* finding IVR value; the result
  says this implementation doesn't pay its opportunity cost, not that the concept
  is wrong.
- `MIDWEEK_VIX_MIN=16` is untested here (`entry_weekday=4` is hardcoded, so the
  midweek path never enters the sim). Left at 16 deliberately. It is inert
  whenever VIX < 16, which covers most of the current regime.

**Open:** 2026 YTD is negative in both arms (PF 0.45 ungated / 0.40 gated) — the
base strategy, not the entry gate, is the live problem.

---

## Chosen defaults (after Stage 6)

| Parameter | Pre-sweep code | Stage 6 default | Notes |
|-----------|----------------|-----------------|-------|
| Capital ceiling | Paper ₹50k hardcoded | ₹50,000 (`MAX_CAPITAL`/`PAPER_CAPITAL`) | Hard constraint |
| TP residual credit | `0.25` | **`0.50`** | ~50% of credit — higher hit rate |
| SL multiple | `2.0` | **`2.0`** | Unchanged |
| Time stop | Thu ≥ 15:00 IST | **disabled** | DTE/delta manage instead |
| DTE manage | off (−1) | **7** | Last week manage |
| Short delta manage | n/a | **0.30** | PROF-017 |
| Short OTM / delta | Target δ≈0.18 | **δ≈0.18 + regime OTM** | + IVR / trend / events |
| Hedge width | 100 pts | **100** | 100×25 ≤ ₹50k |
| Min credit/width | 0.12 | **0.15** | Reject thin credits |
| VIX crisis skip | 25 | **22** | Tighter left-tail |
| IVR min percentile | n/a | **30** | Retuned in PROF-020 |
| Midweek / re-entry | off | **on (gated)** | IVR+filters required |
