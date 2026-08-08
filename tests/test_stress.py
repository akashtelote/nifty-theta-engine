"""Invariants for the adversarial scenario harness (`stress.py`).

Most of these exist because the harness silently lied during development, not
because the failure was hypothetical:

* the warmup traded, bled past the funding cliff before any shock landed, and
  made all ten scenarios return the identical dead-account result;
* `capital_ceiling` was missing, so a ₹200k sweep was clamped to ₹50k and
  reported a ₹50k answer under a ₹200k label;
* scenarios grew long favourable recovery tails and reported a COVID-shaped
  crash as PF 5.18.

A stress harness that quietly measures nothing is worse than no harness, so the
integrity of the fixture is asserted here alongside the strategy's own bounds.
"""

from __future__ import annotations

import math

import pytest

import backtest
import stress
from backtest import PCSParams, round_trip_fees, run_pcs_backtest
from config.settings import ALLOCATION_PCT_PER_TRADE, MAX_CAPITAL

SEEDS = (7, 11, 23, 42, 99, 2024)


def _params(**kw) -> PCSParams:
    return PCSParams(**kw)


# ------------------------------------------------------------ harness integrity


@pytest.mark.parametrize("seed", SEEDS)
def test_warmup_places_no_trades(seed):
    """The warmup exists only to fill the IVR/SMA windows.

    If it trades, every scenario result is warmup noise plus a shock the account
    was too poor to take, and the whole table becomes meaningless.
    """
    res = run_pcs_backtest(stress._frame(stress._warmup(seed=seed)), _params())
    assert res.total_trades == 0, f"warmup traded {res.total_trades}x at seed {seed}"


def test_warmup_ends_above_its_own_sma50():
    """Scenarios assume trading can start once VIX enters the band; that needs
    spot above the SMA50 or the trend gate blocks the scenario too."""
    rows = stress._warmup()
    closes = [r[0] for r in rows]
    assert closes[-1] > sum(closes[-50:]) / 50.0


def test_scenarios_are_distinct():
    """Guards the regression where every scenario returned the same numbers."""
    sigs = {
        sc.name: (
            lambda m: (m["trades"], round(m["total_pnl"], 2), round(m["worst_trade"], 2))
        )(stress.run_scenario(sc, _params()))
        for sc in stress.SCENARIOS
    }
    assert len(set(sigs.values())) >= len(sigs) - 1, f"scenarios collapsed to identical results: {sigs}"


def test_capital_ceiling_actually_resizes():
    """Without patching `backtest.MAX_CAPITAL`, a ₹200k run silently returns a
    ₹50k result — the sweep would 'prove' capital changes nothing."""
    covid = next(s for s in stress.SCENARIOS if s.name == "covid_crash")
    small = stress.run_scenario(covid, _params(initial_capital=50_000.0))
    with stress.capital_ceiling(200_000.0):
        big = stress.run_scenario(covid, _params(initial_capital=200_000.0))
    assert abs(big["worst_trade"]) > abs(small["worst_trade"]) * 2, (
        f"ceiling patch had no effect: {small['worst_trade']} vs {big['worst_trade']}"
    )


def test_capital_ceiling_restores_on_exit():
    original = backtest.MAX_CAPITAL
    with pytest.raises(RuntimeError):
        with stress.capital_ceiling(200_000.0):
            raise RuntimeError("boom")
    assert backtest.MAX_CAPITAL == original


# ------------------------------------------------------------- strategy bounds


@pytest.mark.parametrize("scenario", [s.name for s in stress.SCENARIOS])
def test_loss_never_exceeds_structural_max(scenario):
    """The hedge is the only thing bounding a short put. No trade — in a 6% gap
    clean through the long strike, or a -20% day — may lose more than
    (width - credit) x qty plus the friction paid on top of that floor.
    """
    sc = next(s for s in stress.SCENARIOS if s.name == scenario)
    p = _params()
    res = run_pcs_backtest(sc.build(), p)
    max_lots = math.floor(min(p.initial_capital, MAX_CAPITAL) * p.allocation_pct / (p.hedge_width * p.lot_size))
    assert max_lots >= 1

    for t in res.trades:
        qty = p.lot_size * max_lots
        structural = (p.hedge_width - t.credit) * qty
        friction = p.slippage_points * qty * 2 + round_trip_fees(
            t.credit, p.sl_multiple * t.credit, p.lot_size, max_lots
        )
        floor_pnl = -(structural + friction)
        assert t.pnl >= floor_pnl - 1e-6, (
            f"{scenario}: trade on {t.entry_date} lost {t.pnl:.2f}, "
            f"below the structural floor {floor_pnl:.2f} — the hedge did not cap it"
        )


