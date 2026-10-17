"""A2: corporate-action adjustment (splits, bonuses, rights) from NSE's corporate-action history (plan 20261017).

Source: www.nseindia.com/api/corporates-corporateActions, one cached JSON per year in data/equity_ref/ca/
(frozen once fetched, like symbolchange.csv). Subjects are free text; `parse_subject` turns one into price factors
(post-event price = pre-event price x factor):
  * face-value split / consolidation "From Rs A To Rs B": B / A
  * bonus a:b (a new shares per b held):                b / (a + b)
  * rights a:b @ premium P (face F):                     TERP / cum = (b + a*(F+P)/C) / (a + b), C = cum close
  (rights with subscription >= cum close: 1, the rights are worthless)
Dividends, bonus preference shares/debentures and return of capital are not adjusted (plan A2).
An event applies from the stock's first session on/after its ex-date (within 10 days; perm_id via research.stock_id).
An event's perm_id comes from its ISIN (NSE lists today's symbol), else its symbol. Unparsed subjects, unresolved
rights, unmatched events, ex-day gaps the factor doesn't explain and a standard-ratio fallback detector go to the report.
Events NSE's feed lacks (mostly 2005-09) go in research/ca_manual.csv (split/bonus factor f) only with an NSE or BSE
filing URL as `source`; every event carries its source and the gate refuses to run on anything else (never Yahoo).
Run: uv run python -m research.corp_actions fetch [first_year last_year] | report | gate
(report -> data/equity/ca_report.txt; gate -> data/equity/ca_gate.txt, needs yfinance + network).
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from bisect import bisect_left
from datetime import date, datetime
from pathlib import Path

import polars as pl
import requests

from research import equity, stock_id

CA_DIR = stock_id.REF / "ca"
OUT = Path("data/equity")
API = "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=01-01-{y}&to_date=31-12-{y}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124 Safari/537.36",
           "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9",
           "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions"}


def fetch(years: range, pause: float = 2.0) -> None:
    CA_DIR.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.get("https://www.nseindia.com/", headers=HEADERS, timeout=30).raise_for_status()  # cookies
    for y in years:
        out = CA_DIR / f"{y}.json"
        if out.exists():
            continue
        r = s.get(API.format(y=y), headers=HEADERS, timeout=120)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            raise RuntimeError(f"{y}: no corporate actions returned")
        out.write_text(json.dumps(data), encoding="utf-8")
        print(y, len(data), flush=True)
        time.sleep(pause)


NUM = r"(\d+(?:\.\d+)?)"
SPLIT = re.compile(rf"(?:split|splt|spl\b|sub-?division|consolidat\w*)\D*?{NUM}\D*?(?<![a-z])to(?:\b|(?=r[se]|\d))\D*?{NUM}", re.I)  # "tors.2", "tore1", "to2"
# \D{0,30}? cannot cross a digit, so "Bonus 1 Dvr : 10 Eq" / "Rights-1 Pcd:2 Eq" (other instruments) stay unparsed
BONUS = re.compile(rf"bon(?:us)?(?![a-z])(?!\s+(?:preference|ncrps|deb))\D{{0,30}}?{NUM}\s*:\s*{NUM}", re.I)  # "Bonus1:1"
RIGHTS = re.compile(rf"(?:rights?|rht)(?![a-z])\D{{0,15}}?{NUM}\s*:\s*{NUM}", re.I)  # "Rht 7:2@Prem"
PREMIUM = re.compile(rf"(?:prem\w*|prm)\D{{0,12}}?{NUM}", re.I)
AT_PAR = re.compile(r"(?:at|@)\s*par\b", re.I)
KEYWORDS = re.compile(r"split|splt|fv\W*spl|spl\W*rs\W*\d+\W*to|sub-?div|bon(?:us)?(?![a-z])|(?:rights?|rht)(?![a-z])|consolidat|reduction", re.I)
NOT_EQUITY = re.compile(r"bonus\s+(?:preference|ncrps|deb)|sch\w* of a\w*", re.I)  # value transfers, not share counts
MANUAL = Path(__file__).with_name("ca_manual.csv")
OFFICIAL = r"(?i)^https://(?:(?:www|nsearchives|archives)\.)?(?:nseindia|bseindia)\.com/"  # NSE / BSE filing or archive URL
EVENT_TOL = "10d"  # ex-date -> first session of the symbol within this many calendar days, else unmatched


def parse_subject(subject: str) -> list[tuple]:
    """('split', B/A) | ('bonus', b/(a+b)) | ('rights', a, b, premium or None). Empty if nothing parsed."""
    out = [("split", float(b) / float(a)) for a, b in SPLIT.findall(subject) if float(a) > 0]
    out += [("bonus", float(b) / (float(a) + float(b))) for a, b in BONUS.findall(subject)]
    for a, b in RIGHTS.findall(subject):
        p = PREMIUM.search(subject)
        out.append(("rights", float(a), float(b),
                    float(p.group(1)) if p else 0.0 if AT_PAR.search(subject) else None))
    return out


def raw_events() -> tuple[pl.DataFrame, pl.DataFrame]:
    """(events: symbol, isin, ex_date, face, subject, kind, f, a, b, premium; unparsed corporate-action subjects)."""
    ev, bad = [], []
    for p in sorted(CA_DIR.glob("*.json")):
        for x in json.loads(p.read_text(encoding="utf-8")):
            subj = x["subject"].strip()
            if not KEYWORDS.search(subj):
                continue
            d = datetime.strptime(x["exDate"], "%d-%b-%Y").date()
            try:
                face = float(x["faceVal"])
            except (TypeError, ValueError):
                face = None
            parsed = parse_subject(subj)
            if not parsed and not NOT_EQUITY.search(subj):
                bad.append((x["symbol"], d, subj))
            for e in parsed:
                f = e[1] if e[0] != "rights" else None
                a, b, prem = e[1:] if e[0] == "rights" else (None, None, None)
                ev.append((x["symbol"], x["isin"], d, face, subj, e[0], f, a, b, prem, API.format(y=p.stem)))
    cols = {"symbol": pl.Utf8, "isin": pl.Utf8, "ex_date": pl.Date, "face": pl.Float64, "subject": pl.Utf8,
            "kind": pl.Utf8, "f": pl.Float64, "a": pl.Float64, "b": pl.Float64, "premium": pl.Float64,
            "source": pl.Utf8}
    nse = pl.DataFrame(ev, schema=cols, orient="row").unique(maintain_order=True)
    return (pl.concat([nse, manual_events()], how="diagonal_relaxed"),
            pl.DataFrame(bad, schema={"symbol": pl.Utf8, "ex_date": pl.Date, "subject": pl.Utf8}, orient="row"))


def manual_events(path: Path = MANUAL) -> pl.DataFrame:
    """Hand-confirmed split/bonus events (symbol, isin, ex_date, kind, f, source). Raises on a non-NSE/BSE source,
    an unknown kind or f <= 0, so a bad row can never be adjusted silently."""
    df = pl.read_csv(path, schema={"symbol": pl.Utf8, "isin": pl.Utf8, "ex_date": pl.Date, "kind": pl.Utf8,
                                   "f": pl.Float64, "source": pl.Utf8})
    bad = df.filter(~pl.col("kind").is_in(["split", "bonus"]) | ~(pl.col("f") > 0)
                    | ~pl.col("source").str.contains(OFFICIAL).fill_null(False)
                    | pl.col("ex_date").is_null() | pl.col("symbol").is_null())
    if bad.height:
        raise ValueError(f"{path}: rows need kind split/bonus, f > 0 and an NSE/BSE source URL:\n{bad}")
    return df.with_columns(subject=pl.lit("manual: ") + pl.col("source"))


def with_prev(rows: pl.DataFrame) -> pl.DataFrame:
    """rows: date, symbol, open, close, perm_id -> + prev_close (previous session of the same perm_id)."""
    return rows.sort("perm_id", "date").with_columns(prev_close=pl.col("close").shift().over("perm_id"))


def map_events(ev: pl.DataFrame, rows: pl.DataFrame, ids: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Each event -> (perm_id, date = first session of that perm_id on/after ex_date) with its factor f resolved
    (rights from prev_close). perm_id from the event's ISIN (NSE reports today's symbol: INFY was INFOSYSTCH
    before 2011), else from its symbol's first session on/after ex_date, else from the one perm_id that ever traded
    under that symbol (VITLINFO's 2009 split is filed as CORALHUB, a pre-ISIN rename). Returns (events, unmatched)."""
    r = rows.select("symbol", "date", "perm_id", "open", "prev_close").sort("date")
    ever = (r.select("symbol", perm_id_ever="perm_id").drop_nulls().unique()
            .filter(pl.len().over("symbol") == 1))  # a reused symbol (several perm_ids) stays ambiguous -> skipped
    by_sym = (ev.sort("ex_date").join_asof(r.select("symbol", "date", "perm_id"), left_on="ex_date", right_on="date",
                                          by="symbol", strategy="forward", tolerance=EVENT_TOL,
                                          check_sortedness=False)  # both sorted by date
              .join(ids, left_on="isin", right_on="node", how="left", suffix="_isin")
              .join(ever, on="symbol", how="left")
              .with_columns(perm_id=pl.coalesce("perm_id_isin", "perm_id", "perm_id_ever"))
              .drop("date", "perm_id_isin", "perm_id_ever"))
    m = by_sym.sort("ex_date").join_asof(r.drop("symbol"), left_on="ex_date", right_on="date", by="perm_id",
                                         strategy="forward", tolerance=EVENT_TOL, check_sortedness=False)
    unmatched = m.filter(pl.col("date").is_null()).select("symbol", "ex_date", "subject")
    m = m.filter(pl.col("date").is_not_null())
    other = m.filter(pl.col("kind") != "rights").group_by("perm_id", "date").agg(f_other=pl.col("f").product())
    cum = pl.col("prev_close") * pl.col("f_other").fill_null(1.0)  # cum price in post-split/bonus terms
    terp = (pl.col("b") + pl.col("a") * (pl.col("face") + pl.col("premium")) / cum) / (pl.col("a") + pl.col("b"))
    m = (m.join(other, on=["perm_id", "date"], how="left")   # null premium/face/prev_close -> f null (unresolved)
         .with_columns(f=pl.when(pl.col("kind") != "rights").then(pl.col("f"))
                       .when(cum > 0).then(terp.clip(upper_bound=1.0))))  # clip keeps null
    manual = pl.col("subject").str.starts_with("manual: ")
    mm = m.filter(manual)
    dup = pl.concat([mm.join(m.filter(~manual), on=["perm_id", "date"], how="semi"),
                     mm.filter(pl.struct("perm_id", "date").is_duplicated())])
    if dup.height:  # the factor would be applied twice
        raise ValueError(f"ca_manual.csv rows on a session NSE's feed already covers:\n{dup}")
    return m.drop("f_other"), unmatched


