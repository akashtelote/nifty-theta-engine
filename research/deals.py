"""NSE bulk and block deal history -> Parquet (plan 20261017 E1-E4, task A6; used by E4).

Source (probed 2026-10-18): https://www.nseindia.com/api/historicalOR/bulk-block-short-deals
  ?optionType=bulk_deals|block_deals&from=DD-MM-YYYY&to=DD-MM-YYYY&csv=true
  * scripted HTTP gets 503 (bot wall); the request is made from inside a browser page on nseindia.com (playwright).
  * the JSON form is capped at 70 rows per response (even for one busy day); the csv=true form is complete
    (2016 block: 183 rows = sum of monthly JSON). Ranges over 1 year return 500, so we fetch one month per request.
  * bulk deals from 2004-01, block deals from 2005-11 (the block window opened then; earlier months are empty).
Shares outstanding (also A6): NSE's shareholding master only goes back to 2021-09 and gives percentages (counts are in
per-filing XBRL), so there is no point-in-time source for DEV; E4 runs its fallback rule.

Layout: data/deals/raw/<kind>/<YYYY-MM>.csv (cache; a month is re-fetched only if missing),
        data/deals/deals.parquet, data/deals/report.txt
CLI: uv run --extra research python -m research.deals   (resumable)
"""
from __future__ import annotations

import asyncio
import glob
import io
import os
from calendar import monthrange
from datetime import date
from pathlib import Path

import polars as pl

ROOT = Path("data/deals")
KINDS = ("bulk_deals", "block_deals")
START, END = date(2004, 1, 1), date(2026, 9, 30)
LANDING = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
API = ("https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
       "?optionType={kind}&from={a:%d-%m-%Y}&to={b:%d-%m-%Y}&csv=true")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FETCH_JS = "async u => { const r = await fetch(u, {headers: {accept: 'text/csv'}}); return [r.status, await r.text()]; }"
COLS = {"Date": "date", "Symbol": "symbol", "Security Name": "name", "Client Name": "client", "Buy / Sell": "side",
        "Quantity Traded": "qty", "Trade Price / Wght. Avg. Price": "price", "Remarks": "remarks"}


