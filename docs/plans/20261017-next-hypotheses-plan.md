# Next hypotheses after the PCS FAIL — research plan

_Drafted 2026-10-17, after `20261017-real-chain-pcs-oos-result.md` (FAIL). This is a plan, not a pre-registration.
Each hypothesis that survives Phase B gets its own frozen pre-registration doc before any strategy backtest._

## 0. Ground rules (lessons from PCS v1/v2)

1. **Measure the effect before trading it.** PCS went straight to a 32-config strategy grid. This time, a cheap
   measurement study (Phase B) has to show the underlying effect exists before any P&L grid is built. If the
   effect isn't there, the hypothesis dies without a backtest.
2. **The 2024-01 → 2026-10 window is contaminated.** We know short puts lost money there, so any short-vol rule
   designed now is implicitly fitted to avoid it. It can be *reported*, but it **cannot gate a PASS**.
   Clean holdouts:
   - **OOS-A (backward):** 2011-01 → 2018-12 from the legacy bhavcopy archive, which hasn't been downloaded yet.
     There are **monthly Nifty expiries only** (weeklies began Feb 2019), so it can test monthly-tenor rules
     only. Strike liquidity is thinner; `research/quality.py` must pass on it first.
   - **OOS-B (forward):** at least 6 months of paper trading from the freeze date, with ≥20 trades or the
     result is "inconclusive", not PASS.
   - **DEV:** 2019-01 → 2023-12, as before.
3. **Multiple testing.** Up to three hypotheses are tested, so the confidence intervals for the
   expectancy-and-PF CI criteria use α = 0.05/3 (98.3% bootstrap CIs).
4. **Same pass bar as PCS v2 §6:** PF ≥ 1.30 and > 1.0 at slip 1.0, expectancy CI lower bound > 0, max DD ≤ 20%,
   after-tax CAGR ≥ 7% and above the Nifty buy-and-hold benchmark, OOS PF ≥ 0.7 × DEV PF. All must hold on OOS-A
   *and* OOS-B.
5. **Capital limits.** ₹2L, lot 65. Undefined-risk shorts (naked straddle or strangle, roughly ₹2L+ margin per
   lot) don't fit. **Short structures must be defined-risk** (iron fly or iron condor). Long structures are
   limited to their premium paid.
6. **Each holdout runs once**, with a lock file, as for `OOS_RUN.lock`. Fixing a bug found after a holdout
   run is disclosed and the original result stands.

## Phase A — shared infrastructure (all three hypotheses need it)

| # | Task | Files | Done when |
|---|------|-------|-----------|
| A1 | Download legacy bhavcopy 2011-01 → 2018-12. `bhavcopy.py` already handles the legacy format, but 2011–2018 contracts imply lot 50/75/… so the lot-size table must be extended. | `research/bhavcopy.py`, `research/reference.py` | manifest is complete; `quality.py` coverage report for 2011–18 is written; lot-size dates confirmed from the data (implied-lot method) |
| A2 | **EOD IV surface:** Black-76 IV per strike from `close` against the close-parity forward (`forward(col="close")`); ATM IV and 25Δ put/call IV per expiry per day; a constant-maturity 7d/30d ATM IV by variance interpolation. Add `_call` next to `_put`. | new `research/iv.py`, tests | round-trip test (price → IV → price) passes; 30d ATM IV correlates > 0.9 with India VIX on DEV |
| A3 | **Underlying and realised vol:** daily Nifty close, from the NSE index archive (not the parity proxy, which broke the v2 benchmark, see OOS doc). RV estimators: close-to-close 10/21d, plus HAR-RV forecast (1d/5d/22d terms, fitted **on DEV only**). | new `research/rv.py` | the benchmark and gap-day list are rebuilt from the real index; the known OOS-runner defect is fixed for future runs |
| A4 | **India VIX history** (NSE CSV), 2011 →. | `research/rv.py` | daily series with no gaps on trading days |
| A5 | **Point-in-time event calendar:** RBI MPC decision dates, Union Budget, general-election results, US FOMC decisions (IST next day), and India CPI. Only *announced-in-advance* dates; source and the date each was announced recorded per row. | `data/events.csv`, `research/events.py` | every row has a source; unscheduled RBI moves are excluded (not knowable in advance) |
| A6 | **Generalise the engine to N-leg structures** (calls and puts, long and short): straddle, iron fly, iron condor, put backspread. The current engine is PCS-specific (`_select`, `_walk`, `_expiry_value`, `_fees`). Keep the A2/A3-amendment semantics: expiry valued from `underlying_settle`, holiday-shifted expiries, exercise STT on every ITM long leg. | `research/engine.py` | all existing 17 engine tests still pass; new synthetic tests per structure; PCS v2 DEV numbers reproduce exactly through the new path |
| A7 | **Cost check:** confirm `round_trip_fees` / `exercise_stt` cover the full 2011–2026 STT and exchange-fee history (2011–18 rates differ). | `config/settings.py` | a dated table in the docstring with a source for each rate change |