def test_gap_through_hedge_actually_hurts():
    """Counterpart to the bound above: confirm the scenario is adversarial at
    all. A harness that caps losses because nothing bad happened proves nothing.
    """
    sc = next(s for s in stress.SCENARIOS if s.name == "gap_through_hedge")
    m = stress.run_scenario(sc, _params())
    assert m["trades"] >= 5, "gap scenario stopped re-entering; it measures one gap, not many"
    assert m["pf"] < 1.0
    assert m["worst_trade"] < -2_000


def test_downtrend_blocks_all_entries():
    """The SMA50 trend gate should refuse to sell puts into a sustained bleed."""
    sc = next(s for s in stress.SCENARIOS if s.name == "grind_down")
    assert stress.run_scenario(sc, _params())["trades"] == 0


def test_calm_market_is_profitable():
    """Sanity anchor. If the control loses money the scenarios are not measuring
    tail risk, they are measuring a broken fixture."""
    sc = next(s for s in stress.SCENARIOS if s.name == "calm_bull")
    m = stress.run_scenario(sc, _params())
    assert m["trades"] >= 10 and m["total_pnl"] > 0


# --------------------------------------------------------------- funding cliff


def test_funding_cliff_matches_sizing_rule():
    """Cliff must equal the equity at which floor(budget / width x lot) hits 0."""
    p = _params()
    cliff = stress.funding_cliff(p)
    just_above = math.floor(min(cliff + 50, MAX_CAPITAL) * p.allocation_pct / (p.hedge_width * p.lot_size))
    just_below = math.floor(min(cliff - 50, MAX_CAPITAL) * p.allocation_pct / (p.hedge_width * p.lot_size))
    assert just_above >= 1 and just_below == 0


def test_repeated_shocks_trip_the_cliff():
    """`ruin_proxy` alone cannot see a bricked account: once sizing returns zero
    lots the bot stops trading, drawdown flatlines, and the run reads as safe."""
    sc = next(s for s in stress.SCENARIOS if s.name == "rate_shock_repeat")
    m = stress.run_scenario(sc, _params())
    assert m["bricked_after"] is not None, "30 x -6% gaps should exhaust a ₹50k account"
    assert m["final_equity"] < m["cliff"]


# ------------------------------------------------- the allocation decision itself


def test_allocation_setting_is_live():
    """Regression guard: `.env` shadows `settings.py`, so editing the dataclass
    default alone is a silent no-op. This asserts the value actually in force."""
    assert ALLOCATION_PCT_PER_TRADE == pytest.approx(0.25)


def test_allocation_025_still_buys_exactly_one_lot():
    """The whole basis for the change: more drawdown runway, identical size."""
    p = _params()
    per_lot = p.hedge_width * p.lot_size
    assert math.floor(MAX_CAPITAL * 0.25 / per_lot) == 1
    assert math.floor(MAX_CAPITAL * 0.15 / per_lot) == 1
    # 0.26 is where a second lot appears and per-trade risk doubles.
    assert math.floor(MAX_CAPITAL * 0.26 / per_lot) == 2


def test_allocation_025_does_not_change_risk():
    """At ₹50k the two allocations must produce identical trades, not merely
    similar ones — otherwise the change is not free."""
    covid = next(s for s in stress.SCENARIOS if s.name == "covid_crash")
    a = stress.run_scenario(covid, _params(allocation_pct=0.15))
    b = stress.run_scenario(covid, _params(allocation_pct=0.25))
    assert a["total_pnl"] == pytest.approx(b["total_pnl"])
    assert a["worst_trade"] == pytest.approx(b["worst_trade"])


def test_allocation_025_extends_runway():
    assert stress.funding_cliff(_params(allocation_pct=0.25)) < stress.funding_cliff(
        _params(allocation_pct=0.15)
    )
