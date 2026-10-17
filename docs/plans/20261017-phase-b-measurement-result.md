# Phase B measurement result — DEV 2019–2023 — all three hypotheses FAIL

_Run 2026-10-17 with `uv run python -m research.phase_b` (commit with this doc). Plan:
`20261017-next-hypotheses-plan.md` §Phase B. Only DEV option data was used. OOS-A (2011–18 options) and OOS-B
were not touched._

## Verdict

| Hypothesis | Gate (from the plan, written before the run) | Result |
|---|---|---|
| H1 vol-timed short premium | top quintile short-straddle proxy 98.3% CI lower > 0 **and** Spearman > 0.7 | **FAIL**: no signal or tenor has a top-quintile CI above 0 |
| H2 event structures | pooled n ≥ 40 events, 1-day proxy CI excludes 0 | **FAIL**: n = 74, short proxy +5.7 pts, CI [−9.7, +21.8] |
| H3 buy volatility | bottom quintile or event bucket short proxy CI upper < 0 | **FAIL**: no bucket is reliably cheap |

Per the plan, nothing passes, so this is the **stop** branch. Selling or buying Nifty options on these ideas is
shelved for this project. A6 (N-leg engine) is not built. Phase C does not start.

## How it was measured

The implementation choices were fixed in the `research/phase_b.py` docstring before the run. In short:
- **Rows:** one row per (day, expiry), from the EOD IV surface on `close`.
  - Weekly bucket: 3–10 DTE. Monthly bucket: 20–35 DTE.
  - Expiries settling after 2023-12-31 are dropped.
- **P&L proxy:** the short straddle held to expiry, in index points per unit.
  - Formula: proxy = straddle − 2×0.5 slip − |S_T − K| − fees.
  - S_T is the index close on the expiry session. It matches the bhavcopy index settle on all 204 expiries where
    NSE publishes one, with a maximum difference of 0.00 points.
  - Fees are for 1 lot under that date's STT and transaction-charge regime.
- **Long side:** the long mirror pays its own costs (stamp duty, plus exercise STT on the leg that finishes in the
  money), so it is not just the negative of the short proxy.
- **CIs:** 98.3% (α = 0.05/3). The bootstrap resamples whole expiries, because rows of the same expiry overlap.
- **Events:** only events known at entry are used (scheduled, with `announced` blank or ≤ the entry day).
  The four `held=False` meetings of 2020 are counted as events up to the day they were called off or brought
  forward (FOMC 18 Mar → 15 Mar; RBI 3 Apr → 27 Mar; RBI 5 Jun → 22 May; RBI 1 Oct → 28 Sep). After that day
  they no longer count, because an ex-ante calendar would show them only before then.

## B1 — unconditional variance risk premium

| bucket | n rows | n expiries | implied − realised, % of F: mean [98.3% CI] | median [98.3% CI] | short proxy pts [98.3% CI] | long proxy pts [98.3% CI] |
|---|---|---|---|---|---|---|
| weekly | 1438 | 256 | 0.064 [−0.178, 0.284] | 0.300 [0.147, 0.458] | 5.7 [−25.2, 33.8] | −11.7 [−39.8, 19.2] |
| monthly | 1175 | 169 | −0.185 [−0.834, 0.330] | 0.107 [−0.251, 0.481] | −29.8 [−112.1, 41.2] | 23.5 [−47.2, 105.9] |

In the weekly bucket the median straddle overstates the move: the median gap is +0.30% of F, and its CI excludes
0. That is the usual premium. The monthly median gap's CI includes 0. In both buckets the mean gap's CI includes 0,
because the tail eats it (Feb–Mar 2020 and other gap moves). After costs, the short side earns nothing distinguishable
from zero on either tenor.

## B2 — conditional on signals known at entry (short proxy, pts, mean [98.3% CI])

| bucket | signal | n | Q1 (low) | Q2 | Q3 | Q4 | Q5 (high) | Spearman | Q1 long proxy |
|---|---|---|---|---|---|---|---|---|---|
| weekly | iv30 − HAR | 1429 | −28.7 [−81.7, 19.8] | −8.6 [−51.3, 29.0] | 34.5 [−15.7, 76.2] | 12.2 [−56.8, 74.1] | 17.4 [−57.0, 85.2] | 0.70 | 23.4 [−24.8, 76.3] |
| weekly | iv30 / RV21 | 1429 | −2.5 [−67.5, 58.6] | 22.2 [−23.3, 63.3] | −5.8 [−91.9, 62.6] | 6.4 [−38.6, 48.4] | 6.5 [−50.4, 57.3] | 0.20 | −3.5 [−64.2, 61.7] |
| weekly | VIX 1y pct | 1429 | −7.8 [−56.8, 36.3] | 6.6 [−35.6, 46.0] | −5.4 [−56.2, 40.0] | 20.4 [−33.7, 70.0] | 12.9 [−98.4, 106.1] | 0.80 | 3.0 [−41.0, 52.0] |
| weekly | put skew | 1437 | −3.4 [−36.4, 27.2] | −14.2 [−56.4, 24.1] | 12.1 [−31.2, 52.0] | 28.5 [−15.8, 69.2] | 11.8 [−86.1, 93.6] | 0.60 | −2.7 [−33.4, 30.6] |
| monthly | iv30 − HAR | 1166 | −116.4 [−249.5, 7.2] | −67.5 [−163.9, 14.0] | 48.8 [−117.0, 165.9] | −30.3 [−156.7, 73.4] | 13.5 [−127.4, 155.9] | 0.70 | 111.2 [−12.3, 244.1] |
| monthly | iv30 / RV21 | 1166 | −50.1 [−249.3, 102.0] | −45.1 [−152.1, 50.0] | −70.6 [−197.8, 20.9] | −13.5 [−111.0, 73.6] | 27.0 [−104.8, 135.8] | 0.70 | 43.9 [−108.1, 243.5] |
| monthly | VIX 1y pct | 1166 | −12.3 [−94.4, 73.2] | −1.4 [−100.9, 82.0] | −7.0 [−127.6, 102.3] | −93.7 [−225.1, 26.5] | −38.1 [−331.9, 170.5] | −0.60 | 7.1 [−78.2, 89.1] |
| monthly | put skew | 1170 | −70.5 [−187.7, 36.7] | −69.3 [−144.2, 5.0] | −45.1 [−178.0, 58.6] | −4.7 [−125.8, 96.7] | 33.8 [−159.5, 183.5] | 1.00 | 65.2 [−42.1, 182.2] |

