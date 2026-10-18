"""A5: futures data for E3 (plan 20261017-equity-futures-hypotheses, A5).

Sources (probed 2026-10-18):
  * NSE index futures (FUTIDX NIFTY, BANKNIFTY): the F&O bhavcopy archive of research/bhavcopy.py (legacy from
    2005-01-03, UDiFF after 2024-07-05), re-downloaded with a futures parser. Legacy rows carry no lot size: it is
    implied per contract-day as VAL_INLAKH*1e5 / (contracts*close), snapped to a multiple of 5 (contract-days with
    >= 10 contracts), carried within the contract, else taken from the same symbol's other contracts that day.
  * NSE currency futures (USDINR, EURINR, GBPINR, JPYINR): .../archives/cd/bhav/CD_Bhavcopy<ddmmyy>.zip up to
    2024-07-05 (DBF members before ~2019, csv after; the futures member is CD_NSE_FO*), UDiFF
    .../archives/cd/bhav/BhavCopy_NSE_CD_0_0_0_<yyyymmdd>_F_0000.csv.zip after. The archive starts in 2010-11/12
    (2008-08..2010-10 404s), so CDS history before that is unavailable here.
  * MCX commodity futures (FUTCOM): www.mcxindia.com bhavcopy page; its own GetData("/GetDateWiseBhavCopy") helper
    is called inside a playwright page (direct requests are refused). Volume = lots, VolumeInThousands = traded
    quantity with its unit, so lot quantity = quantity / lots (point-in-time). Value is read as Rs lakhs.
Units: `mult` = rupees per 1.0 price point per lot (NSE index: index units per lot; CDS: 1000, JPYINR quoted per 100
JPY on a 100,000 JPY lot; MCX: lot quantity x PRICE_UNIT conversion). `value` = rupee turnover. The report checks
value / (lots*close*mult) per symbol (~1 when units are right).
TICKS / PRICE_UNIT are today's contract specs, not point-in-time.  # ponytail: hand table; per-date ticks if E3 needs
Continuous series: per symbol, the held contract is the nearest expiry with more than ROLL sessions (of that symbol's
own trading dates) left to expiry, so rolls happen 5 sessions before expiry; never rolls backwards. adj_close is
ADDITIVELY back-adjusted (ratio breaks on negative prices, MCX crude 2020-04-20); P&L must use the real contracts.
Layout: data/futures/{nse,cds,mcx}/year=YYYY/<date>.parquet, manifests data/futures/<src>_manifest.csv,
data/futures/continuous.parquet, contracts.parquet (first listed / first traded date, mult, tick per contract), report.txt.
CLI: uv run --extra research python -m research.futures fetch nse|cds|mcx [start] [end]  |  build
"""
from __future__ import annotations

import asyncio
import glob
import io
import os
import struct
import sys
from bisect import bisect_right
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from research import bhavcopy

ROOT = Path("data/futures")
START, END = date(2004, 9, 1), date(2026, 9, 30)  # 60+ sessions before DEV 2005-01 for the turnover filter
ROLL = 5
NSE_SYMS = ("NIFTY", "BANKNIFTY")
CDS_SYMS = ("USDINR", "EURINR", "GBPINR", "JPYINR")
CDS_LEGACY_LAST = date(2024, 7, 5)
TICKS = {"NSE": 0.05, "CDS": 0.0025}
# MCX: tick (Rs) and price-unit conversion (lot quantity unit -> price quotation unit), current specs.
MCX_SPEC = {  # symbol: (tick, PRICE_UNIT)
    "GOLD": (1.0, 0.1), "GOLDM": (1.0, 0.1), "GOLDPETAL": (1.0, 1.0), "GOLDGUINEA": (1.0, 0.125),  # lot qty in g
    "SILVER": (1.0, 1.0), "SILVERM": (1.0, 1.0), "SILVERMIC": (1.0, 1.0),
    "CRUDEOIL": (1.0, 1.0), "CRUDEOILM": (1.0, 1.0), "NATURALGAS": (0.1, 1.0), "NATGASMINI": (0.1, 1.0),
    "COPPER": (0.05, 1.0), "ZINC": (0.05, 1.0), "ZINCMINI": (0.05, 1.0), "ALUMINIUM": (0.05, 1.0),
    "ALUMINI": (0.05, 1.0), "LEAD": (0.05, 1.0), "LEADMINI": (0.05, 1.0), "NICKEL": (0.1, 1.0),
}
SCHEMA = {"date": pl.Date, "exch": pl.Utf8, "symbol": pl.Utf8, "expiry": pl.Date, "open": pl.Float64,
          "high": pl.Float64, "low": pl.Float64, "close": pl.Float64, "settle": pl.Float64, "lots": pl.Int64,
          "value": pl.Float64, "oi": pl.Int64, "mult": pl.Float64, "unit": pl.Utf8, "implied": pl.Float64}


