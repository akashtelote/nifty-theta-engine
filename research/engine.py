"""Real-chain Bull Put Credit Spread backtest engine (Phase 3).

Built and tested on SYNTHETIC fixtures only; the pre-registration (docs/plans/) freezes every parameter before
any real result is read. Rules, all deterministic:

* Entry: last trading day of each ISO week (Friday, else the last open day) at that day's settle +- slip.
  One position at a time (next entry must be strictly after the previous exit). No staggered entries.
* Expiry: the nearest listed expiry with dte in [dte_lo, dte_hi] (expiries are read from the data).
* Short put: liquid strike (contracts >= min_contracts, settle >= min_settle, multiple of 50, below the forward)
  whose Black-76 delta (IV solved from its own settle, forward from put-call parity, r = 0) is closest to
  `delta`. Hedge: strike - width, same liquidity rule. If either is missing the week is skipped.
* Gates (a subset of the live bot's; VIX is not in bhavcopy): credit/width >= min_cw on the *natural* credit and
  parity-forward >= SMA50 of the parity-forward series (needs 50 prior days; no entries before that).
* Sizing: core.sizing.risk_lots on realised equity, natural credit, point-in-time lot size.
* Exits are decided on a day's settle and EXECUTED at the next trading day's settle +- slip (conservative: the
  overnight gap is paid). Reaching expiry cash-settles at intrinsic with no exit order; exercise STT is charged
  on an ITM long put. Fees: config.settings.round_trip_fees (date-aware) plus exercise STT.
  exit_mode: 'stop2x' = TP at residual <= tp_residual*credit, SL at cost >= sl_mult*credit;
             'mgmt'   = TP, no premium stop, close when short delta >= delta_manage or dte <= dte_manage;
             'hold'   = TP only, otherwise hold to expiry (defined risk).
Known simplifications: settle (15:30) stands in for the 15:15 entry price; r = 0; fees use the entry-date regime.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import polars as pl

from config.settings import BROKERAGE_PER_ORDER, GST_PCT, exercise_stt, round_trip_fees
from core.sizing import risk_lots
from research.execution import fill
from research.reference import lot_size

EXIT_MODES = ("stop2x", "mgmt", "hold")


@dataclass(frozen=True)
class Config:
    width: float = 100
    delta: float = 0.20
    exit_mode: str = "stop2x"
    dte_lo: int = 3
    dte_hi: int = 10
    slip: float = 0.5
    equity0: float = 2_000_000.0
    risk_pct: float = 0.02
    port_pct: float = 0.08
    tp_residual: float = 0.25
    sl_mult: float = 2.0
    delta_manage: float = 0.40
    dte_manage: int = 1
    min_cw: float = 0.15
    sma_gate: bool = True
    sma_days: int = 50
    min_contracts: int = 50
    min_settle: float = 1.0


@dataclass
class Trade:
    entry: date
    expiry: date
    short_k: float
    long_k: float
    lots: int
    lot: int
    credit: float          # natural net credit per share
    exit: date | None = None
    reason: str = ""
    exit_cost: float = 0.0  # natural cost to close per share (0 impl. at expiry = settlement value)
    fees: float = 0.0
    pnl: float = 0.0        # rupees, net of fees
    max_loss: float = 0.0   # rupees at entry: (width - credit) * lot * lots
    worst_pnl: float = 0.0  # worst mid mark-to-market P&L (rupees, before fees) seen while open
    marks: int = 0


# ---------- pricing ----------
def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _put(f: float, k: float, t: float, v: float) -> float:
    d1 = (math.log(f / k) + 0.5 * v * v * t) / (v * math.sqrt(t))
    return k * _ncdf(-(d1 - v * math.sqrt(t))) - f * _ncdf(-d1)


def put_delta(f: float, k: float, t: float, price: float) -> float | None:
    """|delta| of a put from its price (Black-76, r=0). None if the price cannot be inverted."""
    if t <= 0 or price <= 0 or price >= k:
        return None
    if price <= max(k - f, 0) + 1e-9:
        return 1.0  # at/below parity intrinsic (illiquid deep-ITM settle): treat as fully ITM
    lo, hi = 0.01, 3.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _put(f, k, t, mid) < price:
            lo = mid
        else:
            hi = mid
    v = 0.5 * (lo + hi)
    return _ncdf(-(math.log(f / k) + 0.5 * v * v * t) / (v * math.sqrt(t)))


def forward(day: pl.DataFrame, expiry: date, min_contracts: int = 50, col: str = "settle") -> float | None:
    """Parity forward for one expiry: median over the 5 liquid strikes with the smallest |ce - pe|."""
    e = day.filter((pl.col("expiry") == expiry) & (pl.col("contracts") >= min_contracts))
    ce = e.filter(pl.col("opt_type") == "CE").select("strike", ce=col)
    pe = e.filter(pl.col("opt_type") == "PE").select("strike", pe=col)
    j = ce.join(pe, on="strike")
    if j.height < 3:
        return None
    j = j.with_columns(g=(pl.col("ce") - pl.col("pe")).abs()).sort("g").head(5)
    return float((j["strike"] + j["ce"] - j["pe"]).median())


# ---------- data ----------
class Chain:
    """Per-day frames of liquid-enough Nifty options with point-in-time lot sizes; dte <= max_dte only."""

    def __init__(self, df: pl.DataFrame, max_dte: int = 20):
        df = df.filter(((pl.col("expiry") - pl.col("date")).dt.total_days()).is_between(0, max_dte))
        pairs = df.filter(pl.col("lot_size").is_null()).select("date", "expiry").unique()
        if not pairs.is_empty():
            lots = pairs.with_columns(pl.struct("date", "expiry").map_elements(
                lambda r: lot_size(r["date"], r["expiry"]), return_dtype=pl.Int64).alias("_lot"))
            df = df.join(lots, on=["date", "expiry"], how="left").with_columns(
                pl.coalesce("lot_size", "_lot").alias("lot_size")).drop("_lot")
        self.days: dict[date, pl.DataFrame] = {k[0]: v for k, v in df.partition_by("date", as_dict=True).items()}
        self.dates = sorted(self.days)
        self._spot: dict[date, float | None] = {}

    def spot(self, d: date) -> float | None:
        """Parity-forward of the nearest expiry with dte >= 2 (proxy for spot; only used for the SMA gate)."""
        if d not in self._spot:
            day = self.days[d]
            ex = sorted(e for e in day["expiry"].unique().to_list() if (e - d).days >= 2)
            self._spot[d] = forward(day, ex[0]) if ex else None
        return self._spot[d]

    def sma(self, d: date, n: int) -> float | None:
        i = self.dates.index(d)
        if i < n - 1:
            return None
        xs = [self.spot(x) for x in self.dates[i - n + 1:i + 1]]
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if len(xs) >= int(0.8 * n) else None


def _px(day: pl.DataFrame, expiry: date, k: float, typ: str = "PE") -> float | None:
    r = day.filter((pl.col("expiry") == expiry) & (pl.col("strike") == k) & (pl.col("opt_type") == typ))
    return float(r["settle"][0]) if r.height else None


def underlying_settle(day: pl.DataFrame, expiry: date) -> float | None:
    """Index settlement price on expiry day, or None if `settle` already holds option values. The bhavcopy `settle` of
    every strike of an expiring series is (a) the index settle from 2020-02-06 (one number, mode > 1000), (b) 0.0 on
    every row before that, so the index is taken from put-call parity on `close` (last-traded, ~intrinsic near expiry)."""
    s = day.filter(pl.col("expiry") == expiry)["settle"]
    if s.len() < 3:
        return None
    mode = s.mode().sort()[0]
    if mode > 1000 and (s == mode).mean() >= 0.5:
        return float(mode)
    if s.max() <= 0:
        f = forward(day, expiry, 1, "close")
        if f is None:
            raise ValueError(f"zero-settle expiry {expiry}: no close-parity forward, cannot value options")
        return f
    return None


def _expiry_value(day: pl.DataFrame, expiry: date, k: float) -> tuple[float, float | None]:
    """(put settlement value, underlying settlement price) on expiry day."""
    s = underlying_settle(day, expiry)
    if s is not None:
        return max(k - s, 0.0), s
    p = _px(day, expiry, k)
    if p is None:
        f = forward(day, expiry, 1)
        if f is None:
            raise ValueError(f"cannot value {k} put at expiry {expiry}")
        p = max(k - f, 0.0)
    return p, forward(day, expiry, 1)


# ---------- engine ----------
def entry_days(dates: list[date]) -> list[date]:
    """Last trading day of each ISO week."""
    out: dict[tuple[int, int], date] = {}
    for d in dates:
        out[d.isocalendar()[:2]] = d
    return sorted(out.values())


def _select(chain: Chain, d: date, cfg: Config):
    """Pick expiry, strikes and natural credit for an entry on d, or (None, reason)."""
    day = chain.days[d]
    ex = sorted(e for e in day["expiry"].unique().to_list() if cfg.dte_lo <= (e - d).days <= cfg.dte_hi)
    if not ex:
        return None, "no expiry in band"
    e = ex[0]
    f = forward(day, e)
    if f is None:
        return None, "no forward"
    t = (e - d).days / 365.0
    puts = day.filter((pl.col("expiry") == e) & (pl.col("opt_type") == "PE") & (pl.col("contracts") >= cfg.min_contracts)
                      & (pl.col("settle") >= cfg.min_settle) & (pl.col("strike") < f) & (pl.col("strike") % 50 == 0))
    best = None
    for k, p in puts.select("strike", "settle").iter_rows():
        dl = put_delta(f, k, t, p)
        if dl is not None and (best is None or abs(dl - cfg.delta) < abs(best[1] - cfg.delta)):
            best = (k, dl, p)
    if best is None:
        return None, "no short strike"
    sk = best[0]
    lk = sk - cfg.width
    hedge = puts.filter(pl.col("strike") == lk)
    if hedge.is_empty():
        return None, "no hedge strike"
    credit = fill(best[2], "sell", cfg.slip) - fill(float(hedge["settle"][0]), "buy", cfg.slip)
    lot = int(day.filter(pl.col("expiry") == e)["lot_size"][0])
    return (e, sk, lk, credit, lot, f), ""


def _fees(tr: Trade, d_entry: date, se: float, le: float, sx: float, lx: float, expired: bool, s_exp: float | None) -> float:
    on = d_entry
    if not expired:
        return round_trip_fees(tr.credit, sx - lx, tr.lot, tr.lots, on=on, legs=(se, le, sx, lx))
    f = round_trip_fees(tr.credit, 0.0, tr.lot, tr.lots, on=on, legs=(se, le, 0.0, 0.0))
    f -= 2 * BROKERAGE_PER_ORDER * (1 + GST_PCT)  # no exit orders: cash-settled
    if s_exp is not None and tr.long_k > s_exp:
        q = tr.lot * tr.lots
        f += exercise_stt((tr.long_k - s_exp) * q, on=tr.expiry, settlement_value=s_exp * q)
    return f


def run(chain: Chain, cfg: Config, start: date, end: date, dropped: list | None = None) -> list[Trade]:
    if cfg.exit_mode not in EXIT_MODES:
        raise ValueError(cfg.exit_mode)
    trades: list[Trade] = []
    equity, last_exit = cfg.equity0, date.min
    for d in entry_days([x for x in chain.dates if start <= x <= end]):
        if d <= last_exit:
            continue
        if cfg.sma_gate:
            sma, sp = chain.sma(d, cfg.sma_days), chain.spot(d)
            if sma is None or sp is None or sp < sma:
                continue
        sel, _ = _select(chain, d, cfg)
        if sel is None:
            continue
        e, sk, lk, credit, lot, _f = sel
        if credit <= 0 or credit / cfg.width < cfg.min_cw:
            continue
        lots, _why = risk_lots(cfg.width, credit, lot, min(equity, cfg.equity0), 0.0, cfg.risk_pct, cfg.port_pct)
        if lots < 1:
            continue
        tr = Trade(d, e, sk, lk, lots, lot, credit, max_loss=(cfg.width - credit) * lot * lots)
        se = fill(_px(chain.days[d], e, sk), "sell", cfg.slip)
        le = fill(_px(chain.days[d], e, lk), "buy", cfg.slip)
        _walk(chain, cfg, tr, se, le)
        if tr.exit is None:
            if dropped is not None:
                dropped.append(d)  # entry still open when the data ends
            break
        equity += tr.pnl
        last_exit = tr.exit
        trades.append(tr)
    return trades


def _walk(chain: Chain, cfg: Config, tr: Trade, se: float, le: float) -> None:
    # An expiry that falls on an exchange holiday is settled on the previous trading day, and the series is relabelled
    # with that date in the bhavcopy (e.g. listed 2023-06-29, settled and relabelled 2023-06-28).
    ex = tr.expiry
    if ex not in chain.days and chain.dates[-1] > ex:
        ex = max(x for x in chain.dates if x < ex)
    dates = [x for x in chain.dates if tr.entry < x <= ex]
    pending: str | None = None
    for d in dates:
        day = chain.days[d]
        lab = ex if d == ex else tr.expiry
        sp, lp = _px(day, lab, tr.short_k), _px(day, lab, tr.long_k)
        if d == ex and sp is not None and lp is not None:  # expiry-day rows hold the index settle, not option prices
            sp, lp = max(_expiry_value(day, d, tr.short_k)[0], 0.05), max(_expiry_value(day, d, tr.long_k)[0], 0.05)
        if pending is not None and sp is not None and lp is not None:
            sx, lx = fill(sp, "buy", cfg.slip), fill(lp, "sell", cfg.slip)
            tr.exit, tr.reason, tr.exit_cost = d, pending, sx - lx
            tr.fees = _fees(tr, tr.entry, se, le, sx, lx, False, None)
            tr.pnl = (tr.credit - tr.exit_cost) * tr.lot * tr.lots - tr.fees
            tr.worst_pnl = min(tr.worst_pnl, (tr.credit - (sp - lp)) * tr.lot * tr.lots)
            return
        if d == ex:
            sv, s_exp = _expiry_value(day, d, tr.short_k)
            lv, s2 = _expiry_value(day, d, tr.long_k)
            s_exp = s_exp if s_exp is not None else s2
            cost = sv - lv
            tr.exit, tr.reason, tr.exit_cost = d, "expiry", cost
            tr.fees = _fees(tr, tr.entry, se, le, 0.0, 0.0, True, s_exp)
            tr.pnl = (tr.credit - cost) * tr.lot * tr.lots - tr.fees
            tr.worst_pnl = min(tr.worst_pnl, (tr.credit - cost) * tr.lot * tr.lots)
            return
        if sp is None or lp is None:
            continue  # stale: carry the previous decision state
        tr.marks += 1
        cost = sp - lp
        tr.worst_pnl = min(tr.worst_pnl, (tr.credit - cost) * tr.lot * tr.lots)
        if cost <= cfg.tp_residual * tr.credit:
            pending = "tp"
        elif cfg.exit_mode == "stop2x" and cost >= cfg.sl_mult * tr.credit:
            pending = "stop"
        elif cfg.exit_mode == "mgmt":
            f = forward(day, tr.expiry)
            dl = put_delta(f, tr.short_k, (ex - d).days / 365.0, sp) if f is not None else None
            if (dl is not None and dl >= cfg.delta_manage) or (ex - d).days <= cfg.dte_manage:
                pending = "manage"
    if chain.dates[-1] < tr.expiry:
        return  # still open at the end of the data: run() drops it
    raise RuntimeError("expiry day missing from data")  # a hole is loud, never a silent drop
