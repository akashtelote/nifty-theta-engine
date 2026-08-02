"""Optional historical option-chain loader (PROF-015).

Place daily chain snapshots under ``data/option_chains/`` as parquet or CSV with columns:
  date, expiry, type, strike, bid, ask, mid (optional), spot (optional), vix (optional)

When files are present, backtests may use mid marks instead of BS. Schema only —
no vendor download is performed here.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

CHAIN_DIR = Path("data/option_chains")
REQUIRED_COLS = {"date", "expiry", "type", "strike", "bid", "ask"}


def chain_files_available(directory: Path = CHAIN_DIR) -> bool:
    if not directory.exists():
        return False
    return any(directory.glob("*.parquet")) or any(directory.glob("*.csv"))


def load_option_chains(directory: Path = CHAIN_DIR) -> pl.DataFrame | None:
    """Load and concat all chain files; return None if none / invalid."""
    if not directory.exists():
        return None
    frames: list[pl.DataFrame] = []
    for path in sorted(directory.glob("*.parquet")):
        frames.append(pl.read_parquet(path))
    for path in sorted(directory.glob("*.csv")):
        frames.append(pl.read_csv(path))
    if not frames:
        return None
    df = pl.concat(frames, how="diagonal_relaxed")
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"option chain files missing columns: {sorted(missing)}")
    if "mid" not in df.columns:
        df = df.with_columns(((pl.col("bid") + pl.col("ask")) / 2.0).alias("mid"))
    return df