Some signals sort in the expected direction:
- monthly put skew: Spearman 1.0;
- weekly VIX percentile: 0.8;
- iv30 − HAR (both tenors) and monthly iv30 / RV21: 0.7, which does not clear the > 0.7 bar.

But no top quintile has a CI above zero. Even the best buckets have CIs about ±70–150 points wide, so the effect
is either absent or too small to separate from noise with five years of data. Eight signal/tenor combinations were
looked at, so a single near-miss would not count even if one existed. None does.

## B3 — events

**B3a. Expiries with a known event in their life vs without:**

| bucket | event in life | n rows | short proxy pts [98.3% CI] | long proxy pts [98.3% CI] |
|---|---|---|---|---|
| weekly | yes | 480 | −13.6 [−69.8, 36.1] | 7.1 [−42.0, 63.4] |
| weekly | no | 958 | 15.4 [−20.6, 48.4] | −21.1 [−53.8, 14.8] |
| monthly | yes | 964 | −34.9 [−136.4, 46.4] | 28.4 [−52.9, 130.0] |
| monthly | no | 211 | −6.5 [−129.0, 96.4] | 0.8 [−102.4, 123.2] |

Expiries with an event in their life look worse for the seller than expiries without one (weekly −13.6 vs +15.4;
monthly −34.9 vs −6.5). But every CI here straddles 0, so the sign of that difference is not established. Almost
every monthly expiry spans an RBI or FOMC date, so the monthly "no" bucket is small (211 rows).

**B3b. 1-day straddle, close before the event session to close of the event session:**

A pair is dropped if there was no straddle at entry or an ATM leg did not trade at exit. That is a small
exit-day selection, and it removed 0 event pairs and 1 non-event pair. The voided 2020 meetings don't add
pairs, because each was already known to be off by the close before its session.

| set | n | short proxy pts [98.3% CI] | long proxy pts [98.3% CI] |
|---|---|---|---|
| event sessions, pooled | 74 | 5.7 [−9.7, 21.8] | −13.8 [−30.0, 1.6] |
| contains RBI | 28 | 7.7 [−6.8, 20.7] | −15.7 [−28.8, −1.3] |
| contains FOMC | 39 | −1.0 [−17.9, 16.1] | −7.2 [−24.4, 9.6] |
| contains budget | 6 | −3.1 [−114.6, 96.4] | −5.1 [−105.0, 106.7] |
| pooled ex-FOMC-only | 35 | 13.1 [−13.7, 42.8] | −21.2 [−50.9, 5.7] |
| non-event sessions | 1161 | −0.9 [−5.4, 3.1] | −7.0 [−11.0, −2.6] |

The pooled event crush is positive for the seller (+5.7 points), but its CI includes zero. The RBI-only long CI is
below zero, meaning buying straddles into RBI loses. But n = 28 is below the plan's n ≥ 40, and the short side
over the same sessions is not significant either. The plan says a single event type can't carry H2, and this
doesn't. On ordinary days a 1-day long straddle reliably loses about 7 points after costs: that is plain theta
plus costs, not an edge for the seller (the short side is −0.9).

## What this means

- **H1:** the textbook variance risk premium exists in the median, but on Nifty 2019–2023, after realistic costs
  and the 2020 tail, a short straddle doesn't earn it reliably. Timing it with IV vs HAR, IV/RV, the VIX
  percentile or skew doesn't isolate a bucket that does. This matches the PCS v2 FAIL from a different angle.
- **H3:** options were not reliably too cheap anywhere either, as the plan's prior expected.
- **H2:** the event crush is small and not significant at n = 74.

**Not done, deliberately:**
- no new signals;
- no other tenors or bucket edges;
- no relaxed gates.

All of those would be fitting after looking at the results (plan §0.1 and §B2). A different idea needs a new plan
that is written before any data is examined. Reusing these DEV numbers for it would not be clean.

## Caveats

- **The HAR model is in-sample.** It is fitted on the same 2019–2023 DEV window, as the plan specified. That
  flatters signal (i) if anything, and signal (i) still fails.
- **The proxy is an approximation.** It uses EOD `close` with a flat 0.5-point slip per leg. Real ATM fills
  around events may be worse, which would only strengthen the FAIL for the short side.
- **One day is missing.** 2021-03-30 has no bhavcopy (an archive gap), so rows and 1-day pairs touching it are
  absent.
- **The VIX percentile window starts in 2018.** It uses 2018 index and VIX history, but no 2018 option data.
