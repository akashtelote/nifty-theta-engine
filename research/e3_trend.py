"""E3 - time-series trend on NSE index + MCX futures at Rs20L (plan docs/plans/20261017-equity-futures-hypotheses-plan.md).

Step 1 is the feasibility pre-gate (no P&L is read); `dev` then runs the DEV P&L and gates 1-5 (never OOS): per market per day, is 1 lot of the traded product within
2x the target risk 15%/sqrt(N) x capital? Data: A5 data/futures (research/futures.py).

    PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run --extra research python -m research.e3_trend pregate|dev
"""
from __future__ import annotations

import math
import sys
from datetime import date

import polars as pl

from config.settings import futures_fees
from research.benchmarks import TBILL_PATH
from research.e2_momentum import CONF, stationary_ci
from research.futures import MCX_SPEC, ROOT, TICKS, load

CAPITAL = 2_000_000
TARGET = 0.15
CAP_X = 2.0
FLOOR = 5e7  # Rs5 cr median product turnover over the prior 60 sessions
LOOKBACK = 60
JOIN = 252
HALF_LIFE = 60
LOOKS = (63, 126, 252)
SLIP_PCT = 0.0002
MARGIN = {"NSE": 0.12, "MCX": 0.10}  # SPAN estimate, share of notional
MARGIN_CAP = 0.60
TICK_EXTRA = {"GOLDTEN": 1.0, "SILVER100": 1.0, "COPPERM": 0.05}  # outside MCX_SPEC; current MCX specs
# market: (exchange, reference product, products); products outside MCX_SPEC get value/(lots*close) as mult
MARKETS = {
    "NIFTY": ("NSE", "NIFTY", ["NIFTY"]),
    "BANKNIFTY": ("NSE", "BANKNIFTY", ["BANKNIFTY"]),
    "GOLD": ("MCX", "GOLD", ["GOLD", "GOLDM", "GOLDGUINEA", "GOLDPETAL", "GOLDTEN"]),
    "SILVER": ("MCX", "SILVER", ["SILVER", "SILVERM", "SILVERMIC", "SILVER100"]),
    "CRUDEOIL": ("MCX", "CRUDEOIL", ["CRUDEOIL", "CRUDEOILM"]),
    "NATURALGAS": ("MCX", "NATURALGAS", ["NATURALGAS", "NATGASMINI"]),
    "COPPER": ("MCX", "COPPER", ["COPPER", "COPPERM"]),
    "ZINC": ("MCX", "ZINC", ["ZINC", "ZINCMINI"]),
    "ALUMINIUM": ("MCX", "ALUMINIUM", ["ALUMINIUM", "ALUMINI"]),
}
DEV = (date(2005, 1, 1), date(2015, 12, 31))
LAST12 = (date(2025, 10, 1), date(2026, 9, 30))


