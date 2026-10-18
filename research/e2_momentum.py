"""E2: cross-sectional 12-1 momentum, DEV only (plan 20261017-equity-futures-hypotheses, E2 + rules 6-8, A2 amendment 3).

Universe (month m, from the close of the last session L of month m-1): EQ-series row on L, close >= Rs20, first row
of the permanent stock ID (A1 chain) on or before L - 13 months, top 500 by median daily traded value over the
sessions in (L - 6 months, L] (a session with no row counts as 0).
Signal: A2-adjusted close at the end of month m-2 / at the end of month m-13 - 1 (last row on or before each month-end
session, within 40 days, else no signal); no signal when ca_flag_n rises across that window (amendment 3).
Trades: close of the first session of month m. A holding is kept while its rank is <= 50, otherwise sold; cash is split
equally across the best-ranked names not held until 25 are held, whole shares, a name priced above its slot (or
not trading as EQ that session) is skipped. A sale with no row that session goes at the stock's next close.
Regime: equal-weight daily return of the current universe (membership as above), chained from the Dec-2008 close; at
L, index < its 200-session average -> everything is sold at the first session of month m and the book stays in cash
(earning 0) until a month-end where it is back above.
Costs: slippage 0.15% per side for the top 200 of the universe by traded value, 0.35% otherwise (and for any stock
outside the universe); dated delivery fees (config.settings.equity_delivery_fees); position <= 2% of the median
daily traded value. Rule 7: no row for 5 consecutive sessions -> sold at the last close -30%, no slippage.
Amendment 3 inside a portfolio: a held stock's flagged session is not a tradable move, so its return that session
is set to 0 (units rescaled); the count is reported.
Tax (rule 6): per FY, STCG and (from 2018-04-01) LTCG with current-year set-off and carried-forward losses, LTCG
grandfathered to the 2018-01-31 close; paid from cash on the first session on or after 1 April (cash may go
negative until the next sale; the minimum is reported). At the end of DEV the book is sold and that FY's tax paid.
Gates (DEV; gate 4 is OOS-only): 1 CAGR after costs and tax > Nifty 500 TRI and > Nifty200 Momentum 30 TRI;
2 the 98.75% stationary-bootstrap (mean block 6 months) CI of the mean monthly excess over the Nifty 500 TRI has
lower bound > 0; 3 max drawdown of the daily NAV <= 35%. Months run month-end close to month-end close, starting
with Rs2L in cash at the last session of Dec-2009.
Secondary (reported only): no regime filter; 6-month signal (end m-7 -> end m-2, same skip month); rebalancing
only in January and July.
Run: uv run python -m research.e2_momentum   -> data/e2/dev_report.txt, data/e2/dev_nav.parquet
"""
from __future__ import annotations

import random
from bisect import bisect_right
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from math import floor
from pathlib import Path

import polars as pl

from config.settings import equity_delivery_fees
from research import corp_actions, equity, stock_id

OUT = Path("data/e2")
TRI = {"Nifty 500 TRI": Path("data/benchmarks/tri_nifty_500.parquet"),
       "Nifty200 Momentum 30 TRI": Path("data/benchmarks/tri_nifty200_momentum_30.parquet")}
DEV = (date(2010, 1, 1), date(2018, 12, 31))
REGIME_FROM = date(2009, 1, 1)
CAPITAL = 200_000.0
SLOTS, KEEP, UNIVERSE, TOP_LIQ = 25, 50, 500, 200
MIN_PRICE, HISTORY_M, LIQ_M = 20.0, 13, 6
SLIP_TOP, SLIP_REST = 0.0015, 0.0035
ADV_CAP = 0.02
SMA = 200
HAIRCUT, MISSING = 0.30, 5
FMV_DAY, GF_BUY_BEFORE, LTCG_FROM = date(2018, 1, 31), date(2018, 2, 1), date(2018, 4, 1)
CONF, BOOT, BLOCK, SEED = 0.9875, 10_000, 6, 20261017
MAX_DD = 0.35


def months_back(d: date, k: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - k, 12)
    return date(y, m + 1, min(d.day, monthrange(y, m + 1)[1]))


