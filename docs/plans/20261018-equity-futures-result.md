# Equity and futures hypotheses E1–E4: DEV results, all four FAIL

_Written 2026-10-18. Plan: `20261017-equity-futures-hypotheses-plan.md` (pre-registered, gates fixed before any run).
Only DEV windows were used. No OOS window was run, and none will be, because per the plan's "Decision points" a DEV
FAIL stops that hypothesis with no rule changes._

## Verdict

| Hypothesis | DEV window | Gate (from the plan) | Result |
|---|---|---|---|
| E1 index-inclusion drift (₹2L) | 2010–2018 | n ≥ 40, 98.75% CI lower bound of mean net abnormal > 0 | **FAIL**: n = 548, mean net −2.09%, CI [−4.22%, +0.47%] |
| E2 12-1 momentum + regime filter (₹2L) | 2010–2018 | CAGR > Nifty 500 TRI and Nifty200 Momentum 30 TRI; CI lower > 0; MDD ≤ 35% | **FAIL** on all three: CAGR 10.84% vs 9.94% / 17.98%, CI [−1.24%, +1.66%]/month, MDD 41.9% |
| E3 futures trend (₹20L) | 2005–2015 | Sharpe ≥ 0.5, CI lower > 0, corr ≤ 0.3, worst-10% Nifty months > 0, MDD ≤ 30% | **FAIL** on the CI only: Sharpe 0.69, CI [−1.07%, +19.67%]/yr |
| E4 institutional "whale" buys (₹2L) | 2010–2018 | n ≥ 200, CI lower bound of mean net abnormal (20 sessions) > 0 | **FAIL**: n = 1,711, mean net −2.40%, CI [−3.78%, −0.97%] |

All four are reported as nulls. None of the four rules showed an edge over its benchmark after costs (and, for E2/E3,
tax) that holds at the 98.75% confidence level (α = 0.05/4).

## Per hypothesis

**E1** (`data/e1/dev_report.txt`, commit 96cdc63)
- The gross drift on scheduled adds is about zero (+0.04%). Costs turn it negative.
- 6 of 18 reviews had a positive mean.
- Secondary variants were reported only:
  - The announcement-close entry does slightly better (net −1.81%) but is still not significant.
  - Removals and ad hoc adds are reliably negative on the long side, with CI upper bounds below 0.
  - Shorting removals would need stock futures, which were not loaded, so the short side is untested.

**E2** (`data/e2/dev_report.txt`, commit 7b9d1ef)
- The rule beats Nifty 500 TRI but trails the passive Nifty200 Momentum 30 TRI by about 7 points a year.
- The regime filter kept the portfolio in cash for 39 of 108 months, and it still had a 41.9% drawdown.
- The no-filter secondary (+18.14%) only matches the passive momentum index, and its CI still includes 0.
- So our filters added no edge over the passive momentum index.

**E3** (`data/futures/e3_dev.txt`, `e3_pregate.txt`, commit 9525ba1)
- Feasibility pre-gate: PASS in DEV (9/9 markets holdable). The last 12 months at current lot sizes give 6/9 holdable.
- DEV, net of fees, slippage, rolls and FY tax with losses carried forward:
  - CAGR 8.09% as excess over the T-bill (futures P&L / NAV, no collateral interest credited; the 91-day T-bill
    averaged 6.97% for reference);
  - correlation with Nifty 50 TRI 0.06;
  - +0.48% mean in Nifty's worst 10% of months;
  - max drawdown 19.7%;
  - the 60% margin cap was never breached.
- The return looks diversifying, but 10 years of data cannot separate its excess from zero at 98.75%.
- Capacity is a real constraint at ₹20L. In the last 12 months:
  - 1 lot of NIFTY fits the risk cap on only 53% of days;
  - BANKNIFTY on 36.8%;
  - COPPER on 0%.

**E4** (`data/e4/dev_report.txt`, commit 471442c)
- This is the fallback rule, since there is no point-in-time shares-outstanding data.
- Institutional buy events reliably underperform, in every holding period tested: 5, 20 and 60 sessions.
- Block deals alone (n = 97) have a positive mean, but the CI is wide and the result is secondary only.

## What this rules out, and what it does not

- **Ruled out** for this project, on DEV with these pre-registered rules:
  - index-inclusion drift (long);
  - our filtered 12-1 momentum;
  - the 3-speed futures trend at ₹20L;
  - following bulk/block institutional buyers.
- **Not tested (no data or out of scope):**
  - shorting index removals via stock futures;
  - E4's primary rule with point-in-time shares outstanding.
- Each of these would be a new hypothesis that needs its own pre-registration, not a rescue of the failed one.
- **Benchmarks stay bars, not answers.**
  - The passive momentum index beat E2's rule. That makes the rule worthless, not the index a recommendation.
  - Future work should look for edges a passive index cannot provide.

## Next decision (the user's)

No hypothesis from this plan proceeds to OOS or paper trading, and the paper PCS bot is unchanged.
