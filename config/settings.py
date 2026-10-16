import csv
import os
from datetime import date

from pydantic import Field, SecretStr
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

    # Risk-based sizing (replaces ALLOCATION_PCT_PER_TRADE, which sized off notional width
    # and let a 0.25 allocation at the ₹200k ceiling take 7 lots = ~23% of capital at risk).
    # Max loss of a spread is (width - credit) x lot x lots; lots are chosen so that it stays
    # <= RISK_PER_TRADE_PCT x equity, and total open max loss <= MAX_PORTFOLIO_RISK_PCT x equity.
    # Paper default is 3%, not the 2% target: at ₹200k, 2% = ₹4,000 < one 100-wide lot
    # (~₹5.2k max loss), so the bot would never trade. Set 0.02 once equity >= ~₹275k
    # (the ramp stages in the runbook). See sizing.py.
    RISK_PER_TRADE_PCT: float = Field(default=0.03, gt=0.0, le=0.10)
    MAX_PORTFOLIO_RISK_PCT: float = Field(default=0.08, gt=0.0, le=0.30)

    # Capital ceiling (₹). Paper budget and live margin clamp — sizing must never exceed this.
    MAX_CAPITAL: float = Field(default=200000.0, gt=0.0)
    PAPER_CAPITAL: float = Field(default=200000.0, gt=0.0)

    # Exit slippage buffer (percentage above ask / below bid for marketable-limit orders)
    EXIT_SLIPPAGE_BUFFER_PCT: float = Field(default=0.02, ge=0.0, le=0.10)

    # --- Exit rules (PROF-006 / PROF-007 / PROF-017) ---
    # Take profit when cost_to_close <= TP_RESIDUAL_CREDIT_FRACTION * initial_credit
    TP_RESIDUAL_CREDIT_FRACTION: float = Field(default=0.25, ge=0.0, le=1.0)
    # Stop loss when cost_to_close >= SL_CREDIT_MULTIPLE * initial_credit
    SL_CREDIT_MULTIPLE: float = Field(default=2.0, ge=1.0)
    # When True, stop out the moment spot touches the short strike (today's hardcoded
    # behaviour). A touch fires roughly 2x as often as the strike is actually breached
    # at expiry, so this is a prime suspect for the negative expectancy — parameterized
    # here so it can finally be swept. Default True preserves current behaviour.
    STOP_ON_STRIKE_TOUCH: bool = True
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
    # 30, not 50: at 50 the gate cut 62% of entries whose per-trade expectancy was
    # statistically indistinguishable from the ones it kept (bootstrap 95% CI on the
    # difference straddled zero), so it was shedding return without improving quality.
    # 30 keeps a tail-guard against genuinely dead vol; MIN_CREDIT_WIDTH_RATIO does the
    # real premium filtering on credit actually received at fill time.
    IVR_MIN_PERCENTILE: float = Field(default=30.0, ge=0.0, le=100.0)

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
    DATABASE_URL: str  # required: no default, so a missing .env fails loudly instead of using a guessable password

    # Redis
    REDIS_URL: str = "redis://host.docker.internal:6379/0"
    REDIS_PASSWORD: SecretStr | None = None  # .env only, hex; never put it in REDIS_URL (compose/deploy.ps1 override that)

    # Trading mode
    PAPER_TRADE: bool = True
    MOCK_MARKET: bool = False

    # Heartbeat
    HEARTBEAT_URL: str | None = None


settings = Settings()

# Underlying `name` as it appears in the Upstox instruments master, per traded symbol.
# This is a naming convention, not a market parameter — unlike lot size it does not
# drift when NSE revises contract specs.
MASTER_UNDERLYING_NAME = {"Nifty 50": "NIFTY"}

INSTRUMENT_MASTER_PATH = "data/nse_fo_instruments.csv"


def lot_size_from_master(symbol: str, csv_path: str = INSTRUMENT_MASTER_PATH) -> int | None:
    """Read the current F&O lot size for `symbol` from the Upstox instruments master.

    Returns None when the master is absent or has no option rows for the symbol.
    Callers must treat None as a hard abort: a hardcoded fallback is what let the
    lot size sit at 25 while NSE had moved it to 65 (see PROF-022).
    """
    underlying = MASTER_UNDERLYING_NAME.get(symbol)
    if not underlying or not os.path.exists(csv_path):
        return None

    sizes: set[int] = set()
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get("name") or "").strip().upper() != underlying:
                    continue
                if (row.get("instrument_type") or "").strip().upper() != "OPTIDX":
                    continue
                try:
                    sizes.add(int(row["lot_size"]))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return None

    if not sizes:
        return None
    # ponytail: during a contract-spec transition the master briefly carries both the
    # old and new size across expiries. Take the max — oversizing margin is a rejected
    # order, undersizing is an invalid quantity that trades wrong. Switch to
    # per-expiry lookup if multi-expiry support ever lands.
    return max(sizes)

# Backward-compatible module-level exports
CONNECTION_TIMEOUT = settings.CONNECTION_TIMEOUT
READ_TIMEOUT = settings.READ_TIMEOUT
WEBHOOK_URL = settings.WEBHOOK_URL
VIX_MAX_THRESHOLD = settings.VIX_MAX_THRESHOLD
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
STOP_ON_STRIKE_TOUCH = settings.STOP_ON_STRIKE_TOUCH

