# Profitability Roadmap

Staged tracker for expectancy improvements to the Nifty put credit spread engine.

Last updated: 2026-08-06

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

### PROF-021: Measurement rebuild — the tuning target was wrong

**Status:** OPEN. Do not tune further until the slippage question below is answered.

PROF-001..020 were all ranked on a backtest that did not simulate this bot. Three
divergences, now fixed:

| | backtest was | live is | effect |
|---|---|---|---|
| Strike band | searched to `spot*0.92` | clamped to `spot*0.97` | ranked trades the bot cannot take |
| Sizing | always 1 lot | `floor(budget/width·lot)` @ `allocation_pct=1.0` → 20 lots | understated drawdown ~20× |
| Friction | none | brokerage + STT + txn + GST + bid-ask | see curve |

Friction now modelled: `round_trip_fees()` in `config/settings.py` (flat ₹20/order ×4,
STT 0.1% sell-side, txn 0.03503%, GST 18% on brokerage+txn) plus `slippage_points`,
a per-side points haircut on entry credit and exit cost. Both are also subtracted
from live `realized_pnl` — `trade_history` and the dashboard were reporting gross.

**Friction sensitivity, real `^NSEI`/`^INDIAVIX` 2021-01 → 2026-08, 65 trades:**

| slippage/side | PF | Total P&L | ruin_proxy |
|---|---|---|---|
| 0 | 1.38 | +65,688 | 0.64 |
| 0.5 | 1.09 | +15,646 | 0.88 |
| **0.6 (breakeven)** | **~1.00** | **~0** | ~0.92 |
| 0.75 | 0.95 | −7,135 | 0.96 |
| 1.0 | 0.87 | −19,228 | 0.98 |
| 1.5 | 0.69 | −35,786 | 1.05 |
| 2.0 | 0.57 | −43,025 | 1.10 |

2026 YTD after the rebuild: PF 0.22, −₹31,033 (was 0.40 on the 1-lot model — the
model and the live book now disagree by less than tuning noise).

**Decision gate — failed on all three criteria:** net PF ≥ 1.2 (actual 0.57 @ slip 2),
2026 net P&L > 0 (actual −31,033), ruin_proxy ≤ 0.20 (actual 1.10).

Findings, in order of leverage:

1. **FIXED (2026-08-06):** `allocation_pct=1.0` in `core/scheduler.py:18` put the
   whole account in one spread; `ruin_proxy` ≥ 0.64 even at zero slippage. The
   `ALLOCATION_PCT_PER_TRADE=0.15` default in settings existed but was never read —
   `TARGET_SYMBOLS` now sources it from settings instead of hardcoding `1.0`.
2. **The edge dies at ~0.6 points of slippage per side.** `EXIT_SLIPPAGE_BUFFER_PCT
   =0.02` alone is ~0.6 pts on a 30-pt option, before any bid-ask crossing. The
   strategy is priced to lose at its own configured execution quality.
3. **`STOP_ON_STRIKE_TOUCH` is inert, not the culprit.** `ctc >= 2.0×credit` always
   trips before spot reaches the short strike at credit/width ≥ 0.15 on a 100-wide
   spread. Disabling *both* stops (`sl_multiple=99`) took 2021-26 from PF 0.79 to
   1.02 — the SL multiple is what harvests the losses.
4. Sweep ranked `hedge_width=300` best; every 100-wide cell was negative. Per-leg
   friction against 3× the credit. `PF 1.02–1.03` at n=65 is inside noise — read as
   absence of a large loss, not as an edge.

**Next step is a measurement, not a tune:** paper mode already logs fills. Measure
realized slippage per side against the 0.6 breakeven. Everything else is downstream
of that number.

**2026-08-06:** entry-side fill quality was already logged (`PAPER fill quality`,
`wheel_strategy.py`), but exit-side wasn't — `_execute_exit` computed
`actual_cost_to_close` vs `theoretical_cost` and discarded the comparison. Added a
matching `PAPER fill quality ... (exit)` log line with `slippage_per_leg`. No
historical run data exists to mine (stdout-only logging, nothing persisted) — this
starts accumulating from the next paper session onward. Still needed: let paper mode
run and pull both log lines to get an actual number against the 0.6pt breakeven.

