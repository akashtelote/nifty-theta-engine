"""E1: index-inclusion drift, DEV only (plan 20261017-equity-futures-hypotheses, E1 + rules 6-8, A2 amendment 3).

Events (data/index_changes/changes.parquet, A4): scheduled semi-annual review rows (kind scheduled or
criteria_revision). One event per stock per review (half-year of the effective date), filed under the highest-priority
index it moves in (Nifty 50 > Next 50 > Midcap 150/100 > Nifty 500), with that index's side: a Next 50 -> Nifty 50
move is one Nifty 50 add (its Next 50 removal is not counted); read the same way, a Nifty 50 -> Next 50 move is one
Nifty 50 removal (the plan names only the upward case; the report counts these demotions).
Trade: buy at the open of the first session after the announcement date (announcement times are not in A4; plan:
announcements come after hours), sell at the close of the last session before the effective date. Slippage 0.25% per
side on top of the dated fees (config.settings.equity_delivery_fees). Prices are A2-adjusted (adj); a window
(t0, t1] with ca_flag_n[t1] > ca_flag_n[t0] is dropped (amendment 3).
Rule 7: no EQ/BE row for 5 consecutive bhavcopy sessions -> exit at last close -30% (no slippage on top), booked on
the 5th missing session; a stock missing on the exit session is sold at its next close (else rule 7).
Abnormal = stock minus Nifty 500 price index, both entry-session open -> exit-session close, no dividends.
Per-event notional = Rs2L / tradable adds in that review (flat fees bite as a share of the slot). Tax is in the
portfolio report only (plan: per-event gate is "after costs").
Gate (DEV, announced 2010-01-01..2018-12-31): n >= 40 adds and the 98.75% (two-sided) bootstrap CI lower bound of the
mean net abnormal return > 0; the bootstrap resamples whole reviews. OOS is not computed here.
Secondary (reported, never gates): entry at the announcement-day close; removals (cash-price abnormal return only:
the stock-futures short needs FUTSTK data, which A5 does not load); ad hoc adds (one event per announcement date).
Run: uv run python -m research.e1_inclusion   -> data/e1/dev_report.txt, data/e1/dev_events.parquet
"""
from __future__ import annotations

import random
from bisect import bisect_left, bisect_right
from datetime import date
from math import floor
from pathlib import Path

import polars as pl

from config.settings import equity_delivery_fees
from research import corp_actions, stock_id

CHANGES = Path("data/index_changes/changes.parquet")
BENCH = Path("data/benchmarks/price_nifty_500.parquet")
OUT = Path("data/e1")
MIDCAP150_FROM = date(2016, 9, 30)  # first Midcap 150 effective date in A4; Midcap 100 counts only before it
PRIORITY = {"NIFTY50": 0, "NEXT50": 1, "MIDCAP150": 2, "MIDCAP100": 2, "NIFTY500": 3}
REVIEW_KINDS = ("scheduled", "criteria_revision")
DEV = (date(2010, 1, 1), date(2018, 12, 31))
CAPITAL = 200_000.0
SLIP = 0.0025
HAIRCUT = 0.30
MISSING = 5
MIN_N = 40
CONF = 0.9875
BOOT = 10_000
SEED = 20261017


def events(ch: pl.DataFrame, scheduled: bool = True) -> pl.DataFrame:
    """One row per (review, symbol): the highest-priority index row, adds before removes on a tie.
    review = '<year>H<1|2>' of the effective date for scheduled reviews, the announcement date for ad hoc."""
    kinds = REVIEW_KINDS if scheduled else ("ad_hoc",)
    review = (pl.col("effective").dt.year().cast(pl.String) + "H"
              + pl.when(pl.col("effective").dt.month() <= 6).then(pl.lit("1")).otherwise(pl.lit("2"))
              if scheduled else pl.col("announced").cast(pl.String))
    ev = (ch.filter(pl.col("kind").is_in(kinds) & pl.col("valid")
                    & ~((pl.col("index") == "MIDCAP100") & (pl.col("effective") >= MIDCAP150_FROM)))
          .with_columns(review=review, pri=pl.col("index").replace_strict(PRIORITY, return_dtype=pl.Int8),
                        rem=pl.col("side") != "add"))
    sides = ev.group_by("review", "symbol").agg(n_index=pl.len(), sides=pl.col("side").n_unique())
    return (ev.sort("pri", "rem", "announced", "index", maintain_order=True).group_by("review", "symbol", maintain_order=True).first()
            .join(sides, on=["review", "symbol"]).drop("pri", "rem").sort("announced", "index", "symbol"))