_redis_client = None


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        pw = settings.REDIS_PASSWORD.get_secret_value() if settings.REDIS_PASSWORD else None
        # username "default": two-arg AUTH also succeeds before the server sets requirepass, so it can be staged first
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True,
                                       **({"username": "default", "password": pw} if pw else {}))
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


# --- Trading friction (NSE index options, Upstox flat-fee schedule) ---
# One credit spread round trip = 4 orders: buy hedge + sell short (entry),
# buy-to-close short + sell-to-close hedge (exit).
# Sources (verified 2026-10-16):
#   STT: Finance Act 2023 (0.05% -> 0.0625% from 2023-04-01), Finance (No.2) Act 2024
#     (0.0625% -> 0.1% from 2024-10-01), Finance Act 2026, assent 2026-03-30
#     (option sale 0.1% -> 0.15%, exercise 0.125% -> 0.15%, from 2026-04-01):
#     NSE circular FATAX73524, https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf
#   NSE options txn charge: 0.053% -> 0.05% (2023-04-01) -> 0.0495% (2024-04-01) ->
#     0.03503% (2024-10-01); NSE circulars via Zerodha bulletins (zerodha.com/marketintel/bulletin/
#     347967, 373933, 391488).
#   Stamp 0.003% buy side, SEBI Rs10/crore, IPFT Rs0.50/lakh premium (NSE), GST 18% on
#     brokerage+txn+SEBI, brokerage flat Rs20/order: https://upstox.com/brokerage-charges/
# Pre-2023 txn/STT history is from the same sources but only matters for 2019-2022 backtests.
BROKERAGE_PER_ORDER = 20.0       # flat per order, NOT per lot
ORDERS_PER_ROUND_TRIP = 4
STAMP_BUY_PCT = 0.00003
SEBI_PCT = 0.000001
IPFT_PCT = 0.000005
GST_PCT = 0.18                   # on brokerage + transaction charges + SEBI fee

# (effective_from, rate) ascending; the last entry with effective_from <= date applies.
_STT_SELL_SCHEDULE = [
    (date(2000, 1, 1), 0.0005), (date(2023, 4, 1), 0.000625),
    (date(2024, 10, 1), 0.001), (date(2026, 4, 1), 0.0015),
]
_STT_EXERCISE_SCHEDULE = [(date(2000, 1, 1), 0.00125), (date(2026, 4, 1), 0.0015)]
_TXN_SCHEDULE = [
    (date(2000, 1, 1), 0.00053), (date(2023, 4, 1), 0.0005),
    (date(2024, 4, 1), 0.000495), (date(2024, 10, 1), 0.0003503),
]


def _rate(schedule, on: date | None) -> float:
    """Rate in force on `on`; None means today (live / paper)."""
    on = on or date.today()
    return [r for d, r in schedule if d <= on][-1]


def stt_sell_rate(on: date | None = None) -> float:
    return _rate(_STT_SELL_SCHEDULE, on)


def exercise_stt(intrinsic_value: float, on: date | None = None) -> float:
    """STT paid by the BUYER of an option that expires ITM (cash-settled), on intrinsic value.
    A spread's long put pays this when Nifty settles below its strike."""
    return _rate(_STT_EXERCISE_SCHEDULE, on) * abs(intrinsic_value)


def round_trip_fees(
    credit: float,
    cost_to_close: float,
    lot_size: int,
    num_lots: int,
    on: date | None = None,
    legs: tuple[float, float, float, float] | None = None,
) -> float:
    """Total rupee cost of one spread round trip: brokerage + STT + txn + stamp + SEBI + IPFT + GST.

    `on` is the trade date (selects the STT / txn regime; default today). `legs` =
    (short_entry, long_entry, short_exit, long_exit) per-share premiums gives exact
    per-leg bases: STT on both sells (short at entry, long at exit), stamp on both buys,
    txn/SEBI/IPFT on all four. Without `legs`, bases are approximated from the net
    credit / cost_to_close, which UNDERSTATES statutory charges (~38%).

    Excludes bid-ask slippage (modelled separately as a points haircut) and exercise STT
    (see exercise_stt; only when the long put expires ITM).
    """
    brokerage = BROKERAGE_PER_ORDER * ORDERS_PER_ROUND_TRIP
    qty = abs(lot_size) * abs(num_lots)
    if legs is not None:
        se, le, sx, lx = (abs(x) for x in legs)
        sell_prem, buy_prem = (se + lx) * qty, (le + sx) * qty
    else:
        net_in, net_out = abs(credit) * qty, abs(cost_to_close) * qty
        # ponytail: net-spread approximation (legacy callers); pass `legs` for exact bases
        sell_prem, buy_prem = net_in + net_out, net_out
    turnover = sell_prem + buy_prem
    stt = stt_sell_rate(on) * sell_prem
    txn_charges = _rate(_TXN_SCHEDULE, on) * turnover
    sebi = SEBI_PCT * turnover
    gst = GST_PCT * (brokerage + txn_charges + sebi)
    return brokerage + stt + txn_charges + STAMP_BUY_PCT * buy_prem + sebi + IPFT_PCT * turnover + gst
