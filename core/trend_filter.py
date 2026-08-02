"""Spot trend filter using SMA (PROF-018). File-cached yfinance Nifty closes."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("data/nifty_spot_history.json")
_CACHE_TTL_SEC = 6 * 3600


def _load_cache() -> list[float] | None:
    try:
        if not _CACHE_PATH.exists():
            return None
        payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("fetched_at", 0)) > _CACHE_TTL_SEC:
            return None
        return [float(x) for x in (payload.get("closes") or [])]
    except Exception:
        return None


def _save_cache(closes: list[float]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(
        json.dumps({"fetched_at": time.time(), "closes": closes}),
        encoding="utf-8",
    )


def fetch_nifty_closes(lookback: int = 120) -> list[float]:
    cached = _load_cache()
    if cached is not None and len(cached) >= min(lookback, 40):
        return cached[-lookback:]
    try:
        import yfinance as yf
        from datetime import datetime, timedelta

        end = datetime.utcnow().date() + timedelta(days=1)
        start = end - timedelta(days=int(lookback * 1.8) + 20)
        df = yf.download("^NSEI", start=start.isoformat(), end=end.isoformat(), progress=False)
        if df is None or df.empty:
            return cached[-lookback:] if cached else []
        close = df["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        closes = [float(x) for x in close.dropna().tolist()]
        if closes:
            _save_cache(closes)
        return closes[-lookback:]
    except Exception as e:
        logger.warning(f"Failed to fetch Nifty history: {e}")
        return cached[-lookback:] if cached else []


def sma(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    chunk = values[-window:]
    return sum(chunk) / len(chunk)


def trend_allows_entry(
    spot: float | None,
    *,
    sma_days: int = 50,
    enabled: bool = True,
    closes: list[float] | None = None,
) -> tuple[bool, float | None, str]:
    """Skip new short puts when spot < SMA(sma_days)."""
    if not enabled:
        return True, None, "Trend filter disabled"
    if spot is None:
        return True, None, "Spot unavailable — trend filter bypassed"
    series = closes if closes is not None else fetch_nifty_closes(max(sma_days + 10, 60))
    ma = sma(series, sma_days)
    if ma is None:
        return True, None, "Insufficient spot history — trend filter bypassed"
    if float(spot) < ma:
        return False, ma, f"Spot {spot:.1f} < SMA{sma_days} {ma:.1f}"
    return True, ma, f"Spot {spot:.1f} >= SMA{sma_days} {ma:.1f}"