def _num(c: str) -> pl.Expr:
    return pl.col(c).str.strip_chars().cast(pl.Float64, strict=False)


def _udiff(df: pl.DataFrame, d: date, exch: str, tp: str, syms) -> pl.DataFrame:
    o = df.filter((pl.col("FinInstrmTp") == tp) & pl.col("TckrSymb").is_in(syms))
    lot = _num("NewBrdLotQty")
    return o.select(
        pl.lit(d).alias("date"), pl.lit(exch).alias("exch"), pl.col("TckrSymb").alias("symbol"),
        pl.col("XpryDt").str.to_date("%Y-%m-%d").alias("expiry"),
        _num("OpnPric").alias("open"), _num("HghPric").alias("high"), _num("LwPric").alias("low"),
        _num("ClsPric").alias("close"), _num("SttlmPric").alias("settle"),
        _num("TtlTradgVol").cast(pl.Int64).alias("lots"),
        (_num("TtlTrfVal") * (1e5 if exch == "CDS" else 1.0)).alias("value"),  # CD UDiFF value is in Rs lakhs
        _num("OpnIntrst").cast(pl.Int64).alias("oi"),
        (pl.lit(1000.0) if exch == "CDS" else lot).alias("mult"),  # CD NewBrdLotQty is 1; contract is 1000 units
        pl.lit(None, pl.Utf8).alias("unit"), pl.lit(None, pl.Float64).alias("implied")).cast(SCHEMA)


def _dmy(c: str) -> pl.Expr:
    """'31-May-2012', or '31-May-12' as in some legacy files (2012-05-14)."""
    e = pl.col(c).str.strip_chars()
    return pl.when(e.str.len_chars() == 9).then(e.str.to_date("%d-%b-%y", strict=False))         .otherwise(e.str.to_date("%d-%b-%Y", strict=False))


def parse_nse(raw: bytes, d: date) -> pl.DataFrame:
    df = pl.read_csv(io.BytesIO(raw), infer_schema_length=0)
    if "TckrSymb" in df.columns:
        return _udiff(df, d, "NSE", "IDF", NSE_SYMS)
    df = df.rename({c: c.strip() for c in df.columns}).unique(maintain_order=True)  # 2005 files repeat rows
    o = df.filter((pl.col("INSTRUMENT").str.strip_chars() == "FUTIDX") & pl.col("SYMBOL").is_in(NSE_SYMS))
    return o.select(
        pl.lit(d).alias("date"), pl.lit("NSE").alias("exch"), pl.col("SYMBOL").alias("symbol"),
        _dmy("EXPIRY_DT").alias("expiry"),
        _num("OPEN").alias("open"), _num("HIGH").alias("high"), _num("LOW").alias("low"),
        _num("CLOSE").alias("close"), _num("SETTLE_PR").alias("settle"),
        _num("CONTRACTS").cast(pl.Int64).alias("lots"), (_num("VAL_INLAKH") * 1e5).alias("value"),
        _num("OPEN_INT").cast(pl.Int64).alias("oi"), pl.lit(None, pl.Float64).alias("mult"),
        pl.lit(None, pl.Utf8).alias("unit"),
        (_num("VAL_INLAKH") * 1e5 / (_num("CONTRACTS") * _num("CLOSE"))).alias("implied")).cast(SCHEMA)