def windows(ev: pl.DataFrame, cal: list[date]) -> pl.DataFrame:
    """t0 = first session after `announced`, t1 = last session before `effective`, ta = last session on/before
    `announced` (secondary close entry). Null when off the calendar."""
    def at(i: int) -> date | None:
        return cal[i] if 0 <= i < len(cal) else None
    return ev.with_columns(
        t0=pl.col("announced").map_elements(lambda d: at(bisect_right(cal, d)), return_dtype=pl.Date),
        t1=pl.col("effective").map_elements(lambda d: at(bisect_left(cal, d) - 1), return_dtype=pl.Date),
        ta=pl.col("announced").map_elements(lambda d: at(bisect_right(cal, d) - 1), return_dtype=pl.Date))


def hold(px: dict, cal: list[date], d0: date, d1: date, at_close: bool = False) -> dict | str:
    """Enter at d0 (open, or close if at_close), exit at the close of d1, or at the next close if the stock has no
    row on d1, or under rule 7. px: date -> (open, close, adj, ca_flag_n) of one perm_id. Trade or drop reason."""
    if d0 not in px:
        return "no entry row"
    o, c, a, n0 = px[d0]
    raw = c if at_close else o
    t = {"entry_raw": raw, "entry": raw * a, "ca_n0": n0}
    last, n1, miss, i = c * a, n0, 0, bisect_left(cal, d0)
    while cal[i] < d1 or cal[i] not in px:
        i += 1
        if i == len(cal):
            return "past end of data"
        if cal[i] in px:
            _, c, a, n1 = px[cal[i]]
            last, miss = c * a, 0
        else:
            miss += 1
            if miss == MISSING:
                return t | {"exit": last * (1 - HAIRCUT), "exit_date": cal[i], "forced": True, "ca_n1": n1}
    return t | {"exit": last, "exit_date": cal[i], "forced": False, "ca_n1": n1}


def trades(ev: pl.DataFrame, rows: pl.DataFrame, cal: list[date], bench: dict, at_close: bool = False) -> pl.DataFrame:
    """Gross trade per event, with `drop` naming why an event has no usable window (null = kept)."""
    ids = (ev.select("review", "symbol", "t0").filter(pl.col("t0").is_not_null()).sort("t0")
           .join_asof(rows.select("date", "symbol", "perm_id").sort("date"), left_on="t0", right_on="date",
                      by="symbol", strategy="backward").select("review", "symbol", "perm_id"))
    ev = ev.join(ids, on=["review", "symbol"], how="left")
    pids = ev["perm_id"].drop_nulls().unique().to_list()
    px: dict[str, dict] = {}
    for r in rows.filter(pl.col("perm_id").is_in(pids)).select("perm_id", "date", "open", "close", "adj",
                                                                "ca_flag_n").iter_rows():
        px.setdefault(r[0], {})[r[1]] = r[2:]
    out = []
    for e in ev.iter_rows(named=True):
        d0 = e["ta"] if at_close else e["t0"]
        t: dict | str
        if e["perm_id"] is None:
            t = "symbol not found"
        elif d0 is None or e["t1"] is None or d0 > e["t1"]:
            t = "no window"
        else:
            t = hold(px[e["perm_id"]], cal, d0, e["t1"], at_close)
        if isinstance(t, dict):
            b0, b1 = bench.get(d0), bench.get(t["exit_date"])
            if t["ca_n1"] > t["ca_n0"]:
                t = "ca_flag in window"
            elif b0 is None or b1 is None:
                t = "no benchmark"
            else:
                t |= {"bench_r": b1[1] / (b0[1] if at_close else b0[0]) - 1}
        out.append(e | {"entry_date": d0, "drop": None} | (t if isinstance(t, dict) else {"drop": t}))
    return pl.DataFrame(out, infer_schema_length=None)