**2026-08-06 re-run, corrected sizing:** `backtest.py`'s `PCSParams.allocation_pct`
default was still hardcoded `1.0`, silently matching the live bug from finding #1
above rather than tracking it. Fixed to read `settings.ALLOCATION_PCT_PER_TRADE`
(now `0.15`) and re-ran the same real `^NSEI`/`^INDIAVIX` 2021-01→2026-08 series:

| slippage/side | PF | Total P&L | ruin_proxy |
|---|---|---|---|
| 0 | 1.08 | +1,941 | 12.7% |
| 0.2 (new breakeven) | 1.00 | −26 | 13.5% |
| **0.6 (old breakeven)** | **0.89** | **−2,423** | **15.5%** |
| 1.0 | 0.78 | −5,263 | 18.1% |
| 1.5 (default) | 0.67 | −8,180 | 21.0% |
| 2.0 | 0.54 | −12,009 | 27.2% |

2026 YTD (6 trades): PF 0.30, −₹2,077.

Decision gate still fails on all three criteria (PF 0.67 vs ≥1.2, 2026 P&L −2,077 vs
>0, ruin_proxy 21.0% vs ≤20%) — but the *shape* changed:
- **Ruin risk is fixed.** `ruin_proxy` at slippage 1.5 dropped from 105% (old,
  `allocation_pct=1.0`) to 21% — the sizing bug was masking a survivable strategy as
  an account-destroying one. This confirms finding #1 was correctly diagnosed as the
  acute risk, separate from the edge question.
- **Breakeven slippage dropped from ~0.6pt to ~0.2pt/side.** Flat per-order fees
  (`round_trip_fees`) don't scale down with position size, so at 15% allocation
  (~3 lots vs ~20 before) they eat a much larger share of a smaller trade's credit.
  Smaller size reduces ruin, but tightens the margin for error on execution quality —
  the two findings trade off against each other, they don't independently resolve.

Net: sizing is no longer the blocker; the edge itself, after realistic fixed-cost
drag, still isn't there. The slippage measurement from live paper fills (once
logged) is now more urgent, not less — the tolerance for bad fills just shrank.

Unchanged caveat (see ISS-019): still BS(VIX) with no skew, so IV-richness is only
partly modelled. These rank configurations; they are not absolute expectancy.

---

### PROF-022: Lot size was 25; NSE lists 65

**Status:** DONE (2026-08-06) for the fixes; the slippage measurement it enables is OPEN.

`config/settings.py` held `LOT_SIZES = {"Nifty 50": 25}` and `backtest.py` held
`NIFTY_LOT = 25`. The Upstox instruments master the bot already downloads
(`data/nse_fo_instruments.csv`, refreshed every 24h for `_get_instrument_token`) lists
**65** for every one of the 1,760 NIFTY OPTIDX rows.

Consequences, in order of severity:

1. **Live orders were malformed.** Entry sent `num_lots × 25` shares. 25 is not a
   multiple of 65, so the exchange rejects the quantity outright. Paper mode never
   surfaced it — nothing validates quantity there.
2. **Sizing was 2.6× off.** `num_lots = floor(budget / (width × lot))` divided by
   ₹2,500 instead of ₹6,500.
3. **Every PROF-001..021 number was computed on a contract that does not exist.**

This is the third instance of the same bug class after the two `allocation_pct`
hardcodes in PROF-021 — a constant duplicating a value the system already knows.
The fix removes the constant rather than correcting it: `UpstoxClient.get_lot_size()`
and `settings.lot_size_from_master()` read the master, `LOT_SIZES` is deleted, and
there is **no fallback** outside `MOCK_MARKET`. A missing master aborts entry.
`backtest.py` raises rather than defaulting, so a sim can never silently size a
contract the bot cannot trade.

