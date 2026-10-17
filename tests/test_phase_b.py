from datetime import date

import numpy as np
import pytest

from research.phase_b import cluster_ci, fee_pts


def test_cluster_ci_resamples_whole_clusters():
    # two clusters with means 0 and 10: every resample mean is 0, 5 or 10, never anything in between
    x, g = np.array([0.0, 0.0, 10.0, 10.0]), np.array([1, 1, 2, 2])
    m, lo, hi = cluster_ci(x, g, alpha=0.2, n=2000)
    assert m == 5.0 and lo == 0.0 and hi == 10.0
    assert cluster_ci(np.full(6, 3.0), np.arange(6)) == pytest.approx((3.0, 3.0, 3.0))


def test_fee_pts_held_to_expiry():
    d, ex = date(2019, 6, 3), date(2019, 6, 13)
    short = fee_pts(d, ex, 200.0, None, True)
    assert 0 < short < 1  # 2 orders + STT on the sale, per unit
    # pre-2019-09: the buyer's exercise STT is on the whole settlement value (0.125% of ~11900)
    long_itm = fee_pts(d, ex, 200.0, None, False, s_t=11900.0, k=11800.0)
    assert long_itm == pytest.approx(fee_pts(d, ex, 200.0, None, False, s_t=11800.0, k=11800.0) + 0.00125 * 11900)