def _dbf(raw: bytes) -> pl.DataFrame:
    """dBase III table -> all-string DataFrame."""
    n, hlen, rlen = struct.unpack("<IHH", raw[4:12])
    fields, pos = [], 32
    while raw[pos] != 0x0D:
        fields.append((raw[pos:pos + 11].split(b"\0")[0].decode(), raw[pos + 16]))
        pos += 32
    rows = []
    for i in range(n):
        rec = raw[hlen + i * rlen: hlen + (i + 1) * rlen]
        if rec[:1] == b"*":  # deleted record
            continue
        o, r = 1, []
        for _, ln in fields:
            r.append(rec[o:o + ln].decode("latin-1").strip())
            o += ln
        rows.append(r)
    return pl.DataFrame(rows, schema=[f for f, _ in fields], orient="row")


def parse_cds(raw: bytes, d: date) -> pl.DataFrame:
    df = _dbf(raw) if raw[:1] in (b"\x03", b"\x83") else pl.read_csv(io.BytesIO(raw), infer_schema_length=0)
    if "TckrSymb" in df.columns:
        return _udiff(df, d, "CDS", "CDF", CDS_SYMS)
    df = df.rename({c: c.strip() for c in df.columns})
    k = pl.col("CONTRACT_D").str.strip_chars()
    o = df.with_columns(sym=k.str.slice(6, 6), exp=k.str.slice(12)).filter(
        k.str.starts_with("FUTCUR") & pl.col("sym").is_in(CDS_SYMS))
    return o.select(
        pl.lit(d).alias("date"), pl.lit("CDS").alias("exch"), pl.col("sym").alias("symbol"),
        _dmy("exp").alias("expiry"),
        _num("OPEN_PRICE").alias("open"), _num("HIGH_PRICE").alias("high"), _num("LOW_PRICE").alias("low"),
        _num("CLOSE_PRIC").alias("close"), _num("SETTLEMENT").alias("settle"),
        _num("TRADED_QUA").cast(pl.Int64).alias("lots"), _num("TRADED_VAL").alias("value"),
        _num("OI_NO_CON").cast(pl.Int64).alias("oi"), pl.lit(1000.0).alias("mult"),
        pl.lit(None, pl.Utf8).alias("unit"), pl.lit(None, pl.Float64).alias("implied")).cast(SCHEMA)


def cds_url(d: date) -> str:
    if d <= CDS_LEGACY_LAST:
        return f"https://nsearchives.nseindia.com/archives/cd/bhav/CD_Bhavcopy{d:%d%m%y}.zip"
    return f"https://nsearchives.nseindia.com/archives/cd/bhav/BhavCopy_NSE_CD_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def _cds_member(names: list[str]) -> str:
    return next((n for n in names if "_FO" in n.upper()), names[0])  # legacy zips also hold the options file


def parse_mcx(rows: list[dict]) -> pl.DataFrame:
    """MCX GetDateWiseBhavCopy rows -> SCHEMA (FUTCOM only)."""
    out = []
    for r in rows:
        if (r.get("InstrumentName") or "").strip() != "FUTCOM":
            continue
        sym = r["Symbol"].strip()
        qty, _, unit = (r.get("VolumeInThousands") or "").strip().partition(" ")
        lots = int(float(r.get("Volume") or 0))
        q = float(qty or 0)
        pu = MCX_SPEC.get(sym, (None, None))[1]
        out.append({"date": datetime.strptime(r["Date"].strip(), "%m/%d/%Y").date(), "exch": "MCX", "symbol": sym,
                    "expiry": datetime.strptime(r["ExpiryDate"].strip(), "%d%b%Y").date(),
                    "open": float(r["Open"]), "high": float(r["High"]), "low": float(r["Low"]),
                    "close": float(r["Close"]), "settle": float(r["Close"]), "lots": lots,
                    "value": float(r.get("Value") or 0) * 1e5, "oi": int(float(r.get("OpenInterest") or 0)),
                    "mult": round(q * 1000 / lots * pu, 6) if lots and pu else None, "unit": unit.strip() or None,
                    "implied": None})
    return pl.DataFrame(out, schema=SCHEMA)