def products() -> pl.DataFrame:
    """Per product and session: held contract close, mult, daily % return, product turnover, sessions listed."""
    syms = {p: m for m, (_, _, ps) in MARKETS.items() for p in ps}
    raw = pl.concat([load("nse"), load("mcx")], how="diagonal").filter(pl.col("symbol").is_in(list(syms)))
    raw = raw.with_columns(pl.col("mult").fill_null(  # ponytail: implied lot from traded rows, per contract
        (pl.col("value") / (pl.col("lots") * pl.col("close"))).filter(pl.col("lots") > 0).median()
        .over("symbol", "expiry").round(3)))
    cal = raw.select("exch", "date").unique()
    tv = (raw.group_by("symbol", "date").agg(tv=pl.col("value").filter(pl.col("lots") > 0).sum()))
    first = raw.group_by("symbol").agg(first=pl.col("date").min())
    exch = raw.group_by("symbol").agg(pl.col("exch").first())
    # every exchange session from the product's first listing; untraded / unlisted sessions count as zero turnover
    grid = (exch.join(first, on="symbol").join(cal, on="exch").filter(pl.col("date") >= pl.col("first"))
            .join(tv, on=["symbol", "date"], how="left").with_columns(pl.col("tv").fill_null(0.0)).sort("symbol", "date")
            .with_columns(listed=pl.int_range(pl.len()).over("symbol"),  # sessions before today
                          med=pl.col("tv").shift(1).rolling_median(LOOKBACK).over("symbol")))
    cont = pl.read_parquet(ROOT / "continuous.parquet").filter(pl.col("symbol").is_in(list(syms))).sort("symbol", "date")
    # every contract's fill prices: untraded days at settle (as futures.continuous); open falls back to that close
    close = pl.when(pl.col("lots") > 0).then(pl.col("close")).otherwise(pl.coalesce("settle", "close"))
    px = raw.select("exch", "symbol", "expiry", "date", "mult", close=close).with_columns(
        open=pl.when((raw["lots"] > 0) & (raw["open"] > 0)).then(raw["open"]).otherwise(pl.col("close")))
    px = px.filter(pl.col("close") > 0)  # 43 legacy NSE untraded rows carry settle 0: treat as unquoted
    # held contract's own close-to-close move (on a roll day: the new contract's, not the back-adjusted gap day)
    own = px.sort("symbol", "expiry", "date").select(
        "symbol", "expiry", "date", ret=(pl.col("close") / pl.col("close").shift(1) - 1).over("symbol", "expiry"))
    cont = cont.join(own, on=["symbol", "expiry", "date"], how="left")
    lam = 1 - 0.5 ** (1 / HALF_LIFE)
    # annualise by the product's own sessions/year (MCX traded Saturdays to 2013: ~306), trailing 365 days
    ny = cont.rolling("date", period="365d", group_by="symbol").agg(ny=pl.len())
    cont = (cont.join(ny, on=["symbol", "date"]).with_columns(
        span=pl.min_horizontal((pl.col("date") - pl.col("date").min().over("symbol")).dt.total_days() + 1, 365))
        .with_columns(vol=(pl.col("ret").pow(2).ewm_mean(alpha=lam, ignore_nulls=True).over("symbol")
                           * pl.col("ny") * 365 / pl.col("span")).sqrt()).drop("ny", "span"))
    mult = raw.select("symbol", "date", "expiry", "mult")
    out = (cont.join(mult, on=["symbol", "date", "expiry"], how="left")
           .join(grid.select("symbol", "date", "listed", "med"), on=["symbol", "date"], how="left")
           .with_columns(market=pl.col("symbol").replace_strict(syms), notional=pl.col("close") * pl.col("mult")))
    return out, px


def choose(p: pl.DataFrame) -> pl.DataFrame:
    """Per market and session: traded product (smallest lot notional clearing the floor, re-checked at reference-product
    rolls / join), live flag, 1-lot annual risk."""
    rows = []
    for m, (_, ref, _) in MARKETS.items():
        g = p.filter(pl.col("market") == m)
        r = g.filter(pl.col("symbol") == ref).sort("date").with_columns(n=pl.int_range(pl.len()))
        joined = r.filter(pl.col("n") >= JOIN)
        checks = set(joined.filter(pl.col("roll"))["date"]) | set(joined["date"].head(1))
        by_day = {d: grp for (d,), grp in g.group_by("date")}
        held = None
        for d in sorted(joined["date"]):
            day = by_day[d]
            if d in checks or (held is not None and held not in set(day["symbol"])):
                ok = day.filter((pl.col("listed") >= LOOKBACK) & (pl.col("med") >= FLOOR) & pl.col("notional").is_not_null())
                held = ok.sort("notional")["symbol"][0] if ok.height else None
            x = day.filter(pl.col("symbol") == held) if held else None
            if x is None or x.height == 0 or x["vol"][0] is None:
                rows.append((m, d, None, False, None, None))
                continue
            rows.append((m, d, held, True, x["notional"][0], x["notional"][0] * x["vol"][0]))
    return pl.DataFrame(rows, schema={"market": pl.Utf8, "date": pl.Date, "product": pl.Utf8, "live": pl.Boolean,
                                      "notional": pl.Float64, "risk": pl.Float64}, orient="row")


