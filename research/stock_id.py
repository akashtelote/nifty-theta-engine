"""Permanent stock ID over the A1 equity rows (plan 20261017 E1-E4, task A1).

A *node* is an ISIN, or "SYM:<symbol>" for rows before the bhavcopy carried ISINs (first ISIN day 2011-06-22).
Node a is continued by node b when:
  * ISIN -> ISIN: b's first session is the session right after a's last (plan rule), same issuer + security code
    (ISIN chars 3-9), and same symbol or a symbol-change pair;
  * SYM  -> ISIN: same symbol (the 2011 ISIN switch) or a symbol-change pair, b starting within SYM_GAP sessions;
  * SYM  -> SYM : a symbol-change pair (pre-2011 rename), b starting within SYM_GAP sessions.
  For a SYM node the nearest session with any match wins (TITAN: old ISIN on the switch day, split ISIN days later).
Sessions are days with >= MIN_SESSION_SHARE of the median row count (drops the 7- and 14-row Sunday specials).
A link is kept only if it is the sole successor of a and the sole predecessor of b (ambiguous -> reported, unlinked).
The permanent ID is the newest node of the chain. Renames that keep their ISIN need no link.

Symbol-change list: nsearchives.nseindia.com/content/equities/symbolchange.csv -> data/equity_ref/.
ponytail: a pre-2011 symbol reused by a different company merges into one SYM node; SYM_GAP keeps a reuse years
later from linking across. research/equity_coverage.py lists SYM nodes with long internal gaps and every link
(with its `missing` sessions) for a hand check.
"""
from __future__ import annotations

import io
from bisect import bisect_left, bisect_right
from pathlib import Path

import polars as pl
import requests

from research import bhavcopy

REF = Path("data/equity_ref")
SYMBOL_CHANGES = REF / "symbolchange.csv"
SYMBOL_CHANGES_URL = f"{bhavcopy.BASE}/equities/symbolchange.csv"
SYM_GAP = 60             # ~3 months; slowest real cases: KEYCORPSER 2011 switch, GPELECT->DELTAMAGNT ~1 month
MIN_SESSION_SHARE = 0.1


def parse_symbol_changes(raw: bytes) -> pl.DataFrame:
    df = pl.read_csv(io.BytesIO(raw), infer_schema_length=0, truncate_ragged_lines=True)
    df = df.rename({c: c.strip() for c in df.columns})
    return df.select(pl.col("OLD SYMBOL").str.strip_chars().alias("old"),
                     pl.col("NEW SYMBOL").str.strip_chars().alias("new"),
                     pl.col("EFFECTIVE DATE").str.strip_chars().str.strptime(pl.Date, "%d-%b-%Y").alias("date"))


def fetch_symbol_changes() -> pl.DataFrame:
    r = requests.get(SYMBOL_CHANGES_URL, headers=bhavcopy._HEADERS, timeout=60)
    r.raise_for_status()
    df = parse_symbol_changes(r.content)
    if df.is_empty():
        raise RuntimeError("symbolchange.csv has no rows")
    REF.mkdir(parents=True, exist_ok=True)
    SYMBOL_CHANGES.write_bytes(r.content)
    return df


def symbol_changes() -> pl.DataFrame:
    """Cached copy (fetched once, then frozen so the IDs stay reproducible)."""
    return parse_symbol_changes(SYMBOL_CHANGES.read_bytes()) if SYMBOL_CHANGES.exists() else fetch_symbol_changes()


def sessions(rows: pl.DataFrame) -> list:
    """Trading days: dates with >= MIN_SESSION_SHARE of the median row count."""
    counts = rows.group_by("date").len()
    floor = MIN_SESSION_SHARE * (counts["len"].median() or 0)
    return counts.filter(pl.col("len") >= floor)["date"].sort().to_list()


def _ok(a: dict, b: dict, a_sym: bool, b_sym: bool, pairs: set) -> bool:
    renamed = (a["sym1"], b["sym0"]) in pairs
    if not a_sym and not b_sym:
        return a["node"][2:9] == b["node"][2:9] and (a["sym1"] == b["sym0"] or renamed)
    if a_sym and not b_sym:
        return a["sym1"] == b["sym0"] or renamed
    return a_sym and renamed


def _node() -> pl.Expr:
    return pl.coalesce(pl.col("isin"), pl.lit("SYM:") + pl.col("symbol")).alias("node")


def build(rows: pl.DataFrame, changes: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """rows: date, symbol, isin. Returns (ids: node -> perm_id, links: a -> b with `missing` sessions between,
    ambiguous: candidate pairs dropped)."""
    days = sessions(rows)
    nodes = (rows.select("date", "symbol", _node()).sort("date").group_by("node", maintain_order=True)
             .agg(first=pl.col("date").first(), last=pl.col("date").last(),
                  sym0=pl.col("symbol").first(), sym1=pl.col("symbol").last()))
    pairs = set(zip(changes["old"], changes["new"]))
    by_first: dict = {}
    for n in nodes.iter_rows(named=True):
        by_first.setdefault(bisect_left(days, n["first"]), []).append(n)  # first session on/after its first row

    cand = []
    for a in nodes.iter_rows(named=True):
        i, a_sym = bisect_right(days, a["last"]) - 1, a["node"].startswith("SYM:")
        for k in range(1, (SYM_GAP if a_sym else 1) + 1):
            hits = [(a["node"], b["node"], k - 1) for b in by_first.get(i + k, [])
                    if b["first"] > a["last"]  # strictly forward in time -> chains can't cycle
                    and _ok(a, b, a_sym, b["node"].startswith("SYM:"), pairs)]
            cand += hits
            if hits:
                break

    n_succ: dict = {}
    n_pred: dict = {}
    for a, b, _ in cand:
        n_succ[a] = n_succ.get(a, 0) + 1
        n_pred[b] = n_pred.get(b, 0) + 1
    links = [c for c in cand if n_succ[c[0]] == 1 and n_pred[c[1]] == 1]
    ambiguous = [c for c in cand if not (n_succ[c[0]] == 1 and n_pred[c[1]] == 1)]

    succ = {a: b for a, b, _ in links}
    ids = []
    for n in nodes["node"]:
        tail = n
        while tail in succ:
            tail = succ[tail]
        ids.append((n, tail))
    schema = {"a": pl.Utf8, "b": pl.Utf8, "missing": pl.Int64}
    return (pl.DataFrame(ids, schema={"node": pl.Utf8, "perm_id": pl.Utf8}, orient="row"),
            pl.DataFrame(links, schema=schema, orient="row"), pl.DataFrame(ambiguous, schema=schema, orient="row"))


def assign(rows: pl.DataFrame, ids: pl.DataFrame) -> pl.DataFrame:
    """Adds perm_id to equity rows."""
    return rows.with_columns(_node()).join(ids, on="node", how="left").drop("node")