_MCX_JS = """([d]) => new Promise(res => GetData("/GetDateWiseBhavCopy", "GET", {InstrumentName: "ALL", fromDate: d},
  r => res(r && Array.isArray(r.Data) ? r.Data : r && r.Message === "No data found." ? [] : "ERR"),
  () => res("ERR")))"""  # no-session days answer {IsSuccess:false, Message:"No data found.", Data:null}; else retry
WORKERS = 2  # 4 workers drew a 403 IP block after ~2,250 days (2026-10-18)
PAUSE = 1.0


async def _mcx_day(page, d: date, out: Path) -> str:
    data = await asyncio.wait_for(page.evaluate(_MCX_JS, [f"{d:%d/%m/%Y}"]), 60)
    if data == "ERR":
        raise RuntimeError("GetData error")
    df = parse_mcx(data)
    if df.is_empty():
        if d >= date.today() - timedelta(days=2):
            return "pending"  # not yet published: retried next run, never cached as a holiday
        return "holiday"  # ponytail: an empty day is a holiday, including FUTCOM-less special sessions
    path = out / f"year={d.year}" / f"{d:%Y-%m-%d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    return "ok"


async def _mcx_run(start: date, end: date, manifest: Path) -> None:
    from playwright.async_api import async_playwright
    done = bhavcopy._load_manifest(manifest)
    todo = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    queue = [d for d in todo if done.get(f"{d:%Y-%m-%d}") not in ("ok", "holiday")][::-1]
    async with async_playwright() as p:
        exe = sorted(glob.glob(os.path.expanduser("~/AppData/Local/ms-playwright/chromium-*/chrome-win64/chrome.exe")))
        b = await p.chromium.launch(headless=True, **({"executable_path": exe[-1]} if exe else {}))
        ctx = await b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

        n = bad = 0

        async def worker() -> None:
            nonlocal n, bad
            page = None
            while queue:
                d = queue.pop()
                status, empty = "error", 0
                for attempt in range(4):
                    try:
                        if page is None:
                            page = await ctx.new_page()
                            await page.goto("https://www.mcxindia.com/market-data/bhavcopy", timeout=90_000)
                            await page.wait_for_timeout(3000)
                        status = await _mcx_day(page, d, ROOT / "mcx")
                        if status == "holiday" and not empty:  # a transient empty reply cost 2005-12-16
                            empty = 1
                            raise RuntimeError("confirm holiday on a fresh page")
                        break
                    except Exception:  # noqa: BLE001 - page died, timed out or GetData failed: reopen and retry
                        status = "error"
                        if page is not None:
                            try:
                                await page.close()
                            except Exception:  # noqa: BLE001 - browser already gone
                                pass
                        page = None
                        await asyncio.sleep(5 * (attempt + 1))
                done[f"{d:%Y-%m-%d}"] = status
                await asyncio.sleep(PAUSE if status != "error" else 300)  # error = likely blocked: back off
                n += 1
                bad = bad + 1 if status == "error" else 0
                if bad >= 5:  # dead browser or IP block: stop; rerun resumes and retries the error days
                    print(f"{d}: 5 error days in a row, aborting", flush=True)
                    queue.clear()
                if n % 50 == 0:
                    bhavcopy._save(done, manifest)
                    print(d, flush=True)

        try:
            await asyncio.gather(*(worker() for _ in range(WORKERS)))
            await b.close()
        finally:
            bhavcopy._save(done, manifest)  # Ctrl-C or a crash keeps the progress made


