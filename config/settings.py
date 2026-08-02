from pydantic import Field
from pydantic_settings import BaseSettings
import redis


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    # API timeouts
    CONNECTION_TIMEOUT: float = 10.0
    READ_TIMEOUT: float = 30.0

    # Webhook
    WEBHOOK_URL: str | None = None

    # VIX circuit breaker (hard skip above this) — Stage 6 tightened to 22
    VIX_MAX_THRESHOLD: float = 22.0

    # Position sizing
    ALLOCATION_PCT_PER_TRADE: float = 0.15

    # Capital ceiling (₹). Paper budget and live margin clamp — sizing must never exceed this.
    MAX_CAPITAL: float = Field(default=50000.0, gt=0.0)
    PAPER_CAPITAL: float = Field(default=50000.0, gt=0.0)

    # Exit slippage buffer (percentage above ask / below bid for marketable-limit orders)
    EXIT_SLIPPAGE_BUFFER_PCT: float = Field(default=0.02, ge=0.0, le=0.10)

    # --- Exit rules (PROF-006 / PROF-007 / PROF-017) ---
    # Take profit when cost_to_close <= TP_RESIDUAL_CREDIT_FRACTION * initial_credit
    TP_RESIDUAL_CREDIT_FRACTION: float = Field(default=0.50, ge=0.0, le=1.0)
    # Stop loss when cost_to_close >= SL_CREDIT_MULTIPLE * initial_credit
    SL_CREDIT_MULTIPLE: float = Field(default=2.0, ge=1.0)
    # Time stop: weekday 0=Mon .. 6=Sun; set < 0 to disable (Stage 6 default)
    TIME_STOP_WEEKDAY: int = Field(default=-1, ge=-1, le=6)
    TIME_STOP_HOUR: int = Field(default=15, ge=0, le=23)
    # Force manage/exit when DTE <= this (< 0 disables)
    DTE_MANAGE_THRESHOLD: int = Field(default=7)
    # Close when abs(short put delta) exceeds this (>= band)
    SHORT_DELTA_MANAGE: float = Field(default=0.30, gt=0.0, lt=1.0)

    # --- Strike selection (PROF-008 / PROF-009 / PROF-018) ---
    SHORT_PUT_TARGET_DELTA: float = Field(default=0.18, gt=0.0, lt=0.5)
    SHORT_PUT_BASE_OTM_PCT: float = Field(default=0.01, ge=0.0, le=0.10)
    HEDGE_WIDTH: float = Field(default=100.0, gt=0.0)
    MIN_CREDIT_WIDTH_RATIO: float = Field(default=0.15, ge=0.0, le=1.0)
    MAX_BID_ASK_SPREAD_PCT: float = Field(default=0.15, ge=0.0, le=1.0)
    ENTRY_MIN_DTE: int = Field(default=10, ge=1)
    ENTRY_MAX_DTE: int = Field(default=42, ge=1)

    # --- Regime-aware OTM (PROF-010) ---
    VIX_LOW_THRESHOLD: float = Field(default=13.0, gt=0.0)
    VIX_ELEVATED_THRESHOLD: float = Field(default=18.0, gt=0.0)
    VIX_LOW_OTM_PCT: float = Field(default=0.012, ge=0.0, le=0.10)
    VIX_NORMAL_OTM_PCT: float = Field(default=0.010, ge=0.0, le=0.10)
    VIX_ELEVATED_OTM_PCT: float = Field(default=0.015, ge=0.0, le=0.10)

    # --- IVR gate (PROF-016) ---
    SKIP_LOW_IVR: bool = True
    IVR_LOOKBACK_DAYS: int = Field(default=252, ge=20)
    IVR_MIN_PERCENTILE: float = Field(default=50.0, ge=0.0, le=100.0)

    # --- Left-tail (PROF-018) ---
    EVENT_BLACKOUT_ENABLED: bool = True
    EVENT_BLACKOUT_DAYS_BEFORE: int = Field(default=1, ge=0)
    EVENT_BLACKOUT_DAYS_AFTER: int = Field(default=1, ge=0)
    TREND_FILTER_ENABLED: bool = True
    TREND_SMA_DAYS: int = Field(default=50, ge=5)

    # --- Mid-week / re-entry (PROF-011 / PROF-019) ---
    ALLOW_MIDWEEK_ENTRY: bool = True
    MIDWEEK_ENTRY_DAYS: str = "tue,wed,thu"
    MIDWEEK_ENTRY_HOUR: int = Field(default=15, ge=0, le=23)
    MIDWEEK_ENTRY_MINUTE: int = Field(default=15, ge=0, le=59)
    MIDWEEK_VIX_MIN: float = Field(default=16.0, gt=0.0)
    MIDWEEK_VIX_MAX: float = Field(default=22.0, gt=0.0)
    ALLOW_SAME_WEEK_REENTRY: bool = True

    # --- Entry fill improvement (PROF-012) ---
    ENTRY_USE_MID_PRICE: bool = True
    ENTRY_REQUOTE_ATTEMPTS: int = Field(default=2, ge=0, le=5)
    ENTRY_REQUOTE_STEP_PCT: float = Field(default=0.25, ge=0.0, le=1.0)

    # Database
    DATABASE_URL: str = "postgresql://wheelbot:securepassword@localhost:5432/wheeldb"

    # Redis
    REDIS_URL: str = "redis://host.docker.internal:6379/0"

    # Trading mode
    PAPER_TRADE: bool = True
    MOCK_MARKET: bool = False

    # Heartbeat
    HEARTBEAT_URL: str | None = None