Estimate: A1 runs unattended for about 2–3 h. A2/A3/A6 are the real work. **A6 is only needed if Phase B
passes**, so build it last.

**Phase A amendments (2026-10-17, made before any Phase B number was seen):**
- A3 source: the NSE index archive (`ind_close_all_DDMMYYYY.csv`) is patchy: no files for 2011–2012 and no VIX
  row before ~2015. So `research/rv.py` uses Yahoo (^NSEI / ^INDIAVIX) as the base and patches every bhavcopy
  session Yahoo lacks from the NSE archive (`src` column). Recounted after the full A1 download: 2014 onward has
  no missing closes. 15 bhavcopy sessions in 2011-05..2013-01 have no index close (the NSE archive has no files
  there), and 5 VIX values in 2013–14 are null (including 2014-02-17, the interim Budget day). Both affect OOS-A
  only. Yahoo close matches bhavcopy `underlying` on all 565 UDiFF days. iv30 vs VIX on DEV: correlation 0.988,
  iv30 about 1.5 vol points below VIX (VIX includes the OTM wings).
- A1 bhavcopy gaps: there is no options bhavcopy for 2013-10-09 or **2021-03-30 (a DEV day)** in the NSE archive.
  Every attempt returns 404; the only copy is in the `archives/fo/mkt` bundle, which has no settle price. Both
  days stay missing, and Phase B day-level measurements skip them. `fetch_day` now marks a day as a holiday only
  after three 404s.
- A3 benchmark/gap-day rebuild and the OOS-runner fix move to Phase C: no runner uses them before then.
- A5: the calendar is `research/events.csv` (`data/` is gitignored). Unscheduled moves are **kept** with
  `scheduled=False` rather than dropped, so ex-post studies can see them; ex-ante classification must filter on
  `scheduled` and `announced`. `held=False` marks scheduled meetings that did not happen (FOMC 2020-03-18; RBI
  2020-04-03 and 2020-06-05, both brought forward without notice; RBI 2020-10-01, postponed). India CPI is
  deferred: RBI, FOMC, budget and election days already give pooled n ≥ 40 for H2. CPI gets added only if H2
  reaches Phase C.
- A7 adds a fee change: exercise STT before 2019-09-01 is charged on the full settlement value. This slightly
  raises PCS DEV costs for Jan–Aug 2019; the PCS FAIL verdict is unchanged.
- A1 lot sizes for 2011–2015: derived from raw-file `VAL_INLAKH·1e5 / (contracts·(strike+settle))`. Re-checked
  on 2014-10-30/31, 2015-02-16, 2015-03-02/25, 2015-05-20, 2015-06-01/24, 2015-08-27/28, 2015-10-01 and
  2015-10-30: `lot_size()` equals the implied lot wherever it returns a value. The Mar/Jun-2015 series, listed
  before the cut, were already lot 25 once inside 45 DTE. It returns None (no answer) for far series more than 45 days out.

## Phase B — one measurement study that decides H1/H2/H3

All three ideas ask the same question from different angles: **does the option price over- or under-state the
move that follows, and can we tell which in advance?** One study answers it before any strategy is built.
It runs on DEV only. OOS-A and OOS-B are not touched.

Per (day, expiry) on DEV, compute:
- **Implied move** = ATM straddle price (close, both legs) ÷ forward.
- **Realised move** = |index at expiry − forward| ÷ forward.
- **Straddle P&L proxy** = straddle price − |S_T − F|, *after* costs at slip 0.5 per leg.

Then compare:
- **B1 (unconditional VRP):** mean and median of implied − realised, weekly (3–10 DTE) and monthly (20–35 DTE).
  Bootstrap CI, block bootstrap by expiry week.
- **B2 (conditional, for H1/H3):** split into quintiles by a signal known at entry: (i) IV30 − HAR-RV forecast,
  (ii) IV30 ÷ RV21, (iii) VIX percentile over 1 year, (iv) 25Δ put skew. Signals are fixed now. No signals get
  added after looking at the results.
- **B3 (events, for H2/H3):** expiries whose life contains a scheduled event, compared with those that don't.
  Also the 1-day straddle P&L proxy from the close before the event to the close after it, per event type.

**Gates (written down now):**
- **H1 continues** only if the top signal quintile has a straddle-P&L proxy whose 98.3% CI lower bound is > 0
  after costs *and* the effect is monotone-ish across quintiles (Spearman ρ of quintile vs mean > 0.7).
  One good bucket among noise doesn't count.
- **H3 continues** only if the *bottom* quintile (or event bucket) has a proxy CI **upper** bound < 0, i.e.
  options are reliably too cheap there.