def day_factors(m: pl.DataFrame) -> pl.DataFrame:
    """perm_id, date, f (product of the events applied that session); unresolved rights (f null) are skipped."""
    return m.filter(pl.col("f") > 0).group_by("perm_id", "date").agg(f=pl.col("f").product())


def adjust(rows: pl.DataFrame, days: pl.DataFrame) -> pl.DataFrame:
    """Adds adj (backward cumulative factor: product of f over later event sessions) and adj_close."""
    return (rows.join(days, on=["perm_id", "date"], how="left").with_columns(pl.col("f").fill_null(1.0))
            .sort("perm_id", "date")
            .with_columns(adj=(pl.col("f").reverse().cum_prod().reverse() / pl.col("f")).over("perm_id"))
            .with_columns(adj_close=pl.col("close") * pl.col("adj")).drop("f"))


STD_RATIOS = (1 / 2, 1 / 3, 2 / 3, 1 / 4, 1 / 5, 1 / 10, 2.0, 5.0, 10.0)  # bonus 1:1 1:2 2:1 3:1 4:1, splits
RATIO_TOL = 0.015
MIN_PRICE = 10.0  # ponytail: below this, tick-size noise swamps the ratios (575 of 585 2016/2019 hits)


def suspects(rows: pl.DataFrame, days: pl.DataFrame) -> pl.DataFrame:
    """Fallback detector: sessions with open/prev_close within RATIO_TOL of a standard ratio and no mapped event
    (prev_close >= MIN_PRICE). A hand-check list only: nothing here is adjusted unless an NSE/BSE filing confirms it (never Yahoo)."""
    near = pl.any_horizontal([(pl.col("r") / v - 1).abs() < RATIO_TOL for v in STD_RATIOS])
    return (rows.join(days, on=["perm_id", "date"], how="anti").filter(pl.col("prev_close") >= MIN_PRICE)
            .with_columns(r=pl.col("open") / pl.col("prev_close")).filter(near)
            .select("perm_id", "symbol", "date", "prev_close", "open", "r").sort("date"))