def fetch(src: str, start: date = START, end: date = END) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = ROOT / f"{src}_manifest.csv"
    if src == "nse":
        bhavcopy.run(max(start, date(2005, 1, 1)), end, manifest=manifest, parser=parse_nse, out=ROOT / "nse")
    elif src == "cds":
        bhavcopy.run(max(start, date(2010, 11, 1)), end, manifest=manifest, url=cds_url, parser=parse_cds,
                     out=ROOT / "cds", member=_cds_member)
    else:
        asyncio.run(_mcx_run(start, end, manifest))


NSE_LOTS = {"NIFTY": (25.0, 50.0, 65.0, 75.0, 100.0, 200.0),  # every lot size used since 2005
            "BANKNIFTY": (15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 50.0, 100.0)}


def nse_lots(df: pl.DataFrame) -> pl.DataFrame:
    """Fill NSE legacy `mult` (lot size) from the implied lot; UDiFF rows keep the bhavcopy value."""
    near = pl.struct("symbol", "implied").map_elements(
        lambda r: min(NSE_LOTS[r["symbol"]], key=lambda x: abs(x - r["implied"])) if r["implied"] else None,
        return_dtype=pl.Float64)
    snap = pl.when(pl.col("lots") >= 10).then(near)
    # value is at traded prices, not the close: volatile days drift a bucket; keep the contract's mode unless the
    # day is >15% off it (real mid-contract lot changes, e.g. BANKNIFTY 100->50 in 2007, are much larger)
    m = snap.drop_nulls().mode().first().over("symbol", "expiry")
    snap = pl.when((snap / m - 1).abs() < 0.15).then(m).otherwise(snap)
    return (df.with_columns(mult=pl.coalesce("mult", snap))
            .sort("symbol", "expiry", "date")
            .with_columns(mult=pl.col("mult").forward_fill().backward_fill().over("symbol", "expiry"))
            .with_columns(mult=pl.coalesce("mult", pl.col("mult").drop_nulls().mode().first().over("symbol", "date"))))


def load(src: str) -> pl.DataFrame:
    df = (pl.read_parquet(str(ROOT / src / "year=*" / "*.parquet")).unique(maintain_order=True)  # MCX repeats rows
          .with_columns(pl.col("mult").round(6))  # older MCX files stored float-noisy mult
          )
    if src == "mcx":  # MCX prints a few rows after expiry (SOYSEED 2005-04-18); NSE's are postponed real expiries
        return df.filter(pl.col("date") <= pl.col("expiry"))  # (2005-07-29 floods, 2008-11-28 after 26/11)
    return nse_lots(df) if src == "nse" else df


def monthly(df: pl.DataFrame, min_share: float = 0.1) -> pl.DataFrame:
    """Drop CDS weeklies (2021+; before or after the monthly, e.g. USDINR 2022-04-29 vs monthly 04-27): an expiry
    keeps rows only if its lifetime lots are >= min_share of the month's top expiry (weeklies <= ~5%). Then per day
    keep the last surviving expiry of each month, so a re-dated monthly (BANKNIFTY 2025-01-29 -> 01-30, share 0.43)
    is kept on the days it alone is quoted."""
    m = pl.col("expiry").dt.truncate("1mo")
    tot = pl.col("lots").sum().over("symbol", "expiry")
    df = df.filter(tot >= min_share * tot.max().over("symbol", m))
    return df.filter(pl.col("expiry") == pl.col("expiry").max().over("symbol", "date", m))


