import math
from datetime import date

import polars as pl
import pytest

from research import iv


@pytest.mark.parametrize("typ", ["CE", "PE"])
@pytest.mark.parametrize("k", [20000.0, 22000.0, 24000.0])
def test_implied_vol_round_trip(typ, k):
    f, t, v = 22000.0, 7 / 365, 0.18
    assert iv.implied_vol(iv.black76(f, k, t, v, typ), f, k, t, typ) == pytest.approx(v, abs=1e-6)


def test_put_call_parity():
    f, k, t, v = 22000.0, 21800.0, 20 / 365, 0.15
    assert iv.black76(f, k, t, v, "CE") - iv.black76(f, k, t, v, "PE") == pytest.approx(f - k, abs=1e-6)


def test_implied_vol_rejects_below_intrinsic_and_expired():
    assert iv.implied_vol(100.0, 22000.0, 21800.0, 7 / 365, "CE") is None  # intrinsic is 200
    assert iv.implied_vol(50.0, 22000.0, 22000.0, 0.0, "PE") is None


def _chain(d: date, ex: date, f: float, v: float) -> pl.DataFrame:
    t = (ex - d).days / 365
    rows = [{"date": d, "expiry": ex, "strike": k, "opt_type": typ, "close": iv.black76(f, k, t, v, typ),
             "settle": iv.black76(f, k, t, v, typ), "contracts": 1000}
            for k in [f + 100.0 * i for i in range(-15, 16)] for typ in ("CE", "PE")]
    return pl.DataFrame(rows)


def test_expiry_row_recovers_flat_vol_and_straddle():
    d, ex = date(2023, 3, 1), date(2023, 3, 9)
    r = iv.expiry_row(_chain(d, ex, 17500.0, 0.14), d, ex)
    assert r["fwd"] == pytest.approx(17500.0, abs=1e-6)
    assert r["atm_iv"] == pytest.approx(0.14, abs=1e-6)
    assert r["put25_iv"] == pytest.approx(0.14, abs=1e-6) and r["call25_iv"] == pytest.approx(0.14, abs=1e-6)
    assert r["straddle"] == pytest.approx(2 * iv.black76(17500.0, 17500.0, 8 / 365, 0.14, "CE"))


def test_constant_maturity_interpolates_total_variance():
    d = date(2023, 3, 1)
    surf = pl.DataFrame({"date": [d, d], "dte": [10, 40], "atm_iv": [0.10, 0.20]})
    (v,) = iv.constant_maturity(surf, 30)["iv30"].to_list()
    assert v == pytest.approx(math.sqrt((1 / 3 * 0.01 * 10 + 2 / 3 * 0.04 * 40) / 30))
    assert iv.constant_maturity(surf, 50).is_empty()  # no extrapolation
