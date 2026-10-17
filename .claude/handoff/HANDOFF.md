# HANDOFF — E1–E4 equity/futures research plan (docs/plans/20261017-equity-futures-hypotheses-plan.md)
_Updated: 2026-10-17 · context ~66%_

## Goal
After Phase B came back all-FAIL, the user asked to proceed with:
- E1: index-inclusion drift;
- E2: momentum;
- also to consider E3 (trend-following on futures at ₹20L) and E4 (the whale score).

Deliverable now: a pre-registered plan, reviewed, committed and pushed. Then report to the user and ask before Phase A (the downloads).

## Status
- Phase B is committed and pushed (19d5216). The options-premium branch is stopped.
- The plan doc is written (`git add -N` done). Evaluator round 1 returned 10 findings, all fixed:
  - E4 now tests the bot's actual rule: net institutional qty > 0.5% of shares outstanding. Shares come from a point-in-time source; the fallback is the bulk-deal threshold.
  - E3 runs its feasibility check on current specs too.
  - FX is out of the E3 primary: retail has been barred since 2024-05 under RBI rules.
  - E1/E4 have per-event gates only.
  - New rules for delisting and trade-to-trade (BE) moves.
  - E2 buffer, timing and regime-index are now specified.
  - Tax: the LTCG history and cess are corrected.
  - E4 bootstrap blocks lengthened.
  - E1 files additions by order of passive money tracking each index.
  - The A2 tolerance is set.
- Round 2: 6 more fixes (A2 gate on corporate-action days, ISIN keying, E3 smallest-contract rule, E4 fallback + share-basis scaling, 8-week blocks).
- Round 3 returned 4 more findings (ISIN chaining across splits, E4 scaling from quarter-end, A2 gate uses the yfinance `splits` series with ≥ 20 days, E3 liquidity floor checked at rolls only). All are fixed in the working tree, **NOT committed**: the 3-round review cap was hit.
- The user approved a 4th review. It found 2 issues, now fixed: A2's fallback is confirmed against NSE/BSE, never Yahoo; the E3 turnover floor is measured per product.
- The gate review found 5 more, all fixed:
  - cess was 2% up to FY06-07;
  - the E1/E4 benchmark leg is now the Nifty 500 price index from open to close;
  - E2's regime filter is checked at month-end only;
  - the A2 sample is fixed with seed 20261017;
  - E3 back-adjustment is additive, and a product listed fewer than 60 sessions is skipped.
- Next gate review found 2 more, both fixed:
  - §0.5 benchmark now matches E1 (price index, open to close);
  - E3 signal is sign(price difference) on the additive series, and vol uses returns of the held contract.
- Then 1 more fix: the E3 signal now uses one fixed reference product per underlying (gold products quote in different units).
- Also fixed: E3 tie rule (sign(0)=0) and E3 fills at the next session's open (no same-bar fill).
- Next: a gate review, then commit plan + handoff, push, and start Phase A (A1 first).

## Decisions
- One frozen rule per hypothesis. α = 0.05/4.
- Windows: DEV 2010-18, OOS 2019 → 2026-09. E3 uses DEV 2005-15, OOS 2016 → 2026-09.
- Benchmarks are only bars to beat: Nifty 500 TRI, Nifty200 Momentum 30 TRI (E2), T-bill (E3).

## A0 probe facts
- Data available: equity bhavcopy (legacy format, 2010) and UDiFF; F&O from 2005; CDS from 2012.
- PREVCLOSE is not adjusted for corporate actions, so a separate adjustment step is needed (A2).
- Blockers: the NSE bulk-deal API returns 503; MCX data sits behind a form; jugaad_data is not installed.

## Gotchas
- The commit hook needs an evaluator PASS. Run one `git diff HEAD -- <file>` per file, because combined output gets truncated.
