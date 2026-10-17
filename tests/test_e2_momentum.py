from datetime import date

import polars as pl

from research.e2_momentum import CAPITAL, fy_tax, median_padded, months_back, simulate, stationary_ci

D = [date(2015, 3, d) for d in range(2, 21)]


def test_months_back_and_median_padded():
    assert months_back(date(2016, 3, 31), 1) == date(2016, 2, 29)
    assert months_back(date(2010, 1, 15), 13) == date(2008, 12, 15)
    assert median_padded([5.0, None, 3.0], 4) == 1.5  # [0, 0, 3, 5]
    assert median_padded([1.0, 2.0, 3.0], 3) == 2.0


def test_fy_tax_set_off_and_carry_forward():
    cf = [0.0, 0.0]
    assert fy_tax(-50_000.0, 0.0, cf, 2017) == 0.0 and cf == [50_000.0, 0.0]
    # carried ST loss offsets ST gain first, rest stays; 15% * 1.04 from FY2018
    assert abs(fy_tax(30_000.0, 0.0, cf, 2018) - 0.0) < 1e-9 and cf == [20_000.0, 0.0]
    # remaining ST loss offsets LT gain; LT 150k - 20k = 130k, 30k above exemption at 10%
    assert abs(fy_tax(0.0, 150_000.0, cf, 2018) - 30_000 * 0.10 * 1.04) < 1e-6 and cf == [0.0, 0.0]
    cf = [0.0, 0.0]  # same-year ST loss offsets LT gain; LT loss never offsets ST
    assert abs(fy_tax(-10_000.0, 120_000.0, cf, 2019) - 10_000 * 0.10 * 1.04) < 1e-6
    assert abs(fy_tax(10_000.0, -5_000.0, cf, 2019) - 10_000 * 0.15 * 1.04) < 1e-6 and cf == [0.0, 5_000.0]


def test_stationary_ci_deterministic():
    x = [0.01, -0.02, 0.03, 0.0, 0.015, -0.005] * 10
    lo, hi = stationary_ci(x)
    assert (lo, hi) == stationary_ci(x) and lo < sum(x) / len(x) < hi


def _uni(ranks: dict[str, int]) -> pl.DataFrame:
    return pl.DataFrame({"perm_id": list(ranks), "rank12": list(ranks.values()),
                         "liq_rank": [1] * len(ranks), "medval": [1e12] * len(ranks)})


def test_simulate_keep_sell_regime_and_rule7():
    flat = {d: (100.0, 100.0, False, "EQ") for d in D}
    px = {"A": flat, "B": flat, "C": flat,
          "G": {d: (100.0, 100.0, False, "EQ") for d in D[:3]}}  # stops trading after D[2]
    book = {D[0]: (_uni({"A": 1, "G": 2, "B": 3}), True),  # B beyond keep: not bought
            D[3]: (_uni({"A": 1, "C": 2, "B": 3}), True),  # G out: pending sale (no row), no cash yet for C
            D[10]: (_uni({"A": 1, "C": 2}), False)}  # regime off: all cash
    nav, t = simulate(D, book, px, D[0], D[-1], slots=2, keep=2)
    held = dict(zip(nav["date"], nav["held"]))
    assert held[D[0]] == 2 and held[D[3]] == 2 and held[D[10]] == 0
    assert t["forced"] == 1  # G: 5th missing session D[7], sold at last close -30%
    v = dict(zip(nav["date"], nav["nav"]))
    assert v[D[7]] < v[D[6]] - 0.29 * CAPITAL / 2 and nav["cash"][-1] == nav["nav"][-1]