def annotate(sus: pl.DataFrame, rows: pl.DataFrame) -> pl.DataFrame:
    """Adds nse_subject: NSE-feed share-structure subjects (scheme, demerger, split, bonus...) of a symbol the perm_id ever traded under,
    ex-dated within EVENT_TOL before the hit. Demergers and schemes land here: real, but outside A2's scope."""
    near = (filings_near(sus, rows, nse_feed(), r"(?i)sch|demerg|arrang|amalg|spl|bon|rht|right|reduc|consol")
            .group_by("perm_id", "date").agg(nse_subject=pl.col("subj").unique().sort().str.join(" | ")))
    return sus.join(near, on=["perm_id", "date"], how="left")


def nse_feed() -> pl.DataFrame:
    """Every cached NSE corporate-action row: symbol, ex, subj."""
    return pl.DataFrame([(x["symbol"], datetime.strptime(x["exDate"], "%d-%b-%Y").date(), x["subject"].strip())
                         for p in sorted(CA_DIR.glob("*.json")) for x in json.loads(p.read_text(encoding="utf-8"))],
                        schema={"symbol": pl.Utf8, "ex": pl.Date, "subj": pl.Utf8}, orient="row")


def filings_near(s: pl.DataFrame, rows: pl.DataFrame, feed: pl.DataFrame, subj: str) -> pl.DataFrame:
    """(perm_id, date) of s x feed rows of any symbol the perm_id traded under, subject matching subj,
    ex-dated within 10 days before the session."""
    return (s.select("perm_id", "date").join(rows.select("perm_id", "symbol").unique(), on="perm_id")
            .join(feed, on="symbol")
            .filter(pl.col("ex").is_between(pl.col("date") - pl.duration(days=10), pl.col("date"))
                    & pl.col("subj").str.contains(subj)))


