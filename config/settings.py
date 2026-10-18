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
#   Pre-2019 (for the 2011-18 backtest holdout): option sale STT 0.017% -> 0.05% from 2016-06-01
#     (Finance Act 2016; NSE notice, business-standard.com PTI 2016-05-17). Exercise STT 0.125% was
#     charged on the whole settlement value (settle x qty) until 2019-08-31, on intrinsic value from
#     2019-09-01 (Finance (No.2) Act 2019; zerodha.com/marketintel/bulletin/230019).
#     Pre-2023 txn charge (0.05-0.053%) and pre-2020 state stamp duty are approximated by the
#     earliest rows below; both are < 0.01 pt per leg at Nifty premiums.
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
    (date(2000, 1, 1), 0.00017), (date(2016, 6, 1), 0.0005), (date(2023, 4, 1), 0.000625),
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


STT_EXERCISE_INTRINSIC_FROM = date(2019, 9, 1)


def exercise_stt(intrinsic_value: float, on: date | None = None, settlement_value: float | None = None) -> float:
    """STT paid by the BUYER of an option that expires ITM (cash-settled), on intrinsic value.
    A spread's long put pays this when Nifty settles below its strike. Before 2019-09-01 the base was the
    whole settlement value (index settle x qty), so `settlement_value` is required for those dates."""
    base = intrinsic_value
    if (on or date.today()) < STT_EXERCISE_INTRINSIC_FROM:
        if settlement_value is None:
            raise ValueError("exercise before 2019-09-01 is taxed on settlement value; pass settlement_value")
        base = settlement_value
    return _rate(_STT_EXERCISE_SCHEDULE, on) * abs(base)


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


# --- Equity delivery friction (A7, plan 20261017-equity-futures-hypotheses): NSE cash market, delivery ---
# One round trip = one buy order + one sell order of one scrip. (effective_from, rate), as the schedules above.
# Sources (searched 2026-10-18):
#   STT on delivery, charged on BOTH buy and sell: 0.075% from 2004-10-01 (Finance (No.2) Act 2004 s.98);
#     0.1% from 2005-06-01 (Finance Act 2005; CSE notice); 0.125% from 2006-06-01 (Finance Act 2006);
#     0.1% from 2012-07-01 (Finance Act 2012, Act 23 of 2012, assent 2012-05-28; CSE notice 2012-06-20,
#     https://www.cse-india.com/upload/CSE%20Notices%20&%20Circulars/2012/Notice200612.htm).
#   NSE cash txn charge: 0.00325% from 2023-04-01 (zerodha.com/marketintel/bulletin/347967), 0.00322% from
#     2024-04-01 (bulletin 373933), 0.00297% flat from 2024-10-01 (SEBI true-to-label; bulletin 391488).
#     Before 2023 the 0.00345% row is an approximation (history not verified; < 0.001 pt per side).
#   Stamp duty, buy side: uniform 0.015% from 2020-07-01 (Indian Stamp Act amendment; bulletin 259741).
#     Before that it was state-wise; ~Rs1000/crore (0.01%) on delivery in most states is used (approximation).
#   Indirect tax on brokerage + txn + SEBI + DP: service tax 10.2% (2004-09-10, Finance (No.2) Act 2004: 10% + 2%
#     education cess), 12.24% (2006-04-18, Finance Act 2006), 12.36%
#     (2007-05-11, Finance Act 2007 SHE cess), 10.3% (2009-02-24, notification 8/2009-ST), 12.36% (2012-04-01,
#     Finance Act 2012), 14% (2015-06-01, Finance Act 2015), 14.5% (2015-11-15, Swachh Bharat cess), 15%
#     (2016-06-01, Krishi Kalyan cess); GST 18% from 2017-07-01.
#   SEBI Rs10/crore; brokerage Rs20/order and DP charge Rs20/scrip per sell day: https://upstox.com/brokerage-charges/
# ponytail: today's discount-broker brokerage and DP charge are applied to all dates. They are flat rupees
# (~Rs71 per round trip with GST): ~0.35 pt at Rs20k per position, but several points on Rs2-6k tickets.
_EQ_STT_DELIVERY = [
    (date(2004, 10, 1), 0.00075), (date(2005, 6, 1), 0.001), (date(2006, 6, 1), 0.00125), (date(2012, 7, 1), 0.001),
]
_EQ_TXN = [
    (date(2000, 1, 1), 0.0000345), (date(2023, 4, 1), 0.0000325),
    (date(2024, 4, 1), 0.0000322), (date(2024, 10, 1), 0.0000297),
]
_EQ_STAMP_BUY = [(date(2000, 1, 1), 0.0001), (date(2020, 7, 1), 0.00015)]
_INDIRECT_TAX = [
    (date(2004, 9, 10), 0.102), (date(2006, 4, 18), 0.1224), (date(2007, 5, 11), 0.1236), (date(2009, 2, 24), 0.103), (date(2012, 4, 1), 0.1236),
    (date(2015, 6, 1), 0.14), (date(2015, 11, 15), 0.145), (date(2016, 6, 1), 0.15), (date(2017, 7, 1), 0.18),
]
EQ_DP_PER_SELL = 20.0
EQ_FEES_FROM = date(2004, 10, 1)  # first STT row; A7 covers 2005 on


