"""Phase B measurement study (docs/plans/20261017-next-hypotheses-plan.md): does the ATM straddle over- or
under-price the move that follows, and can we tell which in advance? DEV 2019-01..2023-12 only.

Implementation choices (fixed before any number was looked at):
  * Rows = (day, expiry) from iv.surface on `close` (cached at data/index/surface_2019_2023.parquet); expiries
    after 2023-12-31 are dropped so nothing settles outside DEV. Buckets: weekly dte 3-10, monthly 20-35 (calendar).
  * S_T = index close on the last trading day <= listed expiry (NSE settles index options at the closing index
    value; covers holiday-shifted expiries).
  * Short-straddle proxy (index points per unit) = straddle - 2*SLIP - |S_T - K| - fees, K = ATM strike of the row
    (the plan's |S_T - F| is the realised-move measure; the straddle pays off around K). Held to expiry, cash
    settled: no exit orders, and exercise STT falls on the buyer. The long-side mirror (H3) pays stamp on entry and
    exercise STT on the ITM leg, and is reported next to it.
  * Fees: round_trip_fees for 1 lot at the trade date's regime, divided by the lot to get points.
  * CIs: cluster bootstrap that resamples whole expiries (rows of one expiry overlap), alpha = 0.05/3.
  * Signals at the entry close: iv30 - harvol21 (HAR fitted on 2019-2023, as the plan says: in-sample by design),
    iv30 / rv21, 1y VIX percentile (trailing 252 sessions; needs 2018 index history, no 2018 options),
    put skew = put25_iv - atm_iv of the row's expiry. Quintile breakpoints per bucket over DEV.
  * Events (B3): ex-ante known at entry = scheduled and (announced blank or <= entry day), and for held=False rows
    only before the day they were called off (VOIDED). An expiry "contains" an event if its first trading session s has entry < s <= last session of the expiry.
    1-day proxy: ATM straddle of the nearest expiry > s, bought/sold at the close before s, closed at the close of
    s (4 orders, slip on 4 legs); s pairs sharing a session are counted once.
Run: uv run python -m research.phase_b > <out.md>
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date

import numpy as np
import polars as pl

from config.settings import BROKERAGE_PER_ORDER, GST_PCT, exercise_stt, round_trip_fees
from research import bhavcopy, events, rv
from research.iv import constant_maturity
from research.reference import lot_size

DEV = (date(2019, 1, 1), date(2023, 12, 31))
SURFACE = "data/index/surface_2019_2023.parquet"
SLIP = 0.5
ALPHA = 0.05 / 3
BUCKETS = {"weekly": (3, 10), "monthly": (20, 35)}
SIGNALS = ("iv_minus_har", "iv_over_rv", "vix_pct", "put_skew")


def cluster_ci(x: np.ndarray, g: np.ndarray, alpha: float = ALPHA, n: int = 5000, seed: int = 12345, stat=None):
    """Mean (or stat) and percentile CI of x, resampling whole clusters g with replacement."""
    keys, inv = np.unique(g, return_inverse=True)
    idx = np.random.default_rng(seed).integers(0, len(keys), (n, len(keys)))
    if stat is None:  # fast path for the mean
        s, c = np.bincount(inv, weights=x), np.bincount(inv).astype(float)
        m = s[idx].sum(1) / c[idx].sum(1)
        est = x.mean()
    else:  # ponytail: loop over resamples, fine for a few thousand rows
        parts = [x[inv == k] for k in range(len(keys))]
        m = np.array([stat(np.concatenate([parts[j] for j in row])) for row in idx])
        est = stat(x)
    return float(est), float(np.quantile(m, alpha / 2)), float(np.quantile(m, 1 - alpha / 2))


def fee_pts(d: date, expiry: date, entry: float, exit_: float | None, short: bool, s_t: float | None = None,
            k: float | None = None) -> float:
    """Fees per unit (index points) for a 1-lot straddle. exit_=None means held to expiry (cash settled)."""
    lot = lot_size(d, expiry) or 50
    if exit_ is not None:  # 4 orders round trip
        legs = (entry, 0.0, exit_, 0.0) if short else (0.0, entry, 0.0, exit_)
        return round_trip_fees(0, 0, lot, 1, on=d, legs=legs) / lot
    legs = (entry, 0.0, 0.0, 0.0) if short else (0.0, entry, 0.0, 0.0)
    f = round_trip_fees(0, 0, lot, 1, on=d, legs=legs) - 2 * BROKERAGE_PER_ORDER * (1 + GST_PCT)  # 2 orders only
    if not short and s_t != k:  # the buyer pays exercise STT on the leg that finishes ITM
        f += exercise_stt(abs(s_t - k) * lot, on=expiry, settlement_value=s_t * lot)
    return f / lot


def _settle_close(idx: pl.DataFrame, expiry: date) -> tuple[date, float]:
    days = idx["date"].to_list()
    i = bisect_right(days, expiry) - 1
    return days[i], float(idx["close"][i])


def build_rows(surf: pl.DataFrame, idx: pl.DataFrame) -> pl.DataFrame:
    """Hold-to-expiry rows with signals and proxies."""
    iv30 = constant_maturity(surf.filter(pl.col("date").is_between(*DEV)), 30)  # all listed expiries: known at d
    surf = surf.filter((pl.col("expiry") <= DEV[1]) & (pl.col("date") >= DEV[0]))
    i = rv.add_rv(idx, windows=(21,))
    coef = rv.har_fit(i, 21, *DEV)
    i = i.join(rv.har_forecast(i, coef, 21), on="date").with_columns(
        vix_pct=pl.col("vix").rolling_map(lambda s: (s <= s[-1]).mean(), 252))
    sig = iv30.join(i.select("date", "rv21", "harvol21", "vix_pct"), on="date")
    sig = sig.with_columns(iv_minus_har=pl.col("iv30") - pl.col("harvol21"), iv_over_rv=pl.col("iv30") / pl.col("rv21"))
    out = []
    for r in surf.iter_rows(named=True):
        last, s_t = _settle_close(idx, r["expiry"])
        k, st = r["atm_k"], r["straddle"]
        pay = abs(s_t - k)
        out.append({**r, "last_session": last, "s_t": s_t,
                    "implied_move": st / r["fwd"], "realised_move": abs(s_t - r["fwd"]) / r["fwd"],
                    "short_pnl": st - 2 * SLIP - pay - fee_pts(r["date"], r["expiry"], st, None, True),
                    "long_pnl": pay - st - 2 * SLIP - fee_pts(r["date"], r["expiry"], st, None, False, s_t, k),
                    "put_skew": (r["put25_iv"] - r["atm_iv"]) if r["put25_iv"] else None})
    rows = pl.DataFrame(out).join(sig.select("date", *SIGNALS[:3]), on="date", how="left")
    return rows.with_columns(bucket=pl.when(pl.col("dte").is_between(*BUCKETS["weekly"])).then(pl.lit("weekly"))
                             .when(pl.col("dte").is_between(*BUCKETS["monthly"])).then(pl.lit("monthly")))


def _ci(df: pl.DataFrame, col: str):
    return cluster_ci(df[col].to_numpy(), df["expiry"].cast(pl.Int32).to_numpy())


def b1(rows: pl.DataFrame) -> list[str]:
    out = ["| bucket | n rows | n expiries | implied - realised, % of F: mean [98.3% CI] | median [98.3% CI] | short proxy pts [98.3% CI] | long proxy pts [98.3% CI] |",
           "|---|---|---|---|---|---|---|"]
    for b in BUCKETS:
        g = rows.filter(pl.col("bucket") == b)
        d = ((g["implied_move"] - g["realised_move"]) * 100).to_numpy()
        cl = g["expiry"].cast(pl.Int32).to_numpy()
        m, md = cluster_ci(d, cl), cluster_ci(d, cl, stat=np.median)
        s, l = _ci(g, "short_pnl"), _ci(g, "long_pnl")
        out.append(f"| {b} | {g.height} | {g['expiry'].n_unique()} | {m[0]:.3f} [{m[1]:.3f}, {m[2]:.3f}] | "
                   f"{md[0]:.3f} [{md[1]:.3f}, {md[2]:.3f}] | "
                   f"{s[0]:.1f} [{s[1]:.1f}, {s[2]:.1f}] | {l[0]:.1f} [{l[1]:.1f}, {l[2]:.1f}] |")
    return out


def _spearman(a, b) -> float:
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def b2(rows: pl.DataFrame) -> tuple[list[str], list[dict]]:
    out, res = [], []
    for b in BUCKETS:
        for s in SIGNALS:
            g = rows.filter((pl.col("bucket") == b) & pl.col(s).is_not_null() & pl.col(s).is_finite())
            g = g.with_columns(q=((pl.col(s).rank("ordinal") - 1) * 5 // g.height).cast(pl.Int32))
            qs = [g.filter(pl.col("q") == q) for q in range(5)]
            sh, lo = [_ci(x, "short_pnl") for x in qs], [_ci(x, "long_pnl") for x in qs]
            rho = _spearman(range(5), [x[0] for x in sh])
            res.append({"bucket": b, "signal": s, "rho": rho, "top": sh[4], "bottom": sh[0], "bottom_long": lo[0],
                        "n": g.height})
            out.append(f"| {b} | {s} | {g.height} | " + " | ".join(f"{x[0]:.1f} [{x[1]:.1f}, {x[2]:.1f}]" for x in sh)
                       + f" | {rho:.2f} | {lo[0][0]:.1f} [{lo[0][1]:.1f}, {lo[0][2]:.1f}] |")
    hdr = ["| bucket | signal | n | Q1 (low) | Q2 | Q3 | Q4 | Q5 (high) | Spearman | Q1 long proxy |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    return hdr + out, res


# held=False rows: the day the market learnt the meeting would not happen (sources in events.csv rows)
VOIDED = {(date(2020, 3, 18), "fomc"): date(2020, 3, 15),  # cancelled with the Sunday emergency cut
          (date(2020, 4, 3), "rbi"): date(2020, 3, 27),    # brought forward: surprise decision 27 Mar
          (date(2020, 6, 5), "rbi"): date(2020, 5, 22),    # brought forward: surprise decision 22 May
          (date(2020, 10, 1), "rbi"): date(2020, 9, 28)}   # postponed


def known_events(trading_days: list[date]) -> pl.DataFrame:
    """Scheduled events with `void` = date a held=False event was publicly called off. Known at d iff
    (announced is null or <= d) and (void is null or d < void): an ex-ante calendar still shows them before that."""
    ev = events.load().filter(pl.col("scheduled"))
    ev = ev.with_columns(void=pl.Series([VOIDED[(d, t)] if not h else None
                                         for d, t, h in ev.select("date", "type", "held").iter_rows()], dtype=pl.Date))
    return events.with_session(ev, trading_days).drop_nulls("session").filter(pl.col("session").is_between(*DEV))


def _known(d: date, announced: date | None, void: date | None) -> bool:
    return (announced is None or announced <= d) and (void is None or d < void)


def b3_expiries(rows: pl.DataFrame, ev: pl.DataFrame) -> tuple[list[str], dict]:
    evl = list(ev.select("session", "announced", "void").iter_rows())

    def has(d, last):
        return any(d < s <= last and _known(d, a, v) for s, a, v in evl)

    rows = rows.with_columns(event=pl.Series([has(d, l) for d, l in zip(rows["date"], rows["last_session"])]))
    out = ["| bucket | event in life | n rows | short proxy pts [98.3% CI] | long proxy pts [98.3% CI] |",
           "|---|---|---|---|---|"]
    res = {}
    for b in BUCKETS:
        for e in (True, False):
            g = rows.filter((pl.col("bucket") == b) & (pl.col("event") == e))
            s, l = _ci(g, "short_pnl"), _ci(g, "long_pnl")
            res[(b, e)] = (s, l)
            out.append(f"| {b} | {e} | {g.height} | {s[0]:.1f} [{s[1]:.1f}, {s[2]:.1f}] | {l[0]:.1f} [{l[1]:.1f}, {l[2]:.1f}] |")
    return out, res


def one_day(surf: pl.DataFrame, opts: pl.DataFrame, p: date, s: date) -> dict | None:
    """ATM straddle of the nearest expiry > s, entry close p, exit close s."""
    c = surf.filter((pl.col("date") == p) & (pl.col("expiry") > s)).sort("expiry")
    if c.is_empty():
        return None
    r = c.row(0, named=True)
    x = opts.filter((pl.col("date") == s) & (pl.col("expiry") == r["expiry"]) & (pl.col("strike") == r["atm_k"])
                    & (pl.col("contracts") > 0))
    if x.height != 2:
        return None
    ex = float(x["close"].sum())
    en = r["straddle"]
    return {"p": p, "s": s, "expiry": r["expiry"],
            "short": en - ex - 4 * SLIP - fee_pts(p, r["expiry"], en, ex, True),
            "long": ex - en - 4 * SLIP - fee_pts(p, r["expiry"], en, ex, False)}


def b3_one_day(surf: pl.DataFrame, opts: pl.DataFrame, ev: pl.DataFrame, days: list[date]) -> tuple[list[str], dict]:
    have = set(opts["date"].unique().to_list())
    prev = {s: days[days.index(s) - 1] for s in ev["session"].unique().to_list() if days.index(s) > 0}
    kn = ev.filter(pl.Series([bool(prev.get(s)) and _known(prev[s], a, v)
                              for s, a, v in ev.select("session", "announced", "void").iter_rows()]))
    known = set(kn["session"].to_list())
    tmap = dict(kn.group_by("session").agg(pl.col("type").unique().sort().str.join("+")).iter_rows())
    res_e, res_n, dropped = [], [], [0, 0]
    for i in range(1, len(days)):
        p, s = days[i - 1], days[i]
        if not (DEV[0] <= p and s <= DEV[1]) or p not in have or s not in have:
            continue
        r = one_day(surf, opts, p, s)
        if r:
            (res_e if s in known else res_n).append({**r, "type": tmap.get(s, "")})
        else:  # no straddle at p, or an ATM leg untraded at s (exit-day information: count it)
            dropped[s in known] += 1
    e, n = pl.DataFrame(res_e), pl.DataFrame(res_n)
    out = ["| set | n | short proxy pts [98.3% CI] | long proxy pts [98.3% CI] |", "|---|---|---|---|"]
    res = {}

    def line(name, g):
        x = g["s"].cast(pl.Int32).to_numpy()
        sh, lo = cluster_ci(g["short"].to_numpy(), x), cluster_ci(g["long"].to_numpy(), x)
        res[name] = (g.height, sh, lo)
        out.append(f"| {name} | {g.height} | {sh[0]:.1f} [{sh[1]:.1f}, {sh[2]:.1f}] | {lo[0]:.1f} [{lo[1]:.1f}, {lo[2]:.1f}] |")

    line("event sessions, pooled", e)
    for t in ("rbi", "fomc", "budget", "election"):
        g = e.filter(pl.col("type").str.contains(t))
        if g.height >= 2:
            line(f"  contains {t}", g)
    line("pooled ex-FOMC-only", e.filter(pl.col("type") != "fomc"))
    line("non-event sessions", n)
    out.append(f"\nPairs dropped (no entry straddle or an ATM leg untraded at exit): {dropped[1]} event, {dropped[0]} non-event")
    return out, res


def main() -> None:
    idx = rv.load().filter(pl.col("date") <= DEV[1])
    days = idx["date"].to_list()
    surf = pl.read_parquet(SURFACE)
    rows = build_rows(surf, idx)
    opts = bhavcopy.load(*DEV).select("date", "expiry", "strike", "opt_type", "close", "settle", "contracts")
    # sanity: index close vs bhavcopy index settle (from 2020-02-06 the expiring series' settle is the index)
    chk = (opts.filter((pl.col("date") == pl.col("expiry")) & (pl.col("settle") > 1000))
           .group_by("date").agg(pl.col("settle").mode().first()).join(idx.select("date", "close"), on="date"))
    print(f"S_T check: {chk.height} expiries, max |close - settle| = {(chk['close'] - chk['settle']).abs().max():.2f} pts\n")
    rows = rows.filter(pl.col("bucket").is_not_null())
    print("## B1 unconditional\n", *b1(rows), sep="\n")
    t2, r2 = b2(rows)
    print("\n## B2 quintiles (short proxy pts, mean [98.3% CI])\n", *t2, sep="\n")
    ev = known_events(days)
    t3, r3 = b3_expiries(rows, ev)
    print("\n## B3a expiries with a known event in their life\n", *t3, sep="\n")
    t4, r4 = b3_one_day(surf, opts, ev, days)
    print("\n## B3b 1-day straddle across the event session\n", *t4, sep="\n")

    print("\n## Gates")
    h1 = [r for r in r2 if r["top"][1] > 0 and r["rho"] > 0.7]
    print(f"H1: {'PASS' if h1 else 'FAIL'} - top quintile CI lower > 0 and Spearman > 0.7: "
          + (", ".join(f"{r['bucket']}/{r['signal']}" for r in h1) or "none"))
    h3q = [r for r in r2 if r["bottom"][2] < 0]
    h3e = [k for k, (s, _) in r3.items() if s[2] < 0]
    print(f"H3 (as written: short proxy CI upper < 0): {'PASS' if h3q or h3e else 'FAIL'} - quintiles: "
          + (", ".join(f"{r['bucket']}/{r['signal']} (long proxy {r['bottom_long'][0]:.1f} "
                       f"[{r['bottom_long'][1]:.1f}, {r['bottom_long'][2]:.1f}])" for r in h3q) or "none")
          + "; event buckets: " + (", ".join(map(str, h3e)) or "none"))
    n, sh, _ = r4["event sessions, pooled"]
    h2 = n >= 40 and (sh[1] > 0 or sh[2] < 0)
    print(f"H2: {'PASS' if h2 else 'FAIL'} - pooled n={n}, short CI [{sh[1]:.1f}, {sh[2]:.1f}]")


if __name__ == "__main__":
    main()