def median_padded(v: list, n: int) -> float:
    """Median of n sessions' traded value, where the len(v) traded sessions are padded with zeros."""
    s = sorted([x or 0.0 for x in v] + [0.0] * (n - len(v)))
    return (s[(n - 1) // 2] + s[n // 2]) / 2


def month_bounds(cal: list[date]) -> dict[int, tuple[date, date]]:
    """month key (year * 12 + month - 1) -> (first session, last session)."""
    b: dict[int, tuple[date, date]] = {}
    for d in cal:
        k = d.year * 12 + d.month - 1
        b[k] = (b[k][0], d) if k in b else (d, d)
    return b


def _last_on(rows: pl.DataFrame, d: date, ids: pl.Series) -> pl.DataFrame:
    return (rows.filter(pl.col("date").is_between(d - timedelta(days=40), d) & pl.col("perm_id").is_in(ids.to_list()))
            .sort("date").group_by("perm_id").last().select("perm_id", "adj_close", "ca_flag_n"))


def universe(rows: pl.DataFrame, first: pl.DataFrame, cal: list[date], ends: dict, m: int) -> pl.DataFrame:
    """Universe for trading month m with liq_rank, medval, sig12/sig6 and rank12/rank6 (1 = best, null = no signal)."""
    L = ends[m - 1][1]
    on = (rows.filter((pl.col("date") == L) & (pl.col("series") == "EQ") & (pl.col("close") >= MIN_PRICE))
          .join(first.filter(pl.col("first") <= months_back(L, HISTORY_M)), on="perm_id").select("perm_id", "close"))
    i0, i1 = bisect_right(cal, months_back(L, LIQ_M)), bisect_right(cal, L)
    v = (rows.filter(pl.col("date").is_between(cal[i0], L) & pl.col("perm_id").is_in(on["perm_id"].to_list()))
         .group_by("perm_id").agg(pl.col("value")))
    med = pl.DataFrame({"perm_id": v["perm_id"], "medval": [median_padded(x, i1 - i0) for x in v["value"].to_list()]},
                       schema={"perm_id": pl.String, "medval": pl.Float64})
    u = (on.join(med, on="perm_id").sort(["medval", "perm_id"], descending=[True, False]).head(UNIVERSE)
         .with_row_index("liq_rank", offset=1))
    for k, a in ((12, ends[m - 13][1]), (6, ends[m - 7][1])):
        x, y = _last_on(rows, a, u["perm_id"]), _last_on(rows, ends[m - 2][1], u["perm_id"])
        s = (x.join(y, on="perm_id", suffix="_b").filter(pl.col("ca_flag_n_b") <= pl.col("ca_flag_n"))
             .select("perm_id", (pl.col("adj_close_b") / pl.col("adj_close") - 1).alias(f"sig{k}")))
        r = s.sort([f"sig{k}", "perm_id"], descending=[True, False]).select("perm_id").with_row_index(f"rank{k}", offset=1)
        u = u.join(s, on="perm_id", how="left").join(r, on="perm_id", how="left")
    return u


def regime(rows: pl.DataFrame, cal: list[date], unis: dict[int, pl.DataFrame]) -> dict[date, bool]:
    """date -> universe index >= its SMA-session average (True when the average is not yet defined)."""
    prev = pl.DataFrame({"date": cal[1:], "ps": cal[:-1]})
    mem = pl.concat([u.select("perm_id").with_columns(m=pl.lit(m)) for m, u in unis.items()])
    r = (rows.filter(pl.col("date") >= cal[bisect_right(cal, REGIME_FROM) - 1]).sort("perm_id", "date")
         .with_columns(pa=pl.col("adj_close").shift().over("perm_id"), pd=pl.col("date").shift().over("perm_id"))
         .join(prev, on="date").filter((pl.col("pd") == pl.col("ps")) & ~pl.col("ca_flag"))
         .with_columns(m=pl.col("date").dt.year().cast(pl.Int64) * 12 + pl.col("date").dt.month().cast(pl.Int64) - 1)
         .join(mem, on=["perm_id", "m"]).group_by("date").agg(r=(pl.col("adj_close") / pl.col("pa") - 1).mean())
         .sort("date").with_columns(ix=(1 + pl.col("r")).cum_prod())
         .with_columns(sma=pl.col("ix").rolling_mean(SMA)))
    return {d: s is None or ix >= s for d, ix, s in r.select("date", "ix", "sma").iter_rows()}


def fy_tax(st: float, lt: float, cf: list[float], fy: int) -> float:
    """Tax for financial year fy (Apr fy .. Mar fy+1) on net short / long-term gains. cf = [ST, LT] losses carried in,
    updated in place. ST losses offset ST then LT gains; LT losses only LT gains.
    ponytail: FY2024-25 is taxed at the post-2024-07-23 rates and Rs1.25L exemption for the whole year (conservative;
    OOS only); the 8-year carry-forward limit is ignored."""
    rst, rlt, ex = (0.20, 0.125, 125_000.0) if fy >= 2024 else (0.15, 0.10, 100_000.0)
    cess = 1.04 if fy >= 2018 else 1.03
    if st < 0 < lt:
        u = min(-st, lt)
        st, lt = st + u, lt - u
    for i, g in ((0, "st"), (1, "lt"), (0, "lt")):
        gain = st if g == "st" else lt
        u = min(cf[i], max(gain, 0.0))
        cf[i] -= u
        if g == "st":
            st -= u
        else:
            lt -= u
    cf[0] += max(-st, 0.0)
    cf[1] += max(-lt, 0.0)
    return (max(st, 0.0) * rst + max(lt - ex, 0.0) * rlt) * cess


@dataclass
class Pos:
    units: float  # adjusted units: value = units * adj_close
    basis: float  # rupees paid incl. slippage and buy fees
    bought: date
    last: float   # last adj_close seen
    slip: float
    fmv: float | None = None  # value at the 2018-01-31 close (LTCG grandfathering)
    miss: int = 0
    sell: bool = False


def _plus_year(d: date) -> date:
    return d.replace(year=d.year + 1) if (d.month, d.day) != (2, 29) else date(d.year + 1, 2, 28)


def simulate(cal: list[date], book: dict, px: dict, start: date, end: date, rank: str = "rank12",
             slots: int = SLOTS, keep: int = KEEP) -> tuple[pl.DataFrame, dict]:
    """book: rebalance session -> (universe frame, regime on). px: perm_id -> date -> (close, adj_close, ca_flag,
    series). Returns the daily NAV (after that session's trades and tax) and tallies."""
    sess = [d for d in cal if start <= d <= end]
    cash, pos = CAPITAL, {}
    st: dict[int, float] = defaultdict(float)
    lt: dict[int, float] = defaultdict(float)
    cf = [0.0, 0.0]
    t = defaultdict(float, min_cash=CAPITAL)
    s0 = sess[0]
    due = date((s0.year if s0.month >= 4 else s0.year - 1) + 1, 4, 1)

    def slip_for(liq):
        return SLIP_TOP if liq is not None and liq <= TOP_LIQ else SLIP_REST

    def realise(pid: str, gross: float, slip: float, d: date) -> float:
        p = pos.pop(pid)
        value = gross * (1 - slip)
        net = value - equity_delivery_fees(0.0, value, d, d)
        t["sells"] += value
        t["slip"] += gross * slip
        t["fees"] += value - net
        basis = p.basis
        long_ = d > _plus_year(p.bought)
        if long_ and p.bought < GF_BUY_BEFORE and d >= LTCG_FROM and p.fmv is not None:
            basis = max(basis, min(p.fmv, net))
        fy = d.year if d.month >= 4 else d.year - 1
        if not long_:
            st[fy] += net - basis
        elif d >= LTCG_FROM:  # LTCG (and its losses) exempt before 2018-04-01
            lt[fy] += net - basis
        return net

    def pay(fy: int) -> float:
        tax = fy_tax(st.pop(fy, 0.0), lt.pop(fy, 0.0), cf, fy)
        t["tax"] += tax
        return tax

    nav = []
    for d in sess:
        for pid, p in list(pos.items()):
            r = px[pid].get(d)
            if r is None:
                p.miss += 1
                if p.miss == MISSING:
                    cash += realise(pid, p.units * p.last * (1 - HAIRCUT), 0.0, d)
                    t["forced"] += 1
                continue
            if r[2]:  # flagged session: not a tradable move (amendment 3)
                p.units *= p.last / r[1]
                t["neutralised"] += 1
            p.last, p.miss = r[1], 0
            if d <= FMV_DAY:
                p.fmv = p.units * r[1]
            if p.sell:
                cash += realise(pid, p.units * r[1], p.slip, d)
        u, on = book.get(d, (None, False))
        if u is not None:
            rk = dict(zip(u["perm_id"], u[rank]))
            liq = dict(zip(u["perm_id"], u["liq_rank"]))
            for pid, p in list(pos.items()):
                if p.sell or (on and rk.get(pid) is not None and rk[pid] <= keep):
                    continue
                p.slip = slip_for(liq.get(pid))
                if d in px[pid]:
                    cash += realise(pid, p.units * p.last, p.slip, d)
                else:
                    p.sell = True
        while d >= due:
            cash -= pay(due.year - 1)
            due = due.replace(year=due.year + 1)
        if u is not None and on:
            need = slots - sum(not p.sell for p in pos.values())
            slot = cash / need if need > 0 else 0.0
            for row in u.filter(pl.col(rank) <= keep).sort(rank).iter_rows(named=True):  # never rebuy a name just sold
                if need <= 0 or slot <= 0:
                    break
                pid = row["perm_id"]
                if pid in pos:
                    continue
                r = px[pid].get(d)
                if r is None or r[3] != "EQ":
                    continue
                sl = slip_for(row["liq_rank"])
                sh = min(floor(slot / (r[0] * (1 + sl))), floor(ADV_CAP * row["medval"] / r[0]))
                while sh > 0:
                    cost = sh * r[0] * (1 + sl)
                    fee = equity_delivery_fees(cost, 0.0, d, d)
                    if cost + fee <= slot:
                        break
                    sh -= 1
                if sh <= 0:
                    continue
                cash -= cost + fee
                t["buys"] += cost
                t["slip"] += cost - cost / (1 + sl)
                t["fees"] += fee
                pos[pid] = Pos(units=sh * r[0] / r[1], basis=cost + fee, bought=d, last=r[1], slip=sl,
                               fmv=sh * r[0] if d <= FMV_DAY else None)
                need -= 1
        if d == sess[-1]:  # end of window: sell everything at the last known close, pay this FY's tax
            for pid, p in list(pos.items()):
                cash += realise(pid, p.units * p.last, p.slip, d)
            for fy in sorted(set(st) | set(lt)):
                cash -= pay(fy)
        t["min_cash"] = min(t["min_cash"], cash)
        nav.append({"date": d, "nav": cash + sum(p.units * p.last for p in pos.values()), "cash": cash,
                    "held": len(pos), "on": on if u is not None else None})
    return pl.DataFrame(nav), t


def stationary_ci(x: list[float], block: int = BLOCK) -> tuple[float, float]:
    """Two-sided CONF CI of the mean, stationary bootstrap (Politis-Romano) with mean block BLOCK, circular, seeded."""
    rng, n, p = random.Random(SEED), len(x), 1 / block
    means = []
    for _ in range(BOOT):
        i, s = rng.randrange(n), 0.0
        for _ in range(n):
            s += x[i]
            i = rng.randrange(n) if rng.random() < p else (i + 1) % n
        means.append(s / n)
    means.sort()
    q = (1 - CONF) / 2
    return means[int(q * BOOT)], means[min(BOOT - 1, int((1 - q) * BOOT))]


def metrics(nav: pl.DataFrame, t0: date, mends: list[date], tri: dict[str, dict]) -> dict:
    """mends: month-end sessions from t0 (NAV = CAPITAL, before any trade) to the last DEV session."""
    v = dict(zip(nav["date"], nav["nav"])) | {t0: CAPITAL}
    pv = [v[d] for d in mends]
    years = (mends[-1] - mends[0]).days / 365.25
    out = {"cagr": (pv[-1] / CAPITAL) ** (1 / years) - 1, "final": pv[-1]}
    n500 = [tri["Nifty 500 TRI"][d] for d in mends]
    out["bench"] = {k: (b[mends[-1]] / b[mends[0]]) ** (1 / years) - 1 for k, b in tri.items()}
    ex = [a1 / a0 - b1 / b0 for a0, a1, b0, b1 in zip(pv, pv[1:], n500, n500[1:])]
    out["excess_mean"], out["ci"] = sum(ex) / len(ex), stationary_ci(ex)
    out["months"] = len(ex)
    navs = [CAPITAL] + nav["nav"].to_list()
    peak, dd = navs[0], 0.0
    for x in navs:
        peak = max(peak, x)
        dd = max(dd, 1 - x / peak)
    out["mdd"] = dd
    return out


def load() -> tuple[pl.DataFrame, list[date]]:
    """A2 rows + series/value, DEV and earlier only (OOS rows never loaded)."""
    a = corp_actions.build()["rows"].filter(pl.col("date") <= DEV[1])
    e = equity.load(end=DEV[1]).select("date", "symbol", "series", "value")
    rows = a.join(e, on=["date", "symbol"], how="left")
    return rows, [d for d in stock_id.sessions(rows.select("date")) if d <= DEV[1]]


def run() -> str:
    rows, cal = load()
    first = rows.group_by("perm_id").agg(first=pl.col("date").min())
    ends = month_bounds(cal)
    rows = rows.filter(pl.col("date") >= date(2007, 6, 1))
    m0, m1 = REGIME_FROM.year * 12, DEV[1].year * 12 + DEV[1].month - 1
    unis = {m: universe(rows, first, cal, ends, m) for m in range(m0, m1 + 1)}
    on = regime(rows, cal, unis)
    dev_months = [m for m in unis if m >= DEV[0].year * 12]
    pids = set(pl.concat([u.filter((pl.col("rank12") <= 200) | (pl.col("rank6") <= 200)).select("perm_id")
                          for u in unis.values()])["perm_id"].to_list())
    t0 = ends[dev_months[0] - 1][1]
    px: dict[str, dict] = defaultdict(dict)
    for pid, d, c, ac, f, s in (rows.filter(pl.col("perm_id").is_in(list(pids)) & (pl.col("date") >= t0))
                                .select("perm_id", "date", "close", "adj_close", "ca_flag", "series").iter_rows()):
        px[pid][d] = (c, ac, f, s)
    px = dict(px)  # a stock needed beyond rank 200 raises KeyError instead of being skipped
    mends = [t0] + [ends[m][1] for m in dev_months]
    tri = {k: dict(pl.read_parquet(p).select("date", "tri").iter_rows()) for k, p in TRI.items()}

    def book(months=None, use_regime=True):
        return {ends[m][0]: (unis[m], on[ends[m - 1][1]] if use_regime else True)
                for m in dev_months if months is None or m % 12 + 1 in months}

    variants = {"PRIMARY 12-1, monthly, regime filter": (book(), "rank12"),
                "no regime filter": (book(use_regime=False), "rank12"),
                "6-month signal (m-7 -> m-2)": (book(), "rank6"),
                "semi-annual (Jan/Jul)": (book(months={1, 7}), "rank12")}
    lines = [f"E2 cross-sectional momentum - DEV ({DEV[0]}..{DEV[1]}, months from {t0} close). Generated {date.today()}.",
             f"Universe sizes: min {min(u.height for u in unis.values())}, months {len(unis)}; regime months in cash "
             f"(DEV): {sum(not on[ends[m - 1][1]] for m in dev_months)}/{len(dev_months)}", ""]
    verdict = None
    for name, (bk, rank) in variants.items():
        nav, t = simulate(cal, bk, px, ends[dev_months[0]][0], DEV[1], rank=rank)
        mt = metrics(nav, t0, mends, tri)
        g1 = all(mt["cagr"] > b for b in mt["bench"].values())
        g2, g3 = mt["ci"][0] > 0, mt["mdd"] <= MAX_DD
        if verdict is None:
            verdict = "PASS" if g1 and g2 and g3 else "FAIL"
            lines.append(f"GATE (DEV; gate 4 is OOS-only): 1 CAGR > both TRIs {'ok' if g1 else 'FAIL'}; "
                         f"2 CI lower > 0 {'ok' if g2 else 'FAIL'}; 3 MDD <= {MAX_DD:.0%} {'ok' if g3 else 'FAIL'}"
                         f"  ->  {verdict}")
            OUT.mkdir(parents=True, exist_ok=True)
            nav.write_parquet(OUT / "dev_nav.parquet")
        yrs = mt["months"] / 12
        lines += [f"{name}: CAGR after costs+tax {mt['cagr']:+.2%} (final Rs{mt['final']:,.0f}); "
                  + "; ".join(f"{k} {b:+.2%}" for k, b in mt["bench"].items()),
                  f"  monthly excess vs Nifty 500 TRI: mean {mt['excess_mean']:+.3%}, {CONF:.2%} CI "
                  f"[{mt['ci'][0]:+.3%}, {mt['ci'][1]:+.3%}] over {mt['months']} months; max drawdown {mt['mdd']:.1%}",
                  f"  turnover (sells / Rs2L / yr) {t['sells'] / CAPITAL / yrs:.1f}x; slippage Rs{t['slip']:,.0f}, "
                  f"fees Rs{t['fees']:,.0f}, tax Rs{t['tax']:,.0f}; forced exits {t['forced']:.0f}; flagged sessions "
                  f"neutralised {t['neutralised']:.0f}; min cash Rs{t['min_cash']:,.0f}; avg held "
                  f"{nav['held'].mean():.1f}"]
        if name.startswith("PRIMARY"):
            lines.append("Secondary (reported only):")
    text = "\n".join(lines) + "\n"
    (OUT / "dev_report.txt").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(run())