def live_n(c: pl.DataFrame) -> pl.DataFrame:
    """N on a date = markets live on their latest session up to that date (MCX and NSE calendars differ)."""
    cal = c.select("date").unique()
    st = (c.select("market").unique().join(cal, how="cross").join(c, on=["market", "date"], how="left")
          .sort("market", "date").with_columns(pl.col("live").forward_fill().over("market").fill_null(False)))
    return st.group_by("date").agg(N=pl.col("live").sum())


def at_current_specs(c: pl.DataFrame, p: pl.DataFrame, hi: date) -> pl.DataFrame:
    """Rescale each product's notional / 1-lot risk to its lot size on its last session up to hi."""
    m = p.select(pl.col("symbol").alias("product"), "date", "mult")
    cur = m.filter(pl.col("date") <= hi).drop_nulls("mult").sort("date").group_by("product").agg(cur=pl.col("mult").last())
    k = pl.col("cur") / pl.col("mult")
    return (c.join(m, on=["product", "date"], how="left").join(cur, on="product", how="left")
            .with_columns(notional=pl.col("notional") * k, risk=pl.col("risk") * k).drop("mult", "cur"))


def pregate(c: pl.DataFrame, lo: date, hi: date) -> tuple[bool, pl.DataFrame]:
    """>= half of live markets hold >= 1 lot within CAP_X x target on >= 80% of their live days in [lo, hi]."""
    w = (c.filter(pl.col("live") & pl.col("date").is_between(lo, hi)).join(live_n(c), on="date")
         .with_columns(cap=CAP_X * TARGET / pl.col("N").sqrt() * CAPITAL)
         .with_columns(ok=pl.col("risk") <= pl.col("cap")))
    t = (w.group_by("market").agg(days=pl.len(), share=pl.col("ok").mean(), N=pl.col("N").median(),
                                  risk_med=pl.col("risk").median(), cap_med=pl.col("cap").median(),
                                  products=pl.col("product").unique().sort().str.join("/"))
         .with_columns(holdable=pl.col("share") >= 0.8).sort("market"))
    return t.height > 0 and t["holdable"].sum() * 2 >= t.height, t


def tax_rate(fy: int) -> float:
    """Futures P&L as business income: 30% plus cess (plan: 30.6% to FY2006-07, 30.9% to FY2017-18, then 31.2%)."""
    return 0.306 if fy <= 2006 else 0.309 if fy <= 2017 else 0.312


def tick(exch: str, sym: str) -> float:
    return TICKS.get(exch) or MCX_SPEC.get(sym, (TICK_EXTRA.get(sym),))[0]


def rnd(x: float) -> int:
    """Half away from zero (Python's round() is banker's)."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def trade_ok(cur: int, tgt: int) -> bool:
    """Trade only when the target differs from the position by >= 1 lot and by >= 25% of it."""
    d = abs(tgt - cur)
    return d >= 1 and (cur == 0 or d >= 0.25 * abs(cur))


def target_lots(signal: float, n: int, risk: float | None) -> int:
    """signal x (TARGET/sqrt(N) x capital) / 1-lot annual risk, rounded; 0 if 1 lot > CAP_X x target risk."""
    if risk is None or not n:
        return 0
    tr = TARGET / math.sqrt(n) * CAPITAL
    return 0 if risk > CAP_X * tr else rnd(signal * tr / risk)


def order_cost(n: int, price: float, mult: float, sym: str, d: date, exch: str) -> float:
    """Fees (A7, dated) + slippage of 1 tick + SLIP_PCT of notional for an order of n lots (sign = side)."""
    v = abs(n) * mult * price
    return futures_fees(v, d, n > 0, exch) + abs(n) * mult * tick(exch, sym) + SLIP_PCT * v


def fy_tax(fy: int, pnl: float, cf: float) -> tuple[float, float]:
    """(tax, loss carried out) for FY fy's net futures P&L given business losses cf carried in."""
    net = pnl - cf
    return (tax_rate(fy) * net, 0.0) if net > 0 else (0.0, -net)


