# Equity and futures hypotheses (E1–E4): research plan and pre-registration

_Drafted 2026-10-17, after Phase B (`20261017-phase-b-measurement-result.md`, all FAIL; the options-premium branch
is stopped). The rules and parameter values below are **frozen now, before any return data for these ideas has
been loaded**. The only data looked at so far is a feasibility probe: are the files there, and what format are
they in (§A0)._

## 0. Ground rules

1. **One primary rule per hypothesis, no grids.** The parameters below are fixed. Variants marked
   *secondary* are reported but cannot produce a PASS.
2. **Multiple testing:** four hypotheses, so every gating CI is at α = 0.05/4 (**98.75%**). Bootstrap
   choices are named per hypothesis.
3. **Windows:**

   | | DEV | OOS (run once, with a lock file) |
   |---|---|---|
   | E1, E2, E4 | 2010-01 → 2018-12 | 2019-01 → 2026-09 |
   | E3 | 2005-01 → 2015-12 | 2016-01 → 2026-09 |

   After an OOS PASS, ≥ 6 months of forward paper trading (OOS-B), as in the earlier plan.
4. **Contamination note.** I already know, in broad terms, that Indian mid/small caps and momentum did very well
   in 2020–24, and that the papers say index-inclusion effects shrank after about 2015. The rules here were
   written knowing that, not tuned on any data. The OOS window holds both of those regimes, which helps E2 and
   hurts E1. Neither of those is a reason to change the windows.
5. **Benchmarks are bars to beat, never the recommendation.**
   - E1 and E4 are event strategies that are invested only part of the time. They are gated **per event**:
     abnormal return against the **Nifty 500 price index** from entry-session open to exit-session close, with no
     dividends on either leg (as defined in E1), after costs.
   - E2 is gated as a portfolio. It must beat the **Nifty 500 TRI** and the **Nifty200 Momentum 30 TRI**
     after costs and tax: if a passive momentum index does as well, our version has no edge.
   - E3 must beat the risk-free rate (91-day T-bill) and has to add diversification (§E3).
6. **Costs and tax are always included.** That means STT, exchange fees, stamp duty, GST, DP charges and the
   slippage model per hypothesis, using the dated rate for each period (A7). Tax rates below exclude
   surcharge. Cess:
   - 2% up to FY2006-07;
   - 3% for FY2007-08 to FY2017-18;
   - 4% from FY2018-19.
   - **Equity STCG:** 15% (20% from 2024-07-23), plus cess.
   - **Equity LTCG:**
     - exempt up to 2018-03-31;
     - then 10% above ₹1L, grandfathered to the 2018-01-31 price;
     - 12.5% above ₹1.25L from 2024-07-23;
     - plus cess.
   - **Futures:** P&L taxed as business income at 30% plus cess:
     - 30.6% up to FY2006-07;
     - 30.9% for FY2007-08 to FY2017-18;
     - 31.2% from FY2018-19.
7. **Exits nobody chooses: delisting, suspension, or a move to trade-to-trade (E1, E2, E4).**
   - **Suspended or delisted:** if a held stock (by permanent stock ID, A1) has no EQ- or BE-series row for 5 consecutive
     sessions **that have a bhavcopy file**, it is exited at its last close minus a **30% haircut**, booked on
     the 5th missing session. A1 gap days don't count toward the 5.
     - This applies whether the cause was merger, delisting or suspension.
     - The haircut is conservative for mergers and roughly the average delisting loss for distress cases.
   - **Moved EQ → BE (trade-to-trade):** the holding is valued on the BE series and sold at the next scheduled
     exit or rebalance.
8. **A null result is reported as a null**, the same as for PCS and Phase B.

## Phase A — data (feasibility first)

### A0. Feasibility probe (done 2026-10-17)

| Source | Result |
|---|---|
| NSE equity bhavcopy, legacy `cm{DD}{MON}{YYYY}bhav.csv.zip` | 200 for 2010 |
| NSE equity bhavcopy, UDiFF (2024-07-08 →) | 200 |
| NSE F&O bhavcopy 2005 | 200; holds FUTIDX/FUTSTK as well as options |
| NSE currency (CDS) bhavcopy 2012 | 200 |
| `PREVCLOSE` | **not adjusted** for corporate actions. INFY 2014-12-02: close 2126.6, prev 4349.85 (1:1 bonus) |
| NSE historical bulk/block deals API | **503 to scripted requests** (bot wall) |
| MCX bhavcopy | Page loads, but download goes through a form (ASP.NET postback). Not yet scriptable |
| niftyindices.com | Reachable; index-change press releases are published as PDFs |