def months(start: date = START, end: date = END) -> list[tuple[date, date]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((date(y, m, 1), min(date(y, m, monthrange(y, m)[1]), end)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def raw_path(kind: str, a: date) -> Path:
    return ROOT / "raw" / kind / f"{a:%Y-%m}.csv"


def parse(text: str, kind: str) -> pl.DataFrame:
    """One month's CSV -> typed rows. Header names carry trailing spaces; quantities use Indian digit grouping."""
    df = pl.read_csv(io.StringIO(text), infer_schema=False)
    df = df.rename({c: COLS[c.strip()] for c in df.columns})
    return df.select(
        pl.col("date").str.strip_chars().str.to_titlecase().str.to_date("%d-%b-%Y"),
        pl.col("symbol").str.strip_chars(),
        pl.col("name").str.strip_chars(),
        pl.col("client").str.strip_chars().str.replace_all(r"\s+", " "),
        pl.col("side").str.strip_chars().str.to_uppercase()  # a few early rows say B / S / SOLD
        .replace({"B": "BUY", "S": "SELL", "SOLD": "SELL", "BOUGHT": "BUY"}),
        pl.col("qty").str.replace_all(",", "").cast(pl.Int64),
        pl.col("price").str.replace_all(",", "").cast(pl.Float64),
        pl.col("remarks").str.strip_chars(),
        pl.lit(kind.split("_")[0]).alias("kind"),
    )


async def _fetch(todo: list[tuple[str, date, date]]) -> list[str]:
    from playwright.async_api import Error, async_playwright

    failed = []
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Error:  # this playwright's browser build not downloaded: use the newest installed chromium
            exe = sorted(glob.glob(os.path.expanduser("~/AppData/Local/ms-playwright/chromium-*/chrome-win64/chrome.exe")))
            if not exe:
                raise
            browser = await p.chromium.launch(headless=True, executable_path=exe[-1])
        page = await (await browser.new_context(user_agent=UA)).new_page()
        await page.goto(LANDING, timeout=60_000)
        await page.wait_for_timeout(3000)
        for kind, a, b in todo:
            for attempt in range(3):
                status, text = await page.evaluate(FETCH_JS, API.format(kind=kind, a=a, b=b))
                if status == 200 and text.lstrip().startswith('"Date'):
                    raw_path(kind, a).parent.mkdir(parents=True, exist_ok=True)
                    raw_path(kind, a).write_text(text, encoding="utf-8")
                    break
                if status == 200 and not text.strip():  # month without deals
                    raw_path(kind, a).parent.mkdir(parents=True, exist_ok=True)
                    raw_path(kind, a).write_text("", encoding="utf-8")
                    break
                await page.goto(LANDING, timeout=60_000)  # refresh cookies, then retry
                await page.wait_for_timeout(3000 * (attempt + 1))
            else:
                failed.append(f"{kind} {a:%Y-%m}: {status} {text[:80]!r}")
            await page.wait_for_timeout(800)
        await browser.close()
    return failed


def fetch() -> list[str]:
    todo = [(k, a, b) for k in KINDS for a, b in months() if not raw_path(k, a).exists()]
    return asyncio.run(_fetch(todo)) if todo else []


def build() -> pl.DataFrame:
    frames = [parse(t, k) for k in KINDS for a, _ in months()
              if raw_path(k, a).exists() and (t := raw_path(k, a).read_text(encoding="utf-8")).strip()]
    return pl.concat(frames).sort("date", "kind", "symbol")


def report(deals: pl.DataFrame, failed: list[str]) -> str:
    from research import equity

    eq = equity.load(START, END).select("date", "symbol").unique()
    first = eq["date"].min()  # no bhavcopy calendar before this (2004 deals cannot be checked)
    sessions = set(eq["date"].to_list())
    missing = [f"{k} {a:%Y-%m}" for k in KINDS for a, _ in months() if not raw_path(k, a).exists()]
    have = set(deals.select(pl.col("kind") + "_deals", pl.col("date").dt.strftime("%Y-%m")).unique().iter_rows())
    empty = [f"{k} {a:%Y-%m}" for k in KINDS for a, _ in months() if (k, f"{a:%Y-%m}") not in have]
    checked = deals.filter(pl.col("date") >= first)
    off = checked.filter(~pl.col("date").is_in(list(sessions)))
    unmatched = checked.join(eq, on=["date", "symbol"], how="anti")
    never = unmatched.filter(~pl.col("symbol").is_in(eq["symbol"].unique().to_list())).height
    per_year = (deals.group_by(pl.col("date").dt.year().alias("year"), "kind").len()
                .pivot(on="kind", index="year", values="len").sort("year"))
    years = deals.filter(pl.col("kind") == "bulk")["date"].dt.year().n_unique()
    lines = [f"A6 bulk/block deals {START}..{END}. Generated {date.today()}.",
             f"rows {deals.height} (bulk {deals.filter(pl.col('kind') == 'bulk').height}, "
             f"block {deals.filter(pl.col('kind') == 'block').height}); calendar years with bulk deals: {years}",
             f"DONE-WHEN (>= 5 years of daily deal history): {'met' if years >= 5 else 'NOT met'}",
             f"fetch failures: {len(failed)}" + "".join(f"\n  {f}" for f in failed),
             f"months not fetched: {len(missing)} {missing[:12]}",
             f"months with no deals: {len(empty)} {empty[:40]}",
             f"exact duplicate rows (kept): {deals.height - deals.unique().height}",
             f"rows from {first} dated on a non-session day (vs equity bhavcopy calendar): {off.height} "
             f"{sorted(set(off['date'].to_list()))[:12]}; rows before {first} not checked: {deals.height - checked.height}",
             f"rows from {first} whose (date, symbol) has no EQ/BE bhavcopy row: {unmatched.height} "
             f"({unmatched.height / checked.height:.1%}); of which symbol never EQ/BE (SME/other series): {never}; "
             f"by kind {dict(unmatched.group_by('kind').len().iter_rows())}",
             "shares outstanding: no point-in-time source for DEV (NSE shareholding master 2021-09+, % only) -> "
             "E4 fallback rule", "", "rows per year:", str(per_year)]
    return "\n".join(lines) + "\n"


def main() -> None:
    failed = fetch()
    deals = build()
    ROOT.mkdir(parents=True, exist_ok=True)
    deals.write_parquet(ROOT / "deals.parquet")
    text = report(deals, failed)
    (ROOT / "report.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
