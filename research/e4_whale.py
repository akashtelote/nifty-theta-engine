"""E4: institutional bulk/block "whale" signal, DEV only (plan 20261017-equity-futures-hypotheses, E4).

Version run: FALLBACK (A6 found no point-in-time shares-outstanding source, so the bot's 0.5%-of-shares rule cannot
be reproduced). Deals: data/deals/deals.parquet (A6). Institutional = client name (upper-cased) contains one of the
bot's frozen INSTITUTIONAL_KEYWORDS (core/smart_money.py @ 19d5216), substring match, buys minus sells.
Per stock-day:
  net   = sum of institutional bulk + block quantity, buys minus sells
  whale = net > 0 and at least one institutional client with a bulk-deal row that day whose own net (its buys minus
          its sells that day, over all its bulk and block rows in the stock) > 0. Block-only buy days are whale = 0.
  mirror sell = net < 0 and one such client with its own net < 0.
Events: a stock's trigger opens an event; further triggers within 20 sessions of the event's deal date belong to it.
Trade: buy at the open of the first session after the deal date (t0), sell at the close of the H-th session counting
t0 as the first (H = 20 primary). Exits, rule 7, ca_flag drops, fees, 0.25% slippage and the Nifty 500 price-index
abnormal return all come from E1 (research.e1_inclusion: hold / trades / costed). Notional per event = Rs2L split
over the events entering in the same calendar week (only fee drag depends on it).
Gate (DEV, deal dates 2010-01-01..2018-12-31): n >= 200 buy events and the 98.75% two-sided CI lower bound of the
mean net abnormal return > 0, by a moving block bootstrap over calendar weeks (block 8 weeks; every week in the span
counts, empty ones included). OOS is not computed here.
Secondary (reported only): H = 5 and 60; mirror sell events (long-side sign: a short gains when negative); signal
from block deals alone (net institutional block quantity > 0).
Run: uv run --extra research python -m research.e4_whale   -> data/e4/dev_report.txt, data/e4/dev_events.parquet
"""
from __future__ import annotations

import random
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from research import corp_actions, stock_id
from research.e1_inclusion import BENCH, CONF, SEED, costed, drops, trades

DEALS = Path("data/deals/deals.parquet")
OUT = Path("data/e4")
DEV = (date(2010, 1, 1), date(2018, 12, 31))
KEYWORDS = ["FUND", "CAPITAL", "BANK", "ADVISORS", "INSURANCE", "ASSET", "INVESTMENT", "PENSION"]  # frozen, 19d5216
CLUSTER = 20
HOLD = 20
MIN_N = 200
BLOCK_WEEKS = 8
BOOT = 10_000


def signals(deals: pl.DataFrame) -> pl.DataFrame:
    """Per (date, symbol) with institutional rows: buy / sell / block_buy flags (fallback rule)."""
    inst = deals.filter(pl.col("client").str.to_uppercase().str.contains("|".join(KEYWORDS))).with_columns(
        q=pl.when(pl.col("side") == "BUY").then(pl.col("qty")).otherwise(-pl.col("qty")))
    per_client = inst.group_by("date", "symbol", "client").agg(
        own=pl.col("q").sum(), bulk=(pl.col("kind") == "bulk").any())
    flags = per_client.group_by("date", "symbol").agg(
        net=pl.col("own").sum(),
        bulk_buyer=(pl.col("bulk") & (pl.col("own") > 0)).any(),
        bulk_seller=(pl.col("bulk") & (pl.col("own") < 0)).any())
    block = inst.filter(pl.col("kind") == "block").group_by("date", "symbol").agg(block_net=pl.col("q").sum())
    return (flags.join(block, on=["date", "symbol"], how="full", coalesce=True)
            .with_columns(buy=(pl.col("net") > 0) & pl.col("bulk_buyer"),
                          sell=(pl.col("net") < 0) & pl.col("bulk_seller"),
                          block_buy=pl.col("block_net").fill_null(0) > 0)
            .with_columns(pl.col("buy", "sell").fill_null(False)).sort("date", "symbol"))


def cluster(days: list[tuple[str, date]], cal: list[date], gap: int = CLUSTER) -> list[tuple[str, date]]:
    """(symbol, deal date) triggers -> event starts: a trigger within `gap` sessions of its symbol's current event
    start joins that event. Session position = number of sessions on/before the date."""
    last: dict[str, int] = {}
    out = []
    for sym, d in sorted(days, key=lambda x: (x[1], x[0])):
        i = bisect_right(cal, d)
        if sym in last and i - last[sym] <= gap:
            continue
        last[sym] = i
        out.append((sym, d))
    return out


def windows(ev: list[tuple[str, date]], cal: list[date], hold: int) -> pl.DataFrame:
    """t0 = first session after the deal date, t1 = t0 + hold - 1 sessions (null past the calendar)."""
    rows = []
    for sym, d in ev:
        i = bisect_right(cal, d)
        rows.append({"review": f"{sym}|{d}", "symbol": sym, "deal_date": d,
                     "t0": cal[i] if i < len(cal) else None,
                     "t1": cal[i + hold - 1] if i + hold - 1 < len(cal) else None})
    return pl.DataFrame(rows, schema={"review": pl.String, "symbol": pl.String, "deal_date": pl.Date,
                                      "t0": pl.Date, "t1": pl.Date})