SCHEME = r"(?i)demerg|sch|arrang|amalg"
SCHEME_GAP = 0.10  # |open / (prev_close x f) - 1| above this near an NSE demerger / scheme filing
STALE = 20         # previous row of the stock more than this many sessions back: a resumption


def schemes(rows: pl.DataFrame, days: pl.DataFrame, feed: pl.DataFrame) -> pl.DataFrame:
    """Sessions gapping more than SCHEME_GAP (after any applied factor) with an NSE demerger / scheme filing
    ex-dated within 10 days before: a value transfer A2 does not adjust."""
    gap = (rows.join(days, on=["perm_id", "date"], how="left")
           .filter((pl.col("open") / (pl.col("prev_close") * pl.col("f").fill_null(1.0)) - 1).abs() > SCHEME_GAP))
    return filings_near(gap, rows, feed, SCHEME).group_by("perm_id", "date").agg(subj=pl.col("subj").unique().sort().str.join(" | "))


def stale(rows: pl.DataFrame, cal: list) -> pl.DataFrame:
    """Sessions whose previous row of the perm_id is more than STALE sessions (cal) back: prev_close is stale."""
    idx = pl.DataFrame({"date": cal, "i": list(range(len(cal)))}, schema={"date": pl.Date, "i": pl.Int64})
    return (rows.join(idx, on="date").sort("perm_id", "date")
            .with_columns(gap=pl.col("i").diff().over("perm_id")).filter(pl.col("gap") > STALE)
            .select("perm_id", "date", "gap"))