- **H2 continues** only if n ≥ 40 events pooled, with a CI excluding 0 in one direction. With roughly 6 RBI
  meetings a year, 1 budget and about 8 FOMC meetings over 5 DEV years, a single event type can't reach 40.
  Pool them, or H2 is **underpowered by construction and dies here**. That's an acceptable outcome, not a
  reason to relax the gate.
- If nothing passes: **stop**. Write up a null result, and options-selling and buying on Nifty is shelved
  for this project.

Deliverable: `docs/plans/<date>-phase-b-measurement-result.md` with the tables, and the gate verdict per
hypothesis.

## Phase C — per-hypothesis strategy (only for those passing Phase B)

### H1 — Volatility-timed short premium
- **Idea:** sell premium only when implied volatility is rich relative to forecast realised volatility. Stay flat
  otherwise. PCS sold every week regardless, and lost the edge in the weeks where options were cheap.
- **Structure:** an iron condor or iron fly (defined risk, both sides). The B2 measurement is direction-neutral,
  so a one-sided put spread would carry an unmeasured directional bet.
- **Small grid (≤ 12 configs):** signal threshold {top quintile, top 2 quintiles} × wing width {200, 300} ×
  short-strike delta {0.15 (condor), 0.50 (fly)} × exit {hold to expiry, 50% profit}. Tenor fixed by
  whichever of weekly or monthly passed B1/B2. If **monthly**, OOS-A (2011–18) is usable. If **weekly-only**,
  OOS-B (forward paper) is the only clean holdout, and 6 months gives ~10–15 trades, so it may well end
  inconclusive. Say so up front.
- **Sizing:** risk-based as in `core/sizing.py`. Max loss = wing − credit.
- **Specific risk:** a regime break when vol is cheap and then gaps. The stress test is Feb–Mar 2020 (DEV)
  plus the worst OOS-A month (2011 euro crisis, Aug 2015, Sep 2018 IL&FS).

### H2 — Event-driven structures
- **Idea:** scheduled events have a known date, so IV is bid up before them and collapses after. The question
  is whether the crush pays more than the move costs (short), or the reverse (long).
- **Structure:** decided by the B3 sign. Short side: iron fly entered at the close before the event and exited
  at the close after it. Long side: straddle or strangle over the same window.
- **Grid (≤ 6 configs):** expiry choice {nearest, next} × structure width {ATM fly / straddle, 1σ condor /
  strangle} × event set {pooled, ex-FOMC}.
- **Specific risks:** n is small, and OOS-A has events (RBI, budgets, elections 2014) but only monthly options,
  so near-event IV in 2011–18 sits on longer tenors. That's a different instrument and has to be documented
  as such. Results from 2–3 election days must never carry the pooled result. Report a leave-one-event-type-out
  sensitivity.

### H3 — Buying volatility
- **Idea:** the mirror of H1. Buy when options are reliably too cheap (bottom quintile or a specific event
  bucket). Long-vol P&L is many small losses and rare large wins, so the sample-size problem is worse than for
  selling. Expect wide CIs.
- **Structure:** long straddle, or a long put spread / put backspread when B2 shows the cheapness is on the
  downside (skew signal).
- **Grid (≤ 8 configs):** signal bucket {bottom quintile, bottom 2} × structure {straddle, 1:2 put backspread}
  × exit {expiry, 2× premium target}.
- **Honest prior:** global evidence says index options are on average *over*-priced (positive VRP). H3 most
  likely dies at the Phase B gate. It's included because the measurement costs nothing extra, not because it's
  expected to work.

### Common steps for each surviving hypothesis
1. Freeze a pre-registration doc (grid, winner rule, criteria from §0.4, holdout dates) and get the user's
   approval *before* the DEV run.
2. Run the DEV grid. The winner rule is the same as PCS v2 §3.
3. Run OOS-A once, with a lock file.
4. If OOS-A passes, run OOS-B on the paper bot: wire the frozen rule into `strategies/` behind a flag, deploy to
   Oracle (paper only), with a fixed 6-month window and a lock on the evaluation.
5. Live trading only if OOS-A and OOS-B both pass. That's a separate decision with the user, starting at 1 lot.

## Order and stop points

```
A1,A2,A3,A4,A5,A7 ──> B (measurement, DEV only) ──> gate per H
                                                      ├─ none pass ─> null write-up, STOP
                                                      └─ pass ─> A6 engine ─> C: prereg ─> DEV ─> OOS-A ─> OOS-B paper
```

User decision points: (1) after Phase B results, (2) approving each pre-registration, (3) any deploy to
Oracle, (4) any live capital.

## What happens to the running PCS paper bot
Unchanged by this plan. It can keep running as an operational test of the execution stack (fills, WS exits,
token bus), which H1/H2 will reuse. It can be disabled on request. Its P&L isn't evidence for anything here.
