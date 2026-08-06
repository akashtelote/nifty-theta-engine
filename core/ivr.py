"""India VIX percentile (IVR) helper with short-TTL file cache.

Used by entry gates (PROF-016) and backtests. Network fetch is optional;
callers may pass an explicit VIX history series for offline tests.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("data/india_vix_history.json")
_CACHE_TTL_SEC = 6 * 3600  # 6 hours


def _ensure_data_dir() -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)


def vix_percentile(current_vix: float, history: list[float]) -> float | None:
    """Return percentile of current_vix within history (0–100). None if insufficient data."""
    if not history or current_vix is None:
        return None
    cleaned = [float(x) for x in history if x is not None]
    if len(cleaned) < 20:
        return None
    below = sum(1 for x in cleaned if x <= current_vix)
    return 100.0 * below / len(cleaned)


def load_cached_vix_closes() -> list[float] | None:
    """Load cached VIX closes if fresh."""
    try:
        if not _CACHE_PATH.exists():
            return None
        payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("fetched_at", 0)) > _CACHE_TTL_SEC:
            return None
        closes = payload.get("closes") or []
        return [float(x) for x in closes]
    except Exception as e:
        logger.debug(f"VIX cache read failed: {e}")
        return None


def save_vix_cache(closes: list[float]) -> None:
    _ensure_data_dir()
    _CACHE_PATH.write_text(
        json.dumps({"fetched_at": time.time(), "closes": closes}),
        encoding="utf-8",
    )


def fetch_india_vix_history(lookback_days: int = 252) -> list[float]:
    """Fetch daily India VIX closes via yfinance; uses file cache when fresh."""
    cached = load_cached_vix_closes()
    if cached is not None and len(cached) >= min(lookback_days, 60):
        return cached[-lookback_days:]

    try:
        import yfinance as yf

        end = datetime.utcnow().date() + timedelta(days=1)
        start = end - timedelta(days=int(lookback_days * 1.6) + 30)
        df = yf.download("^INDIAVIX", start=start.isoformat(), end=end.isoformat(), progress=False)
        if df is None or df.empty:
            logger.warning("India VIX history download returned empty.")
            return cached[-lookback_days:] if cached else []
        close = df["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        closes = [float(x) for x in close.dropna().tolist()]
        if closes:
            save_vix_cache(closes)
        return closes[-lookback_days:]
    except Exception as e:
        logger.warning(f"Failed to fetch India VIX history: {e}")
        return cached[-lookback_days:] if cached else []


def compute_ivr(current_vix: float | None, lookback_days: int = 252) -> float | None:
    """IVR = percentile of current India VIX vs lookback history."""
    if current_vix is None:
        return None
    history = fetch_india_vix_history(lookback_days)
    return vix_percentile(float(current_vix), history)


def ivr_allows_entry(
    current_vix: float | None,
    *,
    lookback_days: int = 252,
    min_percentile: float = 50.0,
    skip_low_ivr: bool = True,
    history: list[float] | None = None,
) -> tuple[bool, float | None, str]:
    """Return (allowed, ivr, reason)."""
    if not skip_low_ivr:
        return True, None, "IVR gate disabled"
    if current_vix is None:
        # Fail-open when VIX unavailable (same spirit as VIX None → enter)
        return True, None, "VIX unavailable — IVR gate bypassed"
    if history is not None:
        ivr = vix_percentile(float(current_vix), history)
    else:
        ivr = compute_ivr(float(current_vix), lookback_days)
    if ivr is None:
        return True, None, "Insufficient VIX history — IVR gate bypassed"
    if ivr < min_percentile:
        return False, ivr, f"IVR {ivr:.1f} < min {min_percentile:.1f}"
    return True, ivr, f"IVR {ivr:.1f} >= min {min_percentile:.1f}"