def signals(p: pl.DataFrame) -> pl.DataFrame:
    """Mean of sign(P_t - P_t-k), k in LOOKS, on the reference product's additive back-adjusted series."""
    out = []
    for m, (_, ref, _) in MARKETS.items():
        r = p.filter(pl.col("symbol") == ref).sort("date")
        s = sum((pl.col("adj_close") - pl.col("adj_close").shift(k)).sign() for k in LOOKS) / len(LOOKS)
        out.append(r.select(pl.lit(m).alias("market"), "date", signal=s))
    return pl.concat(out)


def simulate(c: pl.DataFrame, p: pl.DataFrame, px: pl.DataFrame, lo: date, hi: date) -> tuple[pl.DataFrame, dict]:
    """Daily NAV in [lo, hi]. Each session per market: mark the held contract to the open; at the open roll / switch
    product (product = the one chosen at the previous close) and fill any pending weekly order; mark to the close;
    then, on the market's last session of the ISO week, set the next open's order. FY tax on net P&L after business-loss
    carry-forward (8-year limit ignored) is paid on the first session of the next FY and at hi.
    ponytail: sizing uses fixed CAPITAL, not NAV; no interest is credited on collateral, so the return is the
    excess over T-bill under the usual fully-collateralised convention (stated in the report)."""
    c = (c.filter(pl.col("date").is_between(lo, hi)).join(live_n(c), on="date")
         .join(signals(p), on=["market", "date"], how="left"))
    cont = {(s, d): e for s, d, e in p.filter(pl.col("date") <= hi).select("symbol", "date", "expiry").iter_rows()}
    price = {(s, e, d): (o, cl, mu) for s, e, d, o, cl, mu in px.filter(pl.col("date").is_between(lo, hi))
             .select("symbol", "expiry", "date", "open", "close", "mult").iter_rows()}
    events: dict[date, list] = {}
    for (m,), g in c.sort("date").group_by("market", maintain_order=True):
        rs = list(g.iter_rows(named=True))
        for i, r in enumerate(rs):
            we = i + 1 == len(rs) or rs[i + 1]["date"].isocalendar()[:2] != r["date"].isocalendar()[:2]
            events.setdefault(r["date"], []).append((m, r, we))
    st = {m: {"lots": 0, "con": None, "last": None, "mult": None, "prod": None, "pend": None} for m in MARKETS}
    nav, fy, fy_pnl, cf, out = float(CAPITAL), None, 0.0, 0.0, []
    stats = {"orders": 0, "rolls": 0, "costs": 0.0, "tax": 0.0, "margin_days": 0, "stuck": 0}
    for d in sorted(events):
        f = d.year if d.month >= 4 else d.year - 1
        if fy is not None and f != fy:
            t, cf = fy_tax(fy, fy_pnl, cf)
            nav, stats["tax"], fy_pnl = nav - t, stats["tax"] + t, 0.0
        fy = f
        pnl = cost = 0.0
        for m, r, we in events[d]:
            s, x = st[m], MARKETS[m][0]
            con = s["con"]
            q = price.get((*con, d)) if con else None
            if q and s["lots"]:
                pnl += s["lots"] * s["mult"] * (q[0] - s["last"])
            if q:
                s["last"] = q[0]
            elif con and s["lots"] and con[1] < d:  # expired unquoted: close at the last mark
                cost += order_cost(-s["lots"], s["last"], s["mult"], con[0], d, x)
                s["lots"], stats["stuck"] = 0, stats["stuck"] + 1
            want = s["pend"] if s["pend"] is not None else s["lots"]
            new = (s["prod"], cont[(s["prod"], d)]) if (s["prod"], d) in cont else None
            qn = price.get((*new, d)) if new else None
            if new and new != con and qn and (q or not s["lots"]):  # roll or product switch at the open
                if s["lots"]:
                    if s["pend"] is None and new[0] != con[0]:  # product switch: keep the rupee exposure
                        want = rnd(s["lots"] * s["mult"] * q[0] / (qn[2] * qn[0]))
                    cost += order_cost(-s["lots"], q[0], s["mult"], con[0], d, x)
                    s["lots"], stats["rolls"] = 0, stats["rolls"] + 1
                s["con"], s["mult"], s["last"], con, q = new, qn[2], qn[0], new, qn
            fill = q and (s["prod"] is None or con[0] == s["prod"])  # never fill a new-product order in the old one
            if want != s["lots"] and fill:
                cost += order_cost(want - s["lots"], q[0], s["mult"], con[0], d, x)
                s["lots"], stats["orders"] = want, stats["orders"] + 1
            if fill or want == s["lots"]:
                s["pend"] = None
            if q:
                pnl += s["lots"] * s["mult"] * (q[1] - s["last"])
                s["last"] = q[1]
            # close: product for the next open, weekly order
            s["prod"] = r["product"] if r["live"] else None
            if not r["live"]:
                s["pend"] = 0 if s["lots"] else None
            elif we:
                t = target_lots(r["signal"] or 0.0, r["N"], r["risk"])
                cur = s["lots"] if not s["lots"] or con[0] == r["product"] else \
                    rnd(s["lots"] * s["mult"] * s["last"] / r["notional"])
                s["pend"] = t if trade_ok(cur, t) else None
        marg = sum(abs(v["lots"]) * v["mult"] * v["last"] * MARGIN[MARKETS[k][0]] for k, v in st.items() if v["lots"])
        nav += pnl - cost
        fy_pnl += pnl - cost
        stats["costs"] += cost
        stats["margin_days"] += marg > MARGIN_CAP * CAPITAL
        out.append((d, nav, pnl, cost, marg, sum(abs(v["lots"]) > 0 for v in st.values())))
    t, cf = fy_tax(fy, fy_pnl, cf)  # partial FY at hi, taxed now (conservative)
    stats["tax"] += t
    out[-1] = (out[-1][0], out[-1][1] - t, *out[-1][2:])
    return pl.DataFrame(out, schema=["date", "nav", "pnl", "cost", "margin", "held"], orient="row"), stats


