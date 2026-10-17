"""Point-in-time macro event calendar (Phase A5 of docs/plans/20261017-next-hypotheses-plan.md).

research/events.csv, one row per event, every date taken from a primary or cited source (column `source`):
  rbi       RBI policy decisions 2011+ (rbi.org.in); scheduled=False for off-cycle moves (e.g. 2020-03-27)
  fomc      scheduled FOMC decisions (federalreserve.gov), US date; announced after the NSE close
            (22:00-00:30 IST depending on year and US DST)
  budget    Union Budgets incl. interims (some were presented in special weekend sessions)
  election  Lok Sabha result days
`timing` says which NSE session first trades the news: intraday = that day's session (or the next one if the
market was shut), after_close = the next session after the date.

Point-in-time columns. scheduled=False rows (off-cycle RBI moves, the two March 2020 emergency FOMC cuts) were not
knowable in advance. held=False rows are scheduled meetings that did not happen on that date (FOMC 2020-03-18
cancelled; RBI 2020-10-01 postponed on 2020-09-28): an ex-ante calendar shows them, an ex-post one must not.
`announced` = when the date became public. Blank only for RBI/FOMC meetings on the published annual calendar
(months ahead). Elections use the ECI schedule date; budgets use date-14d, a deliberately late proxy (real notice
was longer), so an ex-ante filter never sees a budget before it was public. India CPI is not included yet (plan amendment, see the plan's Phase A notes).
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date
from pathlib import Path

import polars as pl

CSV = Path(__file__).with_name("events.csv")


def load() -> pl.DataFrame:
    return pl.read_csv(CSV, try_parse_dates=True).with_columns(pl.col("scheduled", "held").cast(pl.Boolean))


def with_session(ev: pl.DataFrame, trading_days: list[date]) -> pl.DataFrame:
    """Add `session`: the first NSE trading day whose close reflects the event (null past the last known day)."""
    days = sorted(trading_days)

    def first(d: date, timing: str) -> date | None:
        i = bisect_right(days, d) if timing == "after_close" else bisect_left(days, d)
        return days[i] if i < len(days) else None

    return ev.with_columns(session=pl.Series([first(d, t) for d, t in zip(ev["date"], ev["timing"])], dtype=pl.Date))
