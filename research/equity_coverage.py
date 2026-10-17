"""A1 coverage report for the equity store + permanent stock ID + A3 benchmark gap check (plan 20261017).

Run: uv run python -m research.equity_coverage  -> prints a summary, writes data/equity/coverage_report.txt
(the full list of chain links is in the file only).
"""
from __future__ import annotations

import sys
from bisect import bisect_left
from datetime import date

import polars as pl

from research import benchmarks, equity, stock_id

LONG_GAP = stock_id.SYM_GAP  # internal gap (sessions) that flags a SYM node for a symbol-reuse hand check


def manifest_counts() -> dict[str, int]:
    m = pl.read_csv(equity.MANIFEST)
    return dict(m.group_by("status").len().iter_rows())


def gap_days(days: list[date], index_days: list[date]) -> list[date]:
    """Days the Nifty 50 index traded but the equity archive has no session (archive holes)."""
    have = set(days)
    return [d for d in index_days if d not in have and days[0] <= d <= days[-1]]


def isin_near_misses(nodes: pl.DataFrame, links: pl.DataFrame, days: list[date]) -> pl.DataFrame:
    """Same ISIN chars 3-9, b starts 2..LONG_GAP sessions after a ends, not linked (strict rule refused)."""
    isin = (nodes.filter(~pl.col("node").str.starts_with("SYM:"))
            .with_columns(code=pl.col("node").str.slice(2, 7),
                          i_last=pl.col("last").map_elements(lambda d: bisect_left(days, d), pl.Int64),
                          i_first=pl.col("first").map_elements(lambda d: bisect_left(days, d), pl.Int64)))
    pairs = (isin.join(isin, on="code", suffix="_b").filter(pl.col("node") != pl.col("node_b"))
             .with_columns(missing=pl.col("i_first_b") - pl.col("i_last") - 1)
             .filter(pl.col("missing").is_between(1, LONG_GAP - 1)))
    linked = links.select(pl.col("a").alias("node"), pl.col("b").alias("node_b"))
    return (pairs.join(linked, on=["node", "node_b"], how="anti")
            .select("node", "sym1", "last", "node_b", "sym0_b", "first_b", "missing").sort("node"))


def sym_long_gaps(rows: pl.DataFrame, days: list[date]) -> pl.DataFrame:
    """Pre-ISIN symbols with an internal gap > LONG_GAP sessions (possible reuse by another company)."""
    pos = {d: i for i, d in enumerate(days)}
    s = (rows.filter(pl.col("isin").is_null() & pl.col("date").is_in(pl.Series(days).implode()))
         .select("symbol", "date").unique().sort("symbol", "date")
         .with_columns(i=pl.col("date").replace_strict(pos, return_dtype=pl.Int64)))
    return (s.with_columns(prev=pl.col("date").shift().over("symbol"), gap=pl.col("i").diff().over("symbol") - 1)
            .filter(pl.col("gap") > LONG_GAP).select("symbol", "prev", "date", "gap"))


def report(rows: pl.DataFrame) -> tuple[str, str]:
    """Returns (summary, full text)."""
    days = stock_id.sessions(rows)
    all_days = rows["date"].unique().sort().to_list()
    ids, links, amb = stock_id.build(rows, stock_id.symbol_changes())
    nodes = (rows.select("date", "symbol", stock_id._node()).sort("date").group_by("node")
             .agg(first=pl.col("date").first(), last=pl.col("date").last(),
                  sym0=pl.col("symbol").first(), sym1=pl.col("symbol").last()))
    a = stock_id.assign(rows, ids)
    L = [f"equity rows {rows.height:,}; dates {rows['date'].min()} .. {rows['date'].max()}",
         f"manifest: {manifest_counts()}",
         f"sessions {len(days)}; dropped near-empty days (< {stock_id.MIN_SESSION_SHARE:.0%} of median rows): "
         f"{sorted(set(all_days) - set(days))}"]
    n50 = benchmarks.load("price", "NIFTY 50")["date"].to_list()
    L.append(f"A1 gap days (Nifty 50 traded, no equity file): {gap_days(all_days, n50)}")

    L.append("A3 benchmark gaps vs sessions (Momentum 30 from 2005-04-01):")
    for kind, names in (("price", benchmarks.PRICE), ("tri", benchmarks.TRI)):
        for n in names:
            start = date(2005, 4, 1) if "MOMENTUM" in n else days[0]
            g = benchmarks.check_gaps(benchmarks.load(kind, n), [d for d in days if d >= start],
                                      "close" if kind == "price" else "tri")
            L.append(f"  {kind:5} {n}: {len(g)} {g[:10]}")

    kind = lambda c: pl.when(pl.col(c).str.starts_with("SYM:")).then(pl.lit("SYM")).otherwise(pl.lit("ISIN"))
    by_kind = links.group_by((kind("a") + pl.lit("->") + kind("b")).alias("k")).len().sort("k")
    L += [f"stock ID: nodes {ids.height:,}; permanent IDs {ids['perm_id'].n_unique():,}; links {links.height:,} "
          f"{dict(by_kind.iter_rows())}; ambiguous (unlinked) {amb.height}",
          f"rows without perm_id: {a['perm_id'].null_count()}; duplicate (date, perm_id): "
          f"{a.group_by('date', 'perm_id').len().filter(pl.col('len') > 1).height}"]
    gapped = links.filter(pl.col("missing") > 0).sort("missing", descending=True)
    near = isin_near_misses(nodes, links, days)
    sym_unlinked = (nodes.join(ids, on="node").filter(pl.col("node").str.starts_with("SYM:"),
                                                     pl.col("node") == pl.col("perm_id"),
                                                     pl.col("last") >= date(2011, 4, 1))
                    .select("node", "first", "last").sort("node"))
    lg = sym_long_gaps(rows, days)
    tables = lambda: [f"links with missing sessions > 0: {gapped.height}\n{gapped}",
                      f"ambiguous candidates: {amb.height}\n{amb}",
                      f"ISIN->ISIN near misses (same chars 3-9, 1..{LONG_GAP - 1} sessions missing; strict rule, "
                      f"hand check): {near.height}\n{near}",
                      f"SYM nodes alive from 2011-04-01 (switch 2011-06-22) with no successor: "
                      f"{sym_unlinked.height}\n{sym_unlinked}",
                      f"SYM nodes with an internal gap > {LONG_GAP} sessions (symbol reuse? hand check): "
                      f"{lg.height}\n{lg}"]
    summary = "\n".join(L + tables())
    with pl.Config(tbl_rows=-1, fmt_str_lengths=40):
        full = "\n".join(L + tables())
    full += "\n\nALL CHAIN LINKS:\n" + "\n".join(f"{x} -> {y} (missing {m})" for x, y, m in links.sort("a").iter_rows())
    return summary, full


if __name__ == "__main__":
    summary, full = report(equity.load().select("date", "symbol", "isin"))
    (equity.ROOT / "coverage_report.txt").write_text(full, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(summary)