def equity_delivery_fees(buy_value: float, sell_value: float, buy_on: date, sell_on: date) -> float:
    """Rupee cost of one delivery round trip of one scrip: brokerage, STT (both sides), NSE txn, SEBI, stamp (buy),
    DP charge (sell) and service tax / GST on brokerage + txn + SEBI + DP, each at its leg's dated rate.
    Excludes slippage. A zero-value leg (no shares bought) costs nothing."""
    def leg(value: float, on: date, buy: bool) -> float:
        if value <= 0:
            return 0.0
        if on < EQ_FEES_FROM:
            raise ValueError(f"no equity delivery fee schedule before {EQ_FEES_FROM}: {on}")
        taxable = BROKERAGE_PER_ORDER + (_rate(_EQ_TXN, on) + SEBI_PCT) * value + (0.0 if buy else EQ_DP_PER_SELL)
        stamp = _rate(_EQ_STAMP_BUY, on) * value if buy else 0.0
        return taxable * (1 + _rate(_INDIRECT_TAX, on)) + _rate(_EQ_STT_DELIVERY, on) * value + stamp
    return leg(buy_value, buy_on, True) + leg(sell_value, sell_on, False)


# --- Futures friction (A7 futures part, plan 20261017-equity-futures-hypotheses): NSE index futures, MCX non-agri ---
# One leg = one order. Sources (searched 2026-10-18):
#   NSE futures STT, sell side: 0.01% from 2004-10-01, 0.0133% from 2005-06-01, 0.017% from 2006-06-01
#     (tradingqna.com/t/sebi-and-stt-what-is-the-history-around-stt/185139); 0.01% from 2013-06-01 (Finance Act
#     2013; NSE circular, business-standard.com 2013-05-24); 0.0125% from 2023-04-01 (Finance Act 2023); 0.02%
#     from 2024-10-01 (Finance (No.2) Act 2024; zerodha.com/marketintel/bulletin/391488); 0.05% from 2026-04-01
#     (Budget 2026-27; icicidirect.com ilearn "STT changes in budget 2026").
#   MCX CTT, sell side, non-agri futures: 0.01% from 2013-07-01 (Finance Act 2013; CBDT notification 46/2013);
#     none before.
#   Exchange txn: NSE futures 0.00188% -> 0.00173% and MCX futures 0.0026% -> 0.0021% from 2024-10-01 (bulletin
#     391488; hdfcsec.com "Revised Exchange Transaction Charges w.e.f. 1st October 2024"). Earlier rows are the
#     pre-2024-10 rates applied to all earlier dates (approximation; < 0.002% per side either way).
#   Stamp, buy side: 0.002% from 2020-07-01 (Indian Stamp Act amendment); the same rate is used before (state-wise
#     then; approximation). SEBI Rs10/crore; brokerage Rs20/order; service tax / GST as _INDIRECT_TAX.
_FUT_STT_SELL = {
    "NSE": [(date(2004, 10, 1), 0.0001), (date(2005, 6, 1), 0.000133), (date(2006, 6, 1), 0.00017),
            (date(2013, 6, 1), 0.0001), (date(2023, 4, 1), 0.000125), (date(2024, 10, 1), 0.0002),
            (date(2026, 4, 1), 0.0005)],
    "MCX": [(date(2004, 10, 1), 0.0), (date(2013, 7, 1), 0.0001)],
}
_FUT_TXN = {
    "NSE": [(date(2000, 1, 1), 0.0000188), (date(2024, 10, 1), 0.0000173)],
    "MCX": [(date(2000, 1, 1), 0.000026), (date(2024, 10, 1), 0.000021)],
}
FUT_STAMP_BUY_PCT = 0.00002


def futures_fees(value: float, on: date, buy: bool, exch: str) -> float:
    """Rupee cost of one futures order of notional `value` (price x mult x lots) on `exch` ("NSE" or "MCX"):
    brokerage, STT/CTT (sell), exchange txn, SEBI, stamp (buy), service tax / GST on brokerage + txn + SEBI.
    Excludes slippage. A zero-value order costs nothing."""
    value = abs(value)
    if value <= 0:
        return 0.0
    if on < EQ_FEES_FROM:
        raise ValueError(f"no futures fee schedule before {EQ_FEES_FROM}: {on}")
    taxable = BROKERAGE_PER_ORDER + (_rate(_FUT_TXN[exch], on) + SEBI_PCT) * value
    stat = FUT_STAMP_BUY_PCT * value if buy else _rate(_FUT_STT_SELL[exch], on) * value
    return taxable * (1 + _rate(_INDIRECT_TAX, on)) + stat
