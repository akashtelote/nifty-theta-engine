# HANDOFF — Phase A / E-plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
_Updated: 2026-10-18 · post-compact_

## Goal
Order A1→A2→A3→A4→E1→E2→A6→E4→A5→E3. Paper only. No deploy/.env changes, no OOS runs (OOS only on user's go).
Now: **E3 (plan lines 170-237)**: pre-gate done (PASS), next DEV P&L + gates, report PASS/FAIL, no OOS.

## Status
- Done + pushed: A5 (5164d97, graphify 22553a7). A1-A4, E1/E2/E4 DEV FAIL, A6. A5 reported to user.
- E3 pre-gate: research/e3_trend.py (`... -m research.e3_trend pregate`, writes data/futures/e3_pregate.txt).
  DEV 9/9 holdable PASS; LAST12 6/9 PASS (NIFTY 32.8%, BANKNIFTY 16.2%, COPPER 0% fail cap). Told user.
  Pregate evaluator PASS. DEV R1 (a498ae88) fixed: roll-day vol ret from own contract, FY loss carry-forward,
  margin over all held markets, px close<=0 dropped. R2 (a4755636) fixed: vol annualised by own sessions/yr (MCX
  Saturdays), LAST12 pregate at current lot sizes (NIFTY 53%, BANKNIFTY 36.8%, still 6/9 PASS), fill guard for
  new-product orders, gates() no-position raise + null TRI month. **E3 DEV FAIL** gate 2 CI [-1.07%, 19.67%]
  (R0 -1.69%, R1 -1.26%); Sharpe 0.69, corr 0.06, worst-10% +0.48%, MDD 19.7%, margin 0%; CAGR 8.09%, orders 1674,
  rolls 711, costs Rs5.25L, tax Rs11.25L. R3 = final evaluator round (cap 3) -> if findings, stop and report. Outputs data/futures/e3_dev.txt + e3_dev_nav.parquet. tests/test_e3.py 3 pass.
  NEXT: evaluator on all dirty files -> commit -> graphify -> push -> report DEV FAIL to user. No OOS.
- A7 futures fees were missing: added config/settings.py futures_fees(value, on, buy, exch) dated STT/CTT/txn/stamp
  table + tests/test_costs.py::test_futures_fees_dated (16 pass). Needs evaluator too.
- UNCOMMITTED: research/e3_trend.py, config/settings.py, tests/test_costs.py, HANDOFF.md.

## E3 design notes
- products(): per product held contract (continuous.parquet) close, mult (null -> implied value/(lots*close) per
  contract), ret = adj diff/(close - adj diff), EWMA vol hl 60 x sqrt252, turnover median prior 60 sessions.
- choose(): per market re-pick smallest-notional product clearing Rs5cr & >=60 listed at ref-product rolls/join or if
  held product missing; join after 252 ref sessions.
- Next: DEV sim weekly (last session of week signal from ref adj_close sign k=63/126/252; fill next open of
  held contract - needs open from load(); trade if |diff|>=1 lot & >=25%), costs futures_fees + slippage 1 tick +
  0.02%/side + roll cost (close old/open new at roll), margin 12% NSE / 10% MCX > 60% cap days, tax 30% + cess FY
  (research/metrics.py TAX_RATE / e2 fy_tax), gates vs T-bill (benchmarks.load tbill), Nifty 50 TRI corr, worst 10%
  Nifty months, MDD 30%, stationary bootstrap 98.75% (e2_momentum.stationary_ci uses its CONF/BLOCK consts).

## A5 state (2026-10-18 ~07:30)
- All fetched, 0 error days: NSE 5392 sessions, CDS 3859 (2010-11..; earlier 404 = unavailable, in report), MCX 6152.
- build done: data/futures/{report.txt,continuous.parquet,contracts.parquet}. NSE+CDS gaps 0; MCX base products
  gapless except early COPPER/ALUMINIUM; mini products have delisting spans (2020-23) counted as gaps.
- Evaluator round 1 (agent a4f7ae934c21bb741) findings all fixed: CDS UDiFF value*1e5 & mult 1000 (refetched
  2024-07-08..), NSE lots snap to NSE_LOTS set + contract mode within 15%, roll gap from last common quoted day,
  load() dedupes, report ratio by year. Also fixed: 2-digit expiry year (_dmy; 2012-05-14 refetched), empty
  continuous skip. Round-2 PASS was not recorded by gate (SendMessage resume) -> fresh evaluator afb5a1f290366cb2e
  found: CDS weeklies in roll (fixed: monthly() per-day last-expiry-of-month), MCX soft-throttle-as-holiday (fixed:
  only Message "No data found." = holiday; 98 weekday holidays re-verified), mult float noise (round 6 in load+parse),
  BANKNIFTY 2025-01-29->01-30 re-dated contract (gap 0 when never co-quoted & <=7d apart). Not fixed (report to user):
  CDS 2008-08..2010-10 unavailable; tick is current-spec hand table. 11 tests pass.
- Round 3 evaluator a546f08c70a631052 = FINDINGS (cap reached): CDS weekly after monthly (USDINR 2022-04-29),
  MCX unpublished recent day cached as holiday, tail roll. All fixed (monthly min_share 0.1 lifetime lots; MCX
  "pending" if d >= today-2; weekday count past data end). 13 tests pass; rebuilt; NSE/CDS gaps 0; held-vs-top-volume
  mismatches only re-dated months (CDS 2019-04 6d, BANKNIFTY 2024-03/2025-01 17d). UNCOMMITTED.
- User OK'd round 4 (aa8da35060e98f157) = FINDINGS: single empty MCX reply cached as holiday (fixed: confirm on a
  fresh page; 2005-12-16 refetched -> still empty twice, MCX has no data = known hole); page.close() could escape
  and periodic save keyed on len(done) (fixed: try/except, counter n). UNCOMMITTED.