Also fixed in passing: three exit paths defaulted to `LOT_SIZES.get(symbol, 25)` when
the stored position quantity was missing — closing a *guessed* size on a real
position. They now skip the position and log an error.

**Re-run, real `^NSEI`/`^INDIAVIX` 2021-01 → 2026-08, lot 65, alloc 15%, width 100:**

| slippage/side | Trades | PF | Total P&L | ruin_proxy |
|---|---|---|---|---|
| 0 | 65 | 1.14 | +3,520 | 11.0% |
| 0.2 | 65 | 1.07 | +1,831 | 12.6% |
| **0.4 (breakeven)** | **65** | **1.01** | **+141** | **14.3%** |
| 0.6 | 65 | 0.94 | −1,550 | 15.9% |
| 1.0 | 39 | 0.60 | −7,767 | 19.2% |
| 1.5 (default) | 23 | 0.46 | −6,742 | 16.3% |
| 2.0 | 19 | 0.37 | −6,996 | 16.2% |

2026 YTD @ 1.5: 9 trades, PF 0.23, −₹5,993.

**Decision gate:** PF ≥ 1.2 → **fails** (0.46). 2026 net > 0 → **fails** (−5,993).
ruin_proxy ≤ 0.20 → **passes** (16.3%). Two of three, same as before the fix.

What actually changed:

- **Breakeven slippage moved from ~0.2 to ~0.4 pt/side.** Roughly double the tolerance
  PROF-021 reported, but still inside the bid-ask on a Nifty weekly. The edge is thin,
  not obviously absent.
- **The strategy is barely fundable at ₹50k.** One 100-wide spread at lot 65 costs
  ₹6,500 of max loss against a ₹7,500 per-trade budget (15% of ₹50k) — exactly one lot,
  with ₹1,000 of the budget stranded. Worse, `budget = min(equity, MAX_CAPITAL) × 0.15`
  means **trading stops entirely once equity drops below ₹43,334**. That is what the
  collapsing trade counts above are: the ≥1.0 slippage rows did not survive the period,
  they ran out of fundable capital partway through. Their P&L is therefore optimistic —
  2.0 looks *better* than 1.0 only because it stopped losing sooner.
- **`hedge_width=300`, the sweep's preferred cell, is unreachable.** ₹19,500/lot against
  a ₹7,500 budget is zero lots. It should stop being read as an available option.

**Still open — the measurement PROF-021 called for.** Fill quality is now persisted
rather than logged to a stdout nobody captured (`logs/` held only `.gitkeep`):
`trade_history.entry_slippage_per_leg` / `exit_slippage_per_leg`, with
`index_spread_state.theoretical_credit` carrying the entry-side mid to archive time.
The dashboard reports the mean against the 0.4 breakeven. Rows predating this change
are null, not zero. **Next step is unchanged: run paper mode and read the number.**

#### Minimum viable capital

Capital enters the result through one channel: `num_lots = floor(min(equity, MAX_CAPITAL)
× alloc / (width × lot))`. More lots spread the flat ₹94/round-trip brokerage over more
credit. Slippage scales with lots and never amortises, which sets a hard ceiling.

Same real path, 2021-01 → 2026-08, alloc 15%, width 100:

| Capital | Lots | PF @0.4 | PF @0.6 | PF @1.0 | PF @1.5 |
|---|---|---|---|---|---|
| ₹50k | 1 | 1.01 | 0.94 | 0.60 | 0.46 |
| ₹75k | 1 | 1.01 | 0.94 | 0.82 | 0.69 |
| ₹100k | 2 | 1.13 | 1.06 | 0.93 | 0.65 |
| **₹200k** | 4 | **1.20** | 1.12 | 0.99 | 0.81 |
| ₹500k | 11 | 1.24 | 1.16 | 0.99 | 0.85 |
| ₹5M | 115 | 1.26 | 1.18 | 1.03 | 0.87 |