### A-tasks

| # | Task | Needed by | Done when |
|---|---|---|---|
| A1 | **Equity bhavcopy loader**, 2005 → 2026-09, EQ and BE series, legacy plus UDiFF. Same pattern as `research/bhavcopy.py`, saved to `data/equity/`. Each stock gets a **permanent stock ID** built from its ISIN. The legacy files carry the ISIN from about 2011, and earlier rows are mapped through NSE's symbol-change list. A face-value split issues a new ISIN, so ISINs are **chained**: a new ISIN continues an old one when its first session is the old ISIN's next session after the last, it has the same issuer and security-type code (ISIN characters 3–9, e.g. `E009A01` in INE009A01021), and it has the same symbol or a symbol linked in the symbol-change list. Every chain link is listed in the coverage report. This keeps a rename or split from looking like a delisting, and history carries across it. | E1 E2 E4 | manifest complete; coverage report; gap days listed |
| A2 | **Corporate-action adjustment** (splits, bonuses, rights). First choice: NSE corporate-action history through a browser session. Fallback: flag a day where open/prevclose is within 1.5% of a standard ratio (1:1, 1:2, 2:1, 5:1, 10:1, …), then confirm it against NSE or BSE corporate-action filings (never Yahoo, which is the gate's reference). If any adjusted event in the gate sample is confirmed only by Yahoo, the gate is **not run**. Dividends are **not** added back (this is conservative: the TRI benchmarks include them). | E1 E2 E4 | Checked on the first 50 stocks of the fixed sample defined below. Gate: the test days are the split/bonus events in yfinance's `splits` series (Yahoo records Indian bonuses as splits) for those stocks. On those days, the adjusted daily return from the A2 series must be within 0.1 percentage points of the return from Yahoo's split-adjusted `Close` on **≥ 95% of the days**. Yahoo's dividend adjustment is not used. An unadjusted loader fails this by construction. At least 20 test days are needed: below that, more survivors are drawn from the same sequence, 10 at a time, until there are 20 test days. The sample is fixed in advance: survivors (stocks listed on both 2010-01-04 and 2026-09-30), sorted by permanent stock ID and shuffled with `random.Random(20261017)`, taken in that order, with no redraws; and if 20 still can't be found the gate is **not run, which is not a pass**. The match rate over all days is reported, not gated. |
| A3 | **Benchmarks:** Nifty 50 TRI, Nifty 500 TRI and Nifty200 Momentum 30 TRI, daily, from the niftyindices historical download. 91-day T-bill yield from RBI. Nifty 500 **price-index** daily open and close from NSE's daily index snapshot (`ind_close_all`), for the E1/E4 event windows. | all | no gaps on trading days |
| A4 | **Index-change archive** from niftyindices press releases, 2010 →, for Nifty 50, Nifty Next 50, Nifty Midcap 150 (Midcap 100 before it existed) and Nifty 500. Columns: announce date and time, effective date, index, symbol, add/remove, scheduled review or ad hoc, source URL. | E1 | every row has a source; scheduled semi-annual reviews are complete for DEV (checked against the review count) |
| A5 | **Futures data:** extend `bhavcopy.parse` to keep FUTIDX (NIFTY, BANKNIFTY) in a new output. MCX (primary for E3): script the bhavcopy form, or find an archive, and record each contract's first trading date. CDS loader (USDINR from 2008-08; EURINR, GBPINR, JPYINR from 2010-02) for the E3 secondary only. Build continuous series that roll 5 sessions before expiry, **additively** back-adjusted for the signal (ratio adjustment breaks on negative prices such as MCX crude on 2020-04-20), and using real contracts for P&L. Record lot size and tick per contract and date. | E3 | NSE + CDS series without gaps; MCX either loaded or declared unavailable (see E3 universe rule) |
| A6 | **Bulk/block deal history:** try a browser session (playwright, as `core/smart_money.py` already does); otherwise any public archive. Also look for point-in-time shares outstanding (quarterly shareholding-pattern filings). | E4 | ≥ 5 years of daily deal history, or E4 is declared **untestable historically** (see E4). The shares source is optional (E4 has a fallback). |
| A7 | **Fee and tax table** for equity delivery and futures (NSE FO, CDS, MCX CTT), 2005–2026, in a dated docstring with a source for each change. | all | same standard as A7 in the previous plan |

**Order:** A1 → A2 → A3 → A4 → **E1** → **E2** → A6 → **E4** → A5 → **E3**. E1 and E4 are cheap event studies;
E3 needs the most data work. An A-task that fails its "done when" stops only the hypotheses that depend on it.

## E1 — index-inclusion drift (₹2L)

**Claim.** Stocks added to an index at a scheduled review rise between the announcement and the effective date,
because index funds must buy them at the close before the effective date. Retail can buy after the
announcement.

- **Events:** additions at scheduled semi-annual reviews of Nifty 50, Next 50, Midcap 150/100 and Nifty 500.
  Ad hoc replacements (mergers, suspensions) are reported separately and do not gate. A stock added to two
  indices at once counts as one event. It is filed under the index with the most passive money tracking it,
  in this order: Nifty 50, Next 50, Midcap 150/100, Nifty 500.
  - A stock moving up from Next 50 to Nifty 50 is one Nifty 50 addition.
  - The matching Next 50 removal from that move is not counted as a removal.
- **Trade:**
  - Buy at the **open of the first session after the announcement** (announcements come after market hours;
    if one came during market hours, buy at the next open).
  - Sell at the **close of the last session before the effective date**, when index funds trade.
  - Long only: retail cannot hold a cash short overnight, so removals are measured but not traded.
- **Slippage:** 0.25% per side on top of fees.
- **Abnormal return:** stock return minus the benchmark return over the same window. Both legs run from the
  entry-session **open** to the exit-session **close**.
  - The benchmark leg is the **Nifty 500 price index**, which carries an open in NSE's daily index snapshot
    (added to A3). The TRI has no open, so it isn't used here.
  - Neither leg includes dividends (A2 doesn't add them back), so the comparison is like for like.
- **Measurement gate (DEV):** n ≥ 40 events, **and** the mean net abnormal return has a 98.75% CI lower bound
  > 0. The bootstrap resamples whole review dates, because events in one review share a market move.
- **OOS gate (per event):**
  - the mean net abnormal return has a 98.75% CI lower bound > 0;
  - the OOS mean is ≥ 0.5 × the DEV mean;
  - the review-level mean is positive in ≥ 60% of OOS reviews.
- **Portfolio (reported for DEV and OOS, not gated):**
  - ₹2L is split equally across each review's additions, in whole shares.
  - A stock priced above its slot gets 0 shares, and the slot is left in cash.
  - Between reviews the capital earns 0. It is invested only a few weeks per review, so this is a satellite
    strategy, not a standalone one.
- **Secondary (reported only, can't PASS):**
  - entry at the announcement-day close instead of the next open (shows what the gap costs);
  - removals shorted through stock futures when the stock is in F&O;
  - ad hoc events.

## E2 — cross-sectional momentum with our own filters (₹2L)

**Claim.** Stocks with the highest past 12-month return (skipping the last month) keep outperforming. A broader
universe with monthly rebalancing and a market-regime exit beats both the market and the passive momentum
index.

- **Universe** (point in time, built from bhavcopy, so delisted stocks are included):
  - at each month-end, EQ-series stocks with ≥ 13 months of history (counted across the permanent stock ID's
    ISIN chain, A1) and close ≥ ₹20;
  - the top 500 of those by 6-month median daily traded value.
- **Signal:** return from t−12 months to t−1 month, using A2-adjusted closes.
- **Timing:** the universe, the signal and the regime filter are all computed from the close of the **last
  session of month m−1**. Trades execute at the **close of the first session of month m**.
- **Portfolio:**
  - **Slots:** the portfolio holds **25 slots**.
  - **Keep or sell:** a holding is kept, at its current value and not re-weighted, while its rank is ≤ 50.
    Holdings ranked worse are sold.
  - **Refill:** cash from the sales, plus any idle cash, is split equally across the highest-ranked names not
    already held, until 25 are held. Whole shares only. A name whose price is above its slot is skipped and
    the next rank is used.
- **Regime filter (primary, part of the rule):**
  - The universe index is a daily-rebalanced equal-weight average of the returns of the current universe
    members, chained from 2009-01 so the DEV start already has 200 days of history.
  - The filter is checked **only at the month-end close (month m−1)**, never intra-month. If the index is
    below its 200-day average there, the whole portfolio is sold to **cash** at the close of the first session
    of month m.
  - It is re-entered at the first monthly rebalance where the index is back above its average, by filling 25
    fresh slots.
- **Slippage:** 0.15% per side for the top 200 by traded value, 0.35% for the rest. Positions are capped at 2%
  of the stock's median daily traded value. At ₹2L that cap never binds; it is there for when capital grows.
- **Gates (DEV and OOS, all must hold):**
  1. After costs and tax, CAGR beats the **Nifty 500 TRI** and the **Nifty200 Momentum 30 TRI** over the same
     window.
  2. Monthly excess return over the Nifty 500 TRI has a mean whose 98.75% CI lower bound is > 0. The bootstrap
     is a stationary block bootstrap with a mean block of 6 months.
  3. Max drawdown ≤ 35%.
  4. OOS annualised excess ≥ 0.5 × DEV.
- **Secondary (reported only):**
  - the rule without the regime filter;
  - top 25 by 6-month momentum;
  - semi-annual rebalancing, to show the turnover cost against the passive index.

## E3 — trend-following on futures (₹20L)

**Claim.** Time-series momentum across Indian index, currency and commodity futures earns a return above
risk-free that is lowly correlated with Nifty, especially in Nifty sell-offs.

- **Universe (primary): only markets a retail trader can actually trade today.**
  - NIFTY and BANKNIFTY futures (NSE).
  - MCX underlyings: gold, silver, crude oil, natural gas, copper, zinc, aluminium. Each market joins once it
    has 252 sessions of history.
  - **One underlying = one market.** On each date, a market trades the **smallest-notional contract listed**
    for it that day (for example GOLDPETAL / GOLDGUINEA / GOLDM / GOLD; SILVERMIC / SILVERM / SILVER;
    CRUDEOILM / CRUDEOIL; NATGASMINI / NATURALGAS; the mini where one exists for the base metals).
  - A switch to a newly listed smaller contract happens at the next roll.
  - A contract with a median daily turnover below ₹5 crore over the prior 60 sessions is skipped, and the next
    smallest is used. Turnover is measured **per product** (e.g. GOLDM), summed across all its listed expiries,
    not per expiry. A product listed for fewer than 60 sessions at a roll is skipped at that roll.
  - The floor is checked **only at rolls** (and when a market first joins). If no listed contract clears it, the
    market is **not live** until the next roll where one does. A market that isn't live counts toward neither N
    nor the feasibility pre-gate.
  - **Currency futures are excluded from the primary.** Since 2024-05-03, RBI rules require an underlying
    exposure to trade them, so a retail trader can no longer take speculative positions. A result that
    depended on them could not be traded or paper-traded.

  **If A5 cannot load MCX, E3 stops.** Two equity-index futures are not a trend-following portfolio.
- **Signal:** per market, the average of sign(P_t − P_{t−k}) for k = 63, 126 and 252 sessions, where P is the
  additive back-adjusted series of one **fixed reference product** per underlying: the base contract (NIFTY,
  BANKNIFTY, GOLD, SILVER, CRUDEOIL, NATURALGAS, COPPER, ZINC, ALUMINIUM). It is never spliced across products,
  because they quote in different units (e.g. GOLDPETAL per 1 g vs GOLD per 10 g). The traded product can still
  differ from the reference product. It is computed as a price difference, not a % return, because that series can
  go negative. A tie (P_t = P_{t−k}) counts as sign 0, so the signal takes one of the values −1, −⅔, −⅓, 0, +⅓, +⅔ or +1.
- **Sizing:**
  - Target annual vol per market = 15% / √N, where N is the number of markets live on that day.
  - Market vol is an EWMA with a 60-session half-life of daily % returns of the **actual held contract**
    (unadjusted). On a roll day, that day's return is taken on the new contract (close-to-close).
  - Position in lots = signal × target ÷ (vol × lot notional), rounded to whole lots.
  - **No position is opened if even 1 lot exceeds 2× the market's target risk.**
- **Rebalance:** weekly.
  - Signal, vol and target lots are computed from the close of the week's last session (normally Friday).
  - Orders fill at the **open of the next session**. Slippage, costs and contract choice all apply to that fill.
  - Trade only when the target differs from the current position by
  ≥ 1 lot and by ≥ 25%.
- **Costs:** fees per A7, slippage 1 tick + 0.02% of notional per side, and a roll cost on every roll.
- **Margin check:** SPAN margin is estimated at 12% of notional (MCX 10%). If the estimated margin exceeds
  60% of capital on any day, that day is recorded. More than 5% of days recorded = infeasible.
- **Feasibility pre-gate (₹20L, run first, before any P&L is read).** At least half of the live markets must
  be holdable at ≥ 1 lot within the 2× risk cap on ≥ 80% of days, in **both** windows:
  - **DEV** days, with the lot sizes of that time;
  - the **last 12 months** (2025-10 → 2026-09), with current contract specs. Index contracts have had a ₹15L+
    minimum since the 2024-11 SEBI rule.

  If either window fails, E3 stops as "not implementable at ₹20L" and no P&L is computed.
  - Prior: a NIFTY lot (about ₹16–19L notional, ≈ ₹2.2L+ annual vol) likely breaches the cap of
    ≈ 2 × 15%/√N × ₹20L.
  - So in practice this test is mostly about whether the MCX mini contracts carry the portfolio.
- **Gates (DEV and OOS, all must hold):**
  1. Net Sharpe ≥ 0.5 after costs and tax.
  2. Annual excess over T-bill has a 98.75% CI lower bound > 0. Stationary block bootstrap, mean block 3 months.
  3. Correlation of monthly returns with the Nifty 50 TRI ≤ 0.3.
  4. Mean return in Nifty's worst 10% of months > 0 (this is the diversification case).
  5. Max drawdown ≤ 30%.
  6. OOS Sharpe ≥ 0.5 × DEV.

  Honest prior: a trend Sharpe of about 0.5 over 11 years has a standard error of about 0.3, so gate 2 is hard
  to pass unless the edge is strong. That is intended.
- **Secondary (reported only):**
  - NSE stock futures added to the universe;
  - CDS currency futures added, for history only (not tradable by retail since 2024-05);
  - monthly rebalancing.

## E4 — institutional bulk/block "whale" signal (₹2L)

**Claim.** Stocks with net institutional buying in NSE bulk/block deals outperform afterwards.

- **Signal: the bot's own rule** from `core/smart_money.py` (`process_smart_money`, commit `19d5216`),
  **frozen**:
  - per stock-day, sum the bulk and block deal quantity of clients whose name contains an
    `INSTITUTIONAL_KEYWORDS` entry, buys minus sells;
  - **whale = 1 if the net is > 0.5% of shares outstanding.**

  The keyword list is not tuned. The result tests what the bot uses.
- **Shares outstanding, point in time:** taken from the latest quarterly shareholding filing *published* before
  the deal date, if A6 finds such a source.
  - The filed share count is scaled by the A2 split/bonus factors between the filing's **as-of date (quarter-end)** and the deal date,
    so that it uses the same share basis as the deal quantity.
  - The bot's live `sharesOutstanding` value is current data, so it would leak lookahead and is not used.
- **Fallback when no point-in-time source exists:**
  - NSE flags a client's bulk deal when that client's trades in the stock are > 0.5% of listed shares.
  - The fallback rule is: **whale = 1 if total net institutional quantity is > 0 and at least one institutional
    client has a bulk-deal row that day with its own net buy (its buys minus its sells that day) > 0.**
    Otherwise whale = 0, including days with only block-deal buys.
  - This approximates the 0.5% rule rather than reproducing it exactly.
  - The result doc states which version ran.
- **Events:**
  - stock-days with whale = 1;
  - a stock that triggers again within 20 sessions is one event;
  - mirror net-sell events are measured too.
- **Trade:**
  - Buy at the **open of the next session** after the deal date (deal data is published after the close).
  - Hold 20 sessions.
  - Slippage 0.25% per side.
- **Gates (DEV and OOS):**
  - n ≥ 200 buy events;
  - the 20-session net abnormal return, measured as in E1 (next-open entry, exit-session close, against the
    Nifty 500 price index, no dividends on either leg), has a 98.75% CI lower bound > 0. The bootstrap is a
    moving block bootstrap over calendar weeks, with block length **8 weeks** (≥ 2× the 20-session hold), so that
    overlapping holds stay together;
  - OOS mean ≥ 0.5 × DEV.
- **Secondary (reported only):** holds of 5 and 60 sessions; net-sell events; block deals alone.
- **If A6 cannot get ≥ 5 years of history:** E4 is **untestable historically**.
  - It becomes a forward-only test: log every event daily from the start date, and evaluate after
    12 months with the same gate.
  - Until it passes, the bot's whale score should not drive any trading decision.

## Decision points for the user

- After A0–A4: report data coverage, plus anything declared unavailable.
- After each hypothesis's DEV gate: report PASS/FAIL. On a DEV FAIL that hypothesis stops (no rule changes).
  On a DEV PASS, it moves to OOS only after the user says go.
- No live money, deploy or `.env` change comes out of this plan without asking. The paper bot is not touched.