def continuous(df: pl.DataFrame, roll: int = ROLL) -> pl.DataFrame:
    """One symbol's contract rows -> one row per trading date: held contract, its close, additive adj_close."""
    # untraded rows: settle (legacy CDS leaves close empty; UDiFF CDS repeats a stale last trade, JPYINR 2026-07-24)
    px = df.with_columns(close=pl.when(pl.col("lots") > 0).then("close").otherwise(pl.coalesce("settle", "close"))).filter(
        pl.col("close").is_not_null() & (pl.col("close") != 0))
    cal = sorted(px["date"].unique())
    by: dict[date, dict[date, float]] = {}
    for d, e, c in px.select("date", "expiry", "close").iter_rows():
        by.setdefault(d, {})[e] = c
    rows, gaps, held = [], [], None
    for i, d in enumerate(cal):
        def left(e: date) -> float:
            if e <= cal[-1]:
                return bisect_right(cal, e) - 1 - i
            # past the loaded data: count weekdays as sessions so the tail still rolls on time
            return len(cal) - 1 - i + sum((cal[-1] + timedelta(k)).weekday() < 5 for k in range(1, (e - cal[-1]).days + 1))
        # never roll back a month; same month allowed so a re-date earlier (BANKNIFTY 2024-03-28 -> 03-27) is followed
        ok = sorted(e for e in by[d] if left(e) > roll and (held is None or (e.year, e.month) >= (held.year, held.month)))
        pick = ok[0] if ok else held if held in by[d] else None
        if pick is None:
            continue  # nothing tradable with > roll sessions left: a gap, counted in the report
        if held is not None and pick != held:
            # gap measured on the last day both were quoted, so it never mixes two dates' prices
            dc = next((x for x in reversed(cal[:i + 1]) if held in by[x] and pick in by[x]), None)
            if dc:
                gaps.append((d, by[dc][pick] - by[dc][held]))
            elif abs((pick - held).days) > 7:  # never co-quoted: stale fallback (illiquid MCX only)
                gaps.append((d, by[d][pick] - next(r[2] for r in reversed(rows) if r[1] == held)))
            else:  # re-dated contract (expiry weekday change): same instrument, no gap
                gaps.append((d, 0.0))
        held = pick
        rows.append((d, pick, by[d][pick]))
    adj, j, shift = [], len(gaps) - 1, 0.0
    for d, e, c in reversed(rows):
        adj.append(c + shift)
        while j >= 0 and gaps[j][0] == d:  # rolls on d shift everything strictly before d
            shift += gaps[j][1]
            j -= 1
    return pl.DataFrame({"date": [r[0] for r in rows], "expiry": [r[1] for r in rows],
                         "close": [r[2] for r in rows], "adj_close": adj[::-1],
                         "roll": [r[0] in {g[0] for g in gaps} for r in rows]},
                        schema={"date": pl.Date, "expiry": pl.Date, "close": pl.Float64, "adj_close": pl.Float64,
                                "roll": pl.Boolean})


def contracts(df: pl.DataFrame) -> pl.DataFrame:
    """First listed / first traded date per contract; `censored` = listed on the source's first date."""
    first = df["date"].min()
    return (df.group_by("exch", "symbol", "expiry").agg(
        first_listed=pl.col("date").min(), first_traded=pl.col("date").filter(pl.col("lots") > 0).min(),
        last_date=pl.col("date").max(), mult=pl.col("mult").drop_nulls().last())
        .with_columns(censored=pl.col("first_listed") == first, tick=pl.col("exch").replace_strict(TICKS, default=None)
                      .fill_null(pl.col("symbol").replace_strict({k: v[0] for k, v in MCX_SPEC.items()}, default=None)))
        .sort("exch", "symbol", "expiry"))