settings = Settings()

# NSE lot sizes — not an env var, updated manually when NSE changes contract specs
LOT_SIZES = {"Nifty 50": 25}

# Backward-compatible module-level exports
CONNECTION_TIMEOUT = settings.CONNECTION_TIMEOUT
READ_TIMEOUT = settings.READ_TIMEOUT
WEBHOOK_URL = settings.WEBHOOK_URL
VIX_MAX_THRESHOLD = settings.VIX_MAX_THRESHOLD
ALLOCATION_PCT_PER_TRADE = settings.ALLOCATION_PCT_PER_TRADE
MAX_CAPITAL = settings.MAX_CAPITAL
PAPER_CAPITAL = settings.PAPER_CAPITAL
EXIT_SLIPPAGE_BUFFER_PCT = settings.EXIT_SLIPPAGE_BUFFER_PCT
TP_RESIDUAL_CREDIT_FRACTION = settings.TP_RESIDUAL_CREDIT_FRACTION
SL_CREDIT_MULTIPLE = settings.SL_CREDIT_MULTIPLE
TIME_STOP_WEEKDAY = settings.TIME_STOP_WEEKDAY
TIME_STOP_HOUR = settings.TIME_STOP_HOUR
DTE_MANAGE_THRESHOLD = settings.DTE_MANAGE_THRESHOLD
SHORT_PUT_TARGET_DELTA = settings.SHORT_PUT_TARGET_DELTA
SHORT_PUT_BASE_OTM_PCT = settings.SHORT_PUT_BASE_OTM_PCT
HEDGE_WIDTH = settings.HEDGE_WIDTH
MIN_CREDIT_WIDTH_RATIO = settings.MIN_CREDIT_WIDTH_RATIO
MAX_BID_ASK_SPREAD_PCT = settings.MAX_BID_ASK_SPREAD_PCT
ALLOW_MIDWEEK_ENTRY = settings.ALLOW_MIDWEEK_ENTRY

_redis_client = None


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def vix_regime_otm(vix: float | None) -> tuple[str, float]:
    """Map VIX → (action, otm_pct).

    action: 'enter' | 'skip'
    - None VIX → enter at base/normal OTM (fail-open like prior circuit breaker)
    - vix > VIX_MAX_THRESHOLD → skip
    - low / normal / elevated bands scale OTM aggressiveness
    """
    if vix is None:
        return "enter", settings.VIX_NORMAL_OTM_PCT
    if vix > settings.VIX_MAX_THRESHOLD:
        return "skip", settings.VIX_ELEVATED_OTM_PCT
    if vix < settings.VIX_LOW_THRESHOLD:
        return "enter", settings.VIX_LOW_OTM_PCT
    if vix < settings.VIX_ELEVATED_THRESHOLD:
        return "enter", settings.VIX_NORMAL_OTM_PCT
    return "enter", settings.VIX_ELEVATED_OTM_PCT