def gates(nav: pl.DataFrame) -> dict:
    """Monthly gates 1-5 from the first month with a position (gate 6 needs OOS)."""
    t0 = nav.filter(pl.col("held") > 0)["date"].min()
    if t0 is None:
        raise ValueError("no position in the window: gates undefined")
    me = (nav.group_by(m=pl.col("date").dt.month_start()).agg(pl.col("nav").last()).sort("m")
          .with_columns(r=pl.col("nav") / pl.col("nav").shift(1, fill_value=float(CAPITAL)) - 1))
    me = me.filter(pl.col("m") >= date(t0.year, t0.month, 1))
    tri = (pl.read_parquet("data/benchmarks/tri_nifty_50.parquet").group_by(m=pl.col("date").dt.month_start())
           .agg(pl.col("tri").last()).sort("m").with_columns(b=pl.col("tri").pct_change()))
    tb = pl.read_parquet(TBILL_PATH).with_columns(m=pl.col("date").dt.month_start())
    j = me.join(tri.select("m", "b"), on="m").join(tb.select("m", "yield_pct"), on="m", how="left")
    r = j["r"].to_list()
    sd = j["r"].std()
    worst = j.drop_nulls("b").sort("b").head(math.ceil(0.1 * j.height))
    lo, hi = stationary_ci(r, block=3)
    peak = nav["nav"].cum_max()
    navs = [CAPITAL, *me["nav"].to_list()]
    yrs = me.height / 12
    out = {"months": j.height, "from": t0, "cagr": (navs[-1] / CAPITAL) ** (1 / yrs) - 1 if yrs else float("nan"),
           "sharpe": j["r"].mean() / sd * math.sqrt(12) if sd else float("nan"),
           "ci": (12 * lo, 12 * hi), "corr": j.select(pl.corr("r", "b")).item(),
           "worst_mean": worst["r"].mean(), "worst_n": worst.height, "mdd": (1 - nav["nav"] / peak).max(),
           "tbill": j["yield_pct"].mean() / 100}
    out["pass"] = {"1 Sharpe >= 0.5": out["sharpe"] >= 0.5, "2 excess CI lower > 0": out["ci"][0] > 0,
                   "3 corr Nifty50 TRI <= 0.3": out["corr"] <= 0.3, "4 worst-10% Nifty months mean > 0":
                   out["worst_mean"] > 0, "5 max drawdown <= 30%": out["mdd"] <= 0.30}
    return out