- User: "proceed without asking again" (keep looping evaluator rounds). R5 a0698: MCX mult null outside MCX_SPEC
  (now explicit in report), dead-browser abort after 5 error days + finally-save, MCX rows after expiry (load filter,
  MCX only), per-contract tick col. R6 a3d2f: UDiFF CDS stale ClsPric on lots=0 (continuous prices untraded at
  settle), NSE postponed expiries 2005-07-29/2008-11-28 kept. 14 tests pass; rebuilt. UNCOMMITTED.
  R7 aa6f9: re-date to EARLIER expiry (BANKNIFTY 2024-03-28->03-27, CDS 2019-04-26->04-25) rolled to next month
  18 sessions early -> fixed: roll guard compares (year, month). 15 tests pass; rebuilt; all next-month rolls at 5.
  R8 a90ef4f7f3fc247be = PASS (minor: 4 far-month BANKNIFTY 2007 legacy mult days wrong, never held; CRUDEOIL
  adj_close negative 2020 -> downstream use adj diff / real close). Gate recorded PASS but not for futures.py etc:
  diff output truncated -> headers missing; hook also wants untracked HANDOFF.auto.md (add -N it, reset before commit).
  DONE. Gate lesson: evaluator must print each `diff --git` header unprefixed (no grep -n, no truncated output);
  untracked HANDOFF.auto.md + history need add -N for review then reset before commit.
  NOW: E3 (plan lines 170-237): feasibility pre-gate first, DEV only; data = data/futures/{continuous,contracts}.parquet
  (use adj_close diff / real close for returns; CRUDEOIL adj negative 2020).

## A5 probe findings (2026-10-18)
- **MCX loadable.** Land https://www.mcxindia.com/market-data/bhavcopy (playwright, chromium-1234 executable_path
  fallback as in research/deals.py), then in page: `GetData("/GetDateWiseBhavCopy","GET",{InstrumentName:"ALL",
  fromDate:"dd/mm/yyyy"}, ok, err)` (site helper; real URL /market-data/bhavcopy/GetDateWiseBhavCopy). Response
  `.Data` list of {Date "MM/DD/YYYY", Symbol (padded), ExpiryDate "30OCT2026", Open/High/Low/Close, PreviousClose,
  Volume (lots), VolumeInThousands "2152.000 KGS" (qty, unit), Value (lakhs?), OpenInterest, InstrumentName
  FUTCOM/OPTFUT..., StrikePrice, OptionType}. Works 2006-01-05, 2012, 2023, 2026 (2026 ~15.5k rows incl options →
  keep FUTCOM only). Lot = qty*1000/Volume (in unit) when Volume>0. Zero-volume rows have Open=0 (use as no-trade).
  Ticks not in bhavcopy → hand table of current specs (ceiling documented).
- **NSE FUTIDX:** research/bhavcopy.py parse keeps only NIFTY OPTIDX; raw zips not cached; manifest covers
  2011-01-01..2026-10-16 only. Need re-download 2005-01..2026-09 with a FUTIDX parser (NIFTY, BANKNIFTY) via
  `fetch_day(d, s, parser=..., out=...)` (keyword args exist for reuse). Legacy has no lot size: research/reference.py
  has NIFTY lot table/implied lot (VAL_INLAKH*1e5/(contracts*price)); UDiFF has NewBrdLotQty.
- CDS (USDINR 2008-08+, others 2010-02+): secondary only; not probed yet (archive nsearchives .../archives/cd/bhav/?).

## Commit workflow (unchanged)
- Evaluator (independent-evaluator, foreground) must print raw `git diff HEAD -- <paths>` headers; untracked files
  `git add -N`; history snapshots `git add -N .claude/handoff/history/` for evaluator then `git reset
  .claude/handoff/history/` in a separate call before commit. Never commit HANDOFF.auto.md, data/token.json,
  20261016_plan.md. Commit msg ends "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".
- After code commit: `graphify update .`; `git checkout -- graphify-out/cache/last_query_stamp`; add -N graphify-out +
  history; evaluator SendMessage on graphify headers; reset history; commit "Graphify changes"; push.
- Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run --extra research python -m research.<mod>`.
- Never rerun PCS OOS (data/bhavcopy/OOS_RUN.lock). Never suggest ETFs/MFs/index funds.

## Next step
1. Write research/futures.py: MCX daily FUTCOM fetch (cache per day raw JSON→parquet, resumable), NSE FUTIDX
   (NIFTY/BANKNIFTY) via bhavcopy.fetch_day with new parser/out, product first-trade dates, lot sizes, tick table,
   continuous series (roll 5 sessions before expiry, additive back-adjust; real contracts kept for P&L). CDS secondary.
2. Test, run fetch (background), coverage report, evaluator, commit, graphify, push, report A5 → then E3
   (feasibility pre-gate first, before any P&L).