def week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def block_bootstrap(k: pl.DataFrame, col: str = "abn", span: tuple[date, date] = DEV,
                    block: int = BLOCK_WEEKS, boot: int = BOOT) -> tuple[float, float]:
    """Two-sided CONF CI of the event-weighted mean: moving blocks of `block` consecutive calendar weeks (by entry
    week), drawn until the resample has as many weeks as the span. Seeded."""
    g = {w: (s, n) for w, s, n in k.group_by(pl.col("entry_date").map_elements(week, return_dtype=pl.Date).alias("w"))
         .agg(s=pl.col(col).sum(), n=pl.len()).iter_rows()}
    w0, w1 = week(min(span[0], min(g))), week(max(span[1], max(g)))
    weeks = [g.get(w0 + timedelta(weeks=j), (0.0, 0)) for j in range((w1 - w0).days // 7 + 1)]
    m, rng, means = len(weeks), random.Random(SEED), []
    block = min(block, m)
    for _ in range(boot):
        s = n = 0.0
        for _ in range(-(-m // block)):
            j = rng.randrange(m - block + 1)
            for ws, wn in weeks[j:j + block]:
                s, n = s + ws, n + wn
        if n:
            means.append(s / n)
    means.sort()
    q = (1 - CONF) / 2
    return means[int(q * len(means))], means[min(len(means) - 1, int((1 - q) * len(means)))]


def measure(ev, cal, rows, bench, hold: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(all trades with drop reasons, kept costed trades)."""
    t = trades(windows(ev, cal, hold), rows, cal, bench)
    k = t.filter(pl.col("drop").is_null())
    if k.is_empty():
        return t, k
    k = costed(k.with_columns(review=pl.col("entry_date").map_elements(week, return_dtype=pl.Date).cast(pl.String)))
    return t, k


def summary(k: pl.DataFrame, label: str) -> list[str]:
    if k.height < 2:
        return [f"{label}: n={k.height} (too few to summarise)"]
    lo, hi = block_bootstrap(k)
    glo, ghi = block_bootstrap(k, "abn_gross")
    yr = k.group_by(pl.col("entry_date").dt.year().alias("y")).agg(n=pl.len(), m=pl.col("abn").mean()).sort("y")
    return [f"{label}: n={k.height} mean gross abn={k['abn_gross'].mean():+.4%} mean net abn={k['abn'].mean():+.4%} "
            f"median net abn={k['abn'].median():+.4%} hit rate={(k['abn'] > 0).mean():.1%}",
            f"  {CONF:.2%} {BLOCK_WEEKS}-week moving-block CI of mean net abn: [{lo:+.4%}, {hi:+.4%}]; "
            f"gross [{glo:+.4%}, {ghi:+.4%}]; forced exits: {k['forced'].sum()}",
            "  by entry year: " + ", ".join(f"{y}: n={n} {m:+.2%}" for y, n, m in yr.iter_rows())]


def run() -> str:
    deals = pl.read_parquet(DEALS).filter(pl.col("date").is_between(*DEV))  # DEV only: OOS rows never loaded
    a = corp_actions.build()
    rows = a["rows"].filter(pl.col("date") <= date(2019, 6, 30))  # 60-session holds from 2018-12 end by 2019-04
    cal = [d for d in stock_id.sessions(rows.select("date")) if d <= date(2019, 6, 30)]
    bench = {d: (o, c) for d, o, c in pl.read_parquet(BENCH).select("date", "open", "close").iter_rows()}
    sig = signals(deals)
    pick = {f: cluster([(s, d) for d, s in sig.filter(pl.col(f)).select("date", "symbol").iter_rows()], cal)
            for f in ("buy", "sell", "block_buy")}
    t, k = measure(pick["buy"], cal, rows, bench, HOLD)
    lo = block_bootstrap(k)[0] if k.height >= 2 else float("nan")
    verdict = "PASS" if k.height >= MIN_N and lo > 0 else "FAIL"
    inst_rows = deals.filter(pl.col("client").str.to_uppercase().str.contains("|".join(KEYWORDS))).height
    lines = [f"E4 institutional whale signal - DEV (deal dates {DEV[0]}..{DEV[1]}). Generated {date.today()}.",
             "VERSION: FALLBACK rule (no point-in-time shares outstanding; see research/deals.py report).",
             f"GATE: n >= {MIN_N} buy events and {CONF:.2%} CI lower bound of mean net abnormal ({HOLD} sessions) > 0"
             f"  ->  {verdict}",
             *summary(k, f"Buy events, hold {HOLD} (gated)"),
             drops(t, "  buy events"),
             f"  inputs: deal rows {deals.height}, institutional rows {inst_rows}, stock-days with institutional "
             f"rows {sig['net'].is_not_null().sum()}, whale buy stock-days {sig['buy'].sum()} -> events "
             f"{len(pick['buy'])}; sell stock-days {sig['sell'].sum()} -> events {len(pick['sell'])}",
             "", "Secondary (reported only):"]
    for h in (5, 60):
        th, kh = measure(pick["buy"], cal, rows, bench, h)
        lines += [*summary(kh, f"  buy events, hold {h}"), drops(th, f"  hold {h}")]
    ts, ks = measure(pick["sell"], cal, rows, bench, HOLD)
    lines += [*summary(ks, f"  net-sell events, hold {HOLD} (long-side sign; a short gains when negative)"),
              drops(ts, "  net-sell events")]
    tb, kb = measure(pick["block_buy"], cal, rows, bench, HOLD)
    lines += [*summary(kb, f"  block deals alone (net institutional block qty > 0), hold {HOLD}"),
              drops(tb, "  block-only events")]
    OUT.mkdir(parents=True, exist_ok=True)
    k.write_parquet(OUT / "dev_events.parquet")
    text = "\n".join(lines) + "\n"
    (OUT / "dev_report.txt").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(run())