OUTLIER = 0.25  # ex-day |r - 1| above this: the applied factor may be wrong


def flag(rows: pl.DataFrame, sessions: pl.DataFrame) -> pl.DataFrame:
    """ca_flag on these (perm_id, date) sessions; ca_flag_n = flags so far for the perm_id (date order).
    Plan rule (amendment 3): drop a return window (t0, t1] when ca_flag_n[t1] > ca_flag_n[t0]."""
    s = sessions.select("perm_id", "date").unique().with_columns(ca_flag=pl.lit(True))
    return (rows.join(s, on=["perm_id", "date"], how="left").with_columns(pl.col("ca_flag").fill_null(False))
            .sort("perm_id", "date").with_columns(ca_flag_n=pl.col("ca_flag").cast(pl.Int32).cum_sum().over("perm_id")))


def build() -> dict:
    """Everything A2 produces from the cached inputs. `rows` carries adj / adj_close, ca_flag and ca_flag_n. Flagged:
    a fallback-detector session no NSE/BSE filing confirms (not adjusted), or an event session whose ex-day gap the
    applied factor leaves more than OUTLIER off, a session with an unresolved rights issue (f null, not adjusted),
    a gap near an NSE demerger / scheme filing (`schemes`), or a resumption after a suspension (`stale`).
    A return across any of them may not be a tradable move. Unmatched events have no session to flag."""
    rows = equity.load().select("date", "symbol", "isin", "open", "close")
    ids, _, _ = stock_id.build(rows.select("date", "symbol", "isin"), stock_id.symbol_changes())
    rows = with_prev(stock_id.assign(rows, ids))
    ev, unparsed = raw_events()
    m, unmatched = map_events(ev, rows, ids)
    days = day_factors(m)
    sus = suspects(rows, days)
    a = {"rows": adjust(rows, days), "events": m, "unparsed": unparsed, "unmatched": unmatched, "days": days}
    out = ex_check(a).filter((pl.col("r") - 1).abs() > OUTLIER)
    unres = m.filter(pl.col("f").is_null())  # rights with no premium / prev close: known, not adjusted
    a["schemes"] = schemes(rows, days, nse_feed())
    a["stale"] = stale(rows, stock_id.sessions(rows.select("date")))
    a["rows"] = flag(a["rows"], pl.concat([x.select("perm_id", "date")
                                           for x in (sus, out, unres, a["schemes"], a["stale"])]))
    a["suspects"] = annotate(sus, a["rows"])
    return a


def ex_check(a: dict) -> pl.DataFrame:
    """Per event session: kinds, f, r = open / (prev_close * f) (1 = the gap is fully explained)."""
    k = a["events"].filter(pl.col("f") > 0).group_by("perm_id", "date").agg(
        sym=pl.col("symbol").first(), kinds=pl.col("kind").unique().sort().str.join("+"),
        subject=pl.col("subject").unique().str.join(" | "), sources=pl.col("source").unique().str.join(" | "))
    return (a["days"].join(k, on=["perm_id", "date"])
            .join(a["rows"].select("perm_id", "date", "open", "prev_close"), on=["perm_id", "date"])
            .with_columns(r=pl.col("open") / (pl.col("prev_close") * pl.col("f"))).sort("date"))