def costed(t: pl.DataFrame, capital: float = CAPITAL) -> pl.DataFrame:
    """Kept trades + slot notional (capital / kept events in the review), gross and net (slippage + fees) returns."""
    k = t.filter(pl.col("drop").is_null()).with_columns(slot=capital / pl.len().over("review"))
    net, var = [], []
    for r in k.iter_rows(named=True):
        gross = r["exit"] / r["entry"]
        proceeds = r["slot"] * gross * (1 if r["forced"] else 1 - SLIP) / (1 + SLIP)
        fees = equity_delivery_fees(r["slot"], proceeds, r["entry_date"], r["exit_date"])
        net.append((proceeds - fees) / r["slot"] - 1)
        # fees = flat rupees + linear in value, so doubling both legs isolates the linear (percentage) part
        lin = equity_delivery_fees(2 * r["slot"], 2 * proceeds, r["entry_date"], r["exit_date"]) - fees
        var.append((proceeds - lin) / r["slot"] - 1)
    return k.with_columns(stock_r=pl.col("exit") / pl.col("entry") - 1, net_r=pl.Series(net, dtype=pl.Float64),
                          var_r=pl.Series(var, dtype=pl.Float64)) \
        .with_columns(abn_gross=pl.col("stock_r") - pl.col("bench_r"), abn=pl.col("net_r") - pl.col("bench_r"),
                      abn_var=pl.col("var_r") - pl.col("bench_r"))


def bootstrap(k: pl.DataFrame, col: str = "abn") -> tuple[float, float]:
    """Two-sided CONF interval of the event-weighted mean, resampling whole reviews (seeded)."""
    g = k.group_by("review").agg(s=pl.col(col).sum(), n=pl.len())
    s, n = g["s"].to_list(), g["n"].to_list()
    rng, m = random.Random(SEED), len(s)
    means = sorted(sum(s[j] for j in ix) / sum(n[j] for j in ix)
                   for ix in ([rng.randrange(m) for _ in range(m)] for _ in range(BOOT)))
    q = (1 - CONF) / 2
    return means[int(q * BOOT)], means[min(BOOT - 1, int((1 - q) * BOOT))]


def stcg(on: date) -> float:
    """Equity STCG rate incl. cess (plan rule 6; surcharge excluded)."""
    rate = 0.20 if on >= date(2024, 7, 23) else 0.15
    return rate * (1.04 if on >= date(2018, 4, 1) else 1.03)


def portfolio(k: pl.DataFrame) -> tuple[pl.DataFrame, float]:
    """Each review splits a fixed Rs2L equally across its kept adds in whole shares (a stock priced above its slot
    gets 0, left in cash); cash earns 0 between reviews. STCG on the review's net gain, no loss carry-forward.
    Returns per-review rows and the summed after-tax P&L."""
    total, per = 0.0, []
    for (rv,), g in k.sort("entry_date").group_by("review", maintain_order=True):
        slot, gain, last = CAPITAL / g.height, 0.0, max(g["exit_date"])
        for r in g.iter_rows(named=True):
            sh = floor(slot / (r["entry_raw"] * (1 + SLIP)))
            if sh == 0:
                continue
            cost = sh * r["entry_raw"] * (1 + SLIP)
            proceeds = sh * r["entry_raw"] * r["exit"] / r["entry"] * (1 if r["forced"] else 1 - SLIP)
            gain += proceeds - cost - equity_delivery_fees(cost, proceeds, r["entry_date"], r["exit_date"])
        tax = max(gain, 0.0) * stcg(last)
        per.append({"review": rv, "events": g.height, "pnl_after_tax": gain - tax,
                    "ret": (gain - tax) / CAPITAL})
        total += gain - tax
    return pl.DataFrame(per), total


def summary(k: pl.DataFrame, label: str) -> list[str]:
    if k.is_empty():
        return [f"{label}: no events"]
    nan = (float("nan"), float("nan"))
    lo, hi = bootstrap(k) if k["review"].n_unique() > 1 else nan
    glo, ghi = bootstrap(k, "abn_gross") if k["review"].n_unique() > 1 else nan
    vlo, vhi = bootstrap(k, "abn_var") if k["review"].n_unique() > 1 else nan
    rv = k.group_by("review").agg(pl.col("abn").mean())
    return [f"{label}: n={k.height} reviews={k['review'].n_unique()} mean gross abn={k['abn_gross'].mean():+.4%} "
            f"mean net abn={k['abn'].mean():+.4%} median net abn={k['abn'].median():+.4%}",
            f"  {CONF:.2%} review-bootstrap CI of mean net abn: [{lo:+.4%}, {hi:+.4%}]; "
            f"reviews with positive mean: {(rv['abn'] > 0).sum()}/{rv.height}; forced exits: {k['forced'].sum()}",
            f"  context: gross abn CI [{glo:+.4%}, {ghi:+.4%}]; net of slippage + percentage fees only (no flat Rs "
            f"brokerage / DP) mean {k['abn_var'].mean():+.4%} CI [{vlo:+.4%}, {vhi:+.4%}]"]