def build() -> str:
    lines, conts, cons = [f"A5 futures data - generated {date.today()}."], [], []
    for src in ("nse", "cds", "mcx"):
        if not (ROOT / src).exists():
            lines.append(f"{src.upper()}: not fetched")
            continue
        df = load(src)
        if src == "cds":
            lines.append("\nCDS unavailable before 2010-11: archive 404s (USDINR listed 2008-08, EUR/GBP/JPYINR 2010-02)")
        man = bhavcopy._load_manifest(ROOT / f"{src}_manifest.csv")
        st = pl.Series(list(man.values()))
        lines.append(f"\n{src.upper()}: {df.height} rows, {df['date'].n_unique()} sessions "
                     f"{df['date'].min()}..{df['date'].max()}; manifest " +
                     ", ".join(f"{k}={v}" for k, v in st.value_counts().iter_rows()))
        errs = sorted(k for k, v in man.items() if v == "error")
        if errs:
            lines.append(f"  error days ({len(errs)}): {', '.join(errs[:20])}{' ...' if len(errs) > 20 else ''}")
        hol = [date.fromisoformat(k) for k, v in man.items() if v == "holiday"]
        wk = pl.DataFrame({"d": [d for d in hol if d.weekday() < 5]}, schema={"d": pl.Date})
        lines.append("  weekday holidays by year: " + ", ".join(
            f"{y}:{n}" for y, n in wk.group_by(pl.col("d").dt.year()).len().sort("d").iter_rows()))
        sessions = sorted(df["date"].unique())
        conts.append(contracts(df))
        for (sym,), g in sorted(df.group_by("symbol"), key=lambda x: x[0]):
            c = continuous(monthly(g)).with_columns(exch=pl.lit(src.upper()), symbol=pl.lit(sym))
            if c.is_empty():  # never priced with > ROLL sessions left (e.g. short-lived products)
                lines.append(f"  {sym}: no continuous series ({g.height} rows, {g['expiry'].n_unique()} contracts)")
                continue
            cons.append(c)
            s0 = c["date"].min()
            miss = [d for d in sessions if d >= s0 and d <= c["date"].max()]
            gap = sorted(set(miss) - set(c["date"]))
            traded = g.filter(pl.col("lots") > 0)
            chk = traded.filter(pl.col("mult").is_not_null() & (pl.col("close") > 0)).with_columns(
                r=pl.col("value") / (pl.col("lots") * pl.col("close") * pl.col("mult")))
            mults = g.group_by(pl.col("date").dt.year().alias("y")).agg(pl.col("mult").drop_nulls().unique().sort())
            tv = traded.group_by("date").agg(v=pl.col("value").sum())["v"]
            ry = chk.group_by(pl.col("date").dt.year()).agg(pl.col("r").median())["r"]
            yr = f"{ry.min():.3f}..{ry.max():.3f}" if ry.len() else "n/a"
            lines.append(
                f"  {sym}: {s0}..{c['date'].max()} {c.height} sessions, gaps {len(gap)}"
                f"{' (' + ', '.join(map(str, gap[:8])) + (' ...' if len(gap) > 8 else '') + ')' if gap else ''}, "
                f"rolls {c['roll'].sum()}, contracts {g['expiry'].n_unique()}, "
                f"value/(lots*close*mult) median by year {yr}, "
                f"median daily turnover Rs{(tv.median() or 0) / 1e7:,.1f} cr, "
                f"tick {TICKS.get(src.upper()) or MCX_SPEC.get(sym, ('n/a',))[0]}")
            if mults["mult"].list.len().sum() == 0:
                lines.append("    mult unavailable: symbol not in MCX_SPEC (PRICE_UNIT unknown), lots/value still valid")
                continue
            lines.append("    mult by year: " + "; ".join(
                f"{y}:{','.join(f'{m:g}' for m in ms[:4])}{'..' if len(ms) > 4 else ''}"
                for y, ms in mults.sort("y").iter_rows()))
    pl.concat(cons, how="diagonal").select("exch", "symbol", "date", "expiry", "close", "adj_close", "roll") \
        .write_parquet(ROOT / "continuous.parquet")
    pl.concat(conts).write_parquet(ROOT / "contracts.parquet")
    text = "\n".join(lines) + "\n"
    (ROOT / "report.txt").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    if sys.argv[1] == "fetch":
        a = [date.fromisoformat(x) for x in sys.argv[3:5]]
        fetch(sys.argv[2], *a)
    else:
        print(build())