def report(a: dict) -> str:
    ev, x = a["events"], ex_check(a)
    unres = ev.filter(pl.col("f").is_null()).select("symbol", "date", "subject").sort("date")
    sus = a["suspects"]

    def sym(d: pl.DataFrame) -> pl.DataFrame:
        return d.join(a["rows"].select("perm_id", "date", "symbol", "prev_close", "open"), on=["perm_id", "date"])
    big = (a["rows"].join(a["days"], on=["perm_id", "date"], how="anti")
           .filter(~pl.col("ca_flag") & (pl.col("prev_close") >= MIN_PRICE)
                   & ~(pl.col("open") / pl.col("prev_close")).is_between(0.6, 1.8))
           .select("symbol", "date", "prev_close", "open", "close").sort("date"))
    out = [f"A2 corporate actions: {ev.height + a['unmatched'].height} parsed events, {ev.height} mapped to a "
           f"session, {a['unmatched'].height} unmatched, {unres.height} unresolved rights (no premium or prev close), "
           f"{a['unparsed'].height} unparsed subjects; {a['days'].height} adjusted sessions.",
           "Sources of mapped events: " + ", ".join(
               f"{h} {n}" for h, n in ev.group_by(host=pl.col("source").str.extract(r"//([^/]+)/"))
               .len().sort("host").iter_rows()),
           "Ex-day check r = open / (prev_close x f): sessions, share within 10% / 25% of 1, by kinds on the session:"]
    for (k,), g in x.group_by("kinds", maintain_order=True):
        d = (g["r"] - 1).abs()
        out.append(f"  {k:<22} {g.height:5d}  {(d < 0.10).mean():.3f}  {(d < 0.25).mean():.3f}")
    with pl.Config(tbl_rows=-1, fmt_str_lengths=80, tbl_width_chars=220):
        for title, df in [("Manual events (research/ca_manual.csv)",
                           ev.filter(pl.col("subject").str.starts_with("manual: "))
                           .select("symbol", "date", "kind", "f", "source")),
                          (f"Ex-day outliers |r - 1| > {OUTLIER} (factor applied; ca_flag = true)",
                           x.filter((pl.col("r") - 1).abs() > OUTLIER).drop("perm_id")),
                          ("Unresolved rights (not adjusted; ca_flag = true)", unres),
                          ("Unmatched events (no session of the stock within 10 days)", a["unmatched"]),
                          ("Unparsed subjects", a["unparsed"].sort("ex_date")),
                          (f"Fallback detector: standard-ratio gaps with no NSE split/bonus/rights ({sus.height}; "
                           "not adjusted, ca_flag = true). nse_subject: other NSE filings ex-dated <= 10 days before "
                           "(demergers, schemes: outside A2). BSE per-scrip corporate-action history (api.bseindia.com "
                           "CorporateAction, checked 2026-10-17) starts ~2008-10: hits before that are not checkable "
                           "on BSE; for later hits no BSE split/bonus filing was found", sus),
                          (f"Gaps > {SCHEME_GAP:.0%} near an NSE demerger / scheme filing ({a['schemes'].height}; "
                           "not adjusted, ca_flag = true)", sym(a["schemes"]).sort("date")),
                          (f"Resumptions: previous row more than {STALE} sessions back ({a['stale'].height}; "
                           "ca_flag = true), by year", a["stale"].group_by(year=pl.col("date").dt.year())
                           .agg(n=pl.len(), median_gap=pl.col("gap").median()).sort("year")),
                          ("Large gaps left in as moves (open/prev_close < 0.6 or > 1.8, prev_close >= "
                           f"{MIN_PRICE:.0f}, no event, not flagged)", big)]:
            out += ["", f"{title}:", str(df)]
    return "\n".join(out)


GATE_SEED, GATE_FIRST, GATE_STEP, GATE_MIN_DAYS = 20261017, 50, 10, 20
GATE_TOL, GATE_PASS = 0.001, 0.95
GATE_ENDS = (date(2010, 1, 4), date(2026, 9, 30))


def survivors(rows: pl.DataFrame) -> list[str]:
    """Plan A2 sample order: perm_ids listed on both GATE_ENDS days, sorted, shuffled with the fixed seed."""
    on = [set(rows.filter(pl.col("date") == d)["perm_id"].drop_nulls()) for d in GATE_ENDS]
    s = sorted(on[0] & on[1])
    random.Random(GATE_SEED).shuffle(s)
    return s


