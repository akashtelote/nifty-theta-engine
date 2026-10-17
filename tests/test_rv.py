import math
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from research import rv


def _idx(n: int, seed: int = 1) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.01, n)
    d0 = date(2019, 1, 1)
    df = pl.DataFrame({"date": [d0 + timedelta(days=i) for i in range(n)], "close": 10000 * np.exp(np.cumsum(r))})
    return df.with_columns(r=pl.col("close").log().diff()).with_columns(r2=pl.col("r") ** 2)


def test_rv_is_trailing_annualised():
    df = rv.add_rv(_idx(60), windows=(10,))
    r2 = df["r2"].to_list()
    assert df["rv10"][30] == pytest.approx(math.sqrt(sum(r2[21:31]) / 10 * 252))


def test_har_on_constant_variance_forecasts_that_variance():
    df = _idx(2000)
    coef = rv.har_fit(df, 5, df["date"][0], df["date"][-1])
    f = rv.har_forecast(df, coef, 5)["harvol5"].drop_nulls()
    assert f.mean() == pytest.approx(0.01 * math.sqrt(252), rel=0.05)


def test_har_fit_ignores_targets_after_end():
    df = _idx(600)
    end = df["date"][399]
    tampered = df.with_columns(pl.when(pl.col("date") > end).then(pl.col("r2") * 100).otherwise(pl.col("r2")).alias("r2"))
    assert np.allclose(rv.har_fit(df, 5, df["date"][0], end), rv.har_fit(tampered, 5, df["date"][0], end))