def drops(t: pl.DataFrame, label: str) -> str:
    d = t.filter(pl.col("drop").is_not_null()).group_by("drop").len().sort("drop")
    return f"{label} dropped: " + (", ".join(f"{a}={b}" for a, b in d.iter_rows()) or "none")


def run() -> str:
    ch = pl.read_parquet(CHANGES).filter(pl.col("announced").is_between(*DEV))  # DEV only: OOS rows never loaded
    a = corp_actions.build()
    rows = a["rows"].filter(pl.col("date") <= date(2019, 6, 30))  # DEV windows end by 2019-03; rule 7 margin
    cal = [d for d in stock_id.sessions(rows.select("date")) if d <= date(2019, 6, 30)]
    bench = {d: (o, c) for d, o, c in pl.read_parquet(BENCH).select("date", "open", "close").iter_rows()}
    ev = windows(events(ch), cal)
    adds, rems = ev.filter(pl.col("side") == "add"), ev.filter(pl.col("side") == "remove")
    t = trades(adds, rows, cal, bench)
    k = costed(t)
    lo, _ = bootstrap(k) if k.height else (float("nan"), None)
    verdict = "PASS" if k.height >= MIN_N and lo > 0 else "FAIL"
    port, pnl = portfolio(k)
    tc = trades(adds, rows, cal, bench, at_close=True)
    tr = trades(rems, rows, cal, bench)
    ah = windows(events(ch, scheduled=False), cal).filter(pl.col("side") == "add")
    ta = trades(ah, rows, cal, bench)
    multi = ev.filter(pl.col("n_index") > 1)
    demoted = multi.filter((pl.col("side") == "remove") & (pl.col("sides") > 1))
    lines = [
        f"E1 index-inclusion drift - DEV (announced {DEV[0]}..{DEV[1]}). Generated {date.today()}.",
        f"GATE: n >= {MIN_N} and {CONF:.2%} CI lower bound of mean net abnormal > 0  ->  {verdict}",
        *summary(k, "Scheduled adds (gated)"),
        drops(t, "  scheduled adds"),
        f"  events by filed index: " + ", ".join(f"{i}={n}" for i, n in
                                                  k.group_by("index").len().sort("index").iter_rows()),
        f"  stocks in >1 index row of a review: {multi.height} (moves with an add and a removal: "
        f"{multi.filter(pl.col('sides') > 1).height}, of which filed as removals / demotions: {demoted.height})",
        "",
        f"Portfolio (Rs{CAPITAL:,.0f} per review, whole shares, cash 0 between reviews, STCG + cess, not gated): "
        f"summed P&L Rs{pnl:,.0f} over {port.height} reviews (mean {port['ret'].mean():+.2%} per review); "
        f"reviews positive after tax: {(port['ret'] > 0).sum()}/{port.height}",
        *(f"  {r['review']}: events={r['events']} pnl=Rs{r['pnl_after_tax']:,.0f} ret={r['ret']:+.2%}"
          for r in port.iter_rows(named=True)),
        "",
        "Secondary (reported only):",
        *summary(costed(tc), "  entry at announcement-day close"),
        drops(tc, "  close-entry"),
        *summary(costed(tr), "  removals (cash price, long-side sign; a short gains when this is negative)"),
        drops(tr, "  removals"),
        "  removals via stock futures: not run (FUTSTK not loaded; A5 keeps FUTIDX only)",
        *summary(costed(ta), "  ad hoc adds"),
        drops(ta, "  ad hoc adds"),
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    k.write_parquet(OUT / "dev_events.parquet")
    text = "\n".join(lines) + "\n"
    (OUT / "dev_report.txt").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(run())