def gate_days(sub: pl.DataFrame, splits: list[date], closes: dict) -> list[dict]:
    """sub: one perm_id's rows (date-sorted, adj_close). One test row per Yahoo split date inside its history;
    a date missing from either series counts as a miss."""
    dates, adj = sub["date"].to_list(), sub["adj_close"].to_list()
    ydates = sorted(closes)
    out = []
    for d in splits:
        if not dates[0] < d <= GATE_ENDS[1]:
            continue
        row = {"perm_id": sub["perm_id"][0], "date": d, "a2": None, "yahoo": None, "ok": False}
        i, j = bisect_left(dates, d), bisect_left(ydates, d)
        if i < len(dates) and dates[i] == d:
            row["a2"] = adj[i] / adj[i - 1] - 1
        if 0 < j < len(ydates) and ydates[j] == d:
            row["yahoo"] = closes[d] / closes[ydates[j - 1]] - 1
        if row["a2"] is not None and row["yahoo"] is not None:
            row["ok"] = abs(row["a2"] - row["yahoo"]) <= GATE_TOL
        out.append(row)
    return out


def yahoo(ticker: str) -> tuple[list[date], dict]:
    """Yahoo split dates and split-adjusted (not dividend-adjusted) Close."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    h = t.history(start="2005-01-01", end="2026-10-01", auto_adjust=False)
    return ([d.date() for d in t.splits.index],
            {d.date(): float(c) for d, c in h["Close"].items()} if "Close" in h else {})


def unofficial(events: pl.DataFrame, pids: list[str]) -> pl.DataFrame:
    """Applied events (f > 0) of these perm_ids whose source is not an NSE/BSE URL (missing counts)."""
    return events.filter(pl.col("perm_id").is_in(pids) & (pl.col("f") > 0)
                         & ~pl.col("source").str.contains(OFFICIAL).fill_null(False))


def gate(a: dict) -> str:
    rows = a["rows"]
    order, tested, lines, n, i = survivors(rows), [], [], GATE_FIRST, 0
    while True:
        for pid in order[i:n]:
            sub = rows.filter(pl.col("perm_id") == pid).sort("date")
            tk = sub["symbol"][-1] + ".NS"
            sp, cl = yahoo(tk)
            got = gate_days(sub, sp, cl)
            tested += got
            lines.append(f"  {pid:<14} {tk:<16} yahoo rows {len(cl):5d}  splits {len(sp):2d}  test days {len(got)}")
        i = min(n, len(order))
        if len(tested) >= GATE_MIN_DAYS or n >= len(order):
            break
        n += GATE_STEP
    t = pl.DataFrame(tested, schema={"perm_id": pl.Utf8, "date": pl.Date, "a2": pl.Float64, "yahoo": pl.Float64,
                                     "ok": pl.Boolean})
    rate = t["ok"].mean() if t.height else None
    applied = a["events"].filter(pl.col("perm_id").is_in(order[:i]) & (pl.col("f") > 0))
    bad = unofficial(a["events"], order[:i])
    verdict = ("NOT RUN (an applied event in the sample lacks an NSE/BSE source; not a pass)" if bad.height
               else "NOT RUN (fewer than 20 test days; not a pass)" if t.height < GATE_MIN_DAYS
               else "PASS" if rate >= GATE_PASS else "FAIL")
    hosts = ", ".join(f"{h} {n}" for h, n in applied.group_by(host=pl.col("source").str.extract(r"//([^/]+)/"))
                      .len().sort("host").iter_rows())
    head = (f"A2 gate: {verdict}. {i} survivors of {len(order)} drawn (seed {GATE_SEED}); {t.height} test days; "
            f"match rate (|A2 - Yahoo| <= 0.1pp) {rate if rate is None else round(rate, 4)}. "
            f"Sources of the {applied.height} applied events in the sample: {hosts or 'none'}; "
            f"{bad.height} without an NSE/BSE source.")
    with pl.Config(tbl_rows=-1, fmt_str_lengths=120):
        return "\n".join([head, "", "Sample:", *lines, "", str(bad), "",
                          str(t.with_columns(diff_pp=(pl.col("a2") - pl.col("yahoo")) * 100))])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "fetch":
        y = [int(x) for x in sys.argv[2:4]] or [2005, 2026]
        fetch(range(y[0], y[1] + 1))
    else:
        a = build()
        name, text = ("ca_gate.txt", gate(a)) if cmd == "gate" else ("ca_report.txt", report(a))
        (OUT / name).write_text(text, encoding="utf-8")
        print(text.split("\n\n")[0])