def main() -> None:
    cmd = sys.argv[1:2]
    if cmd not in (["pregate"], ["dev"]):
        sys.exit(__doc__)
    p, px = products()
    c = choose(p)
    if cmd == ["dev"]:
        ok, _ = pregate(c, *DEV)
        ok2, _ = pregate(at_current_specs(c, p, LAST12[1]), *LAST12)
        if not (ok and ok2):
            sys.exit("pre-gate FAIL: no P&L")
        nav, s = simulate(c, p, px, *DEV)
        g = gates(nav)
        md = s["margin_days"] / nav.height
        verdict = all(g["pass"].values()) and md <= 0.05
        lines = [f"E3 DEV {DEV[0]}..{DEV[1]} (Rs{CAPITAL / 1e5:.0f}L, weekly, net of A7 fees, slippage, rolls, FY tax) "
                 f"- generated {date.today()}",
                 "Return convention: futures P&L / NAV = excess over T-bill (no collateral interest credited).",
                 f"first position {g['from']}, {g['months']} months; final NAV Rs{nav['nav'][-1] / 1e5:.2f}L, "
                 f"CAGR {g['cagr']:.2%} (avg 91d T-bill {g['tbill']:.2%} for reference)",
                 f"orders {s['orders']} (incl. roll re-opens), rolls {s['rolls']}, costs Rs{s['costs'] / 1e5:.2f}L, tax Rs{s['tax'] / 1e5:.2f}L, "
                 f"expired-unquoted closes {s['stuck']}",
                 f"Sharpe {g['sharpe']:.2f}; annual excess {CONF:.2%} CI [{g['ci'][0]:.2%}, {g['ci'][1]:.2%}]; "
                 f"corr Nifty50 TRI {g['corr']:.2f}; worst {g['worst_n']} Nifty months mean {g['worst_mean']:.2%}; "
                 f"max DD {g['mdd']:.1%}; margin > {MARGIN_CAP:.0%} of capital on {md:.1%} of days (limit 5%)",
                 *(f"  {k}: {'PASS' if v else 'FAIL'}" for k, v in g["pass"].items()),
                 f"  margin feasibility: {'PASS' if md <= 0.05 else 'FAIL'}",
                 f"\nE3 DEV {'PASS' if verdict else 'FAIL'} (gate 6 needs OOS; not run)"]
        text = "\n".join(lines) + "\n"
        (ROOT / "e3_dev.txt").write_text(text, encoding="utf-8")
        nav.write_parquet(ROOT / "e3_dev_nav.parquet")
        print(text)
        return
    lines = [f"E3 feasibility pre-gate (Rs{CAPITAL / 1e5:.0f}L, 1 lot <= {CAP_X:g} x {TARGET:.0%}/sqrt(N) x capital "
             f"on >= 80% of live days, >= half of live markets; LAST12 at current lot sizes) - generated {date.today()}"]
    verdict = True
    for name, (lo, hi) in (("DEV", DEV), ("LAST12", LAST12)):
        ok, t = pregate(c if name == "DEV" else at_current_specs(c, p, hi), lo, hi)
        verdict &= ok
        lines += [f"\n{name} {lo}..{hi}: {'PASS' if ok else 'FAIL'} ({t['holdable'].sum()}/{t.height} markets holdable)",
                  *(f"  {r['market']:<10} {r['products']:<28} days {r['days']:>5}  holdable {r['share']:6.1%}  "
                    f"N~{r['N']:.0f}  1-lot risk Rs{r['risk_med'] / 1e5:6.2f}L vs cap Rs{r['cap_med'] / 1e5:5.2f}L"
                    for r in t.iter_rows(named=True))]
    lines.append(f"\nPRE-GATE {'PASS' if verdict else 'FAIL: E3 not implementable at Rs20L, no P&L computed'}")
    text = "\n".join(lines) + "\n"
    (ROOT / "e3_pregate.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