PF asymptotes at ~1.26. Ten times the capital between ₹500k and ₹5M buys 0.02 of PF.
**What capital actually buys is slippage tolerance: breakeven moves from ~0.4 to ~1.05
pt/side, and no further.** So: at ≥1.1 pt/side no budget works; at ~0.6 no budget clears
the PF ≥ 1.2 gate (ceiling 1.18); at ~0.4 the minimum is **₹200,000**. ₹50k–₹75k is a
dead band — both fund exactly one lot, so the extra ₹25k buys only survival past the
₹43,334 funding cliff, not size.

#### Why 97.5% of the account is idle

| | |
|---|---|
| Days holding a position | 392 / 2038 = **19.2%** |
| Deployed while in a trade | ₹6,500 / ₹50,000 = **13%** |
| Time-weighted utilisation | **2.5%** |

Friday census over the sample (272 Fridays): 65 entered (23.9%), **19 blocked by an open
position (7.0%)**, **188 blocked by an entry gate (69.1%)**. Concurrent positions would
recover ~19 trades in 5.6 years. The gate stack — IVR, VIX, SMA50 trend, event blackout,
min credit/width — is the real throttle, consistent with PROF-020's 30-Friday blackout.

Three structural reasons the capital sits:

1. `ALLOCATION_PCT_PER_TRADE=0.15` — a *per-trade* risk cap (PROF-021 finding #1) applied
   to a system that only ever holds one trade, so it caps total exposure.
2. Lot granularity: ₹7,500 budget, ₹6,500 per spread, ₹1,000 stranded. `alloc` 0.15 and
   0.25 produce byte-identical runs — both round to 1 lot.
3. One position per symbol. `index_spread_state.symbol` is the PRIMARY KEY; `state[symbol]`
   holds a singular active/hedge pair; entry requires `current_stage in (IDLE, CLOSED)`;
   the advisory lock is per symbol. `backtest.py` mirrors this with a scalar `in_trade`
   flag, deliberately — a harness that models trades the bot cannot take is what PROF-021
   was written about. Concurrency means re-keying positions by ID, not a config toggle.
   `ALLOW_MIDWEEK_ENTRY` is already on but inert for the same reason.

**Allocation sweep at ₹50k, slippage 0.4:**

| alloc | lots | PF | Total P&L | Max DD | ruin |
|---|---|---|---|---|---|
| 0.15 | 1 | 1.01 | +141 | 7,124 | 14.2% |
| 0.40 | 3 | 1.06 | +3,867 | 16,374 | 32.7% |
| 0.60 | 4 | 1.12 | +11,072 | 24,498 | 49.0% |
| 1.00 | 7 | 1.18 | +29,436 | 36,790 | 73.6% |

Deploying more does improve PF — fixed fees amortise — but ruin tracks it straight up.
**At ₹50k, safe sizing and fee-efficient sizing are mutually exclusive:** ruin ≤ 20% or
PF → 1.2, not both. This is the ₹200k result seen from the other side. At ₹200k a 15%
allocation buys 4 lots, so the fee amortisation and the risk cap coexist. The idle
capital is not a bug — ₹50k cannot fund a fee-efficient position without betting the
account.

Caveat unchanged from ISS-019: still BS(VIX) with no skew, so IV richness is only
partly modelled. These rank configurations; they are not absolute expectancy. The
return-on-account figures are further depressed by the single-position design — with
2.5% utilisation, account-level return measures the harness's shape, not the edge.

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
| Hedge width | 100 pts | **100** | 100×65 = ₹6,500/lot (PROF-022) |
| Lot size | `LOT_SIZES` dict = 25 | **from instruments master (65)** | No constant; aborts if unreadable |
| Min credit/width | 0.12 | **0.15** | Reject thin credits |
| VIX crisis skip | 25 | **22** | Tighter left-tail |
| IVR min percentile | n/a | **30** | Retuned in PROF-020 |
| Midweek / re-entry | off | **on (gated)** | IVR+filters required |
