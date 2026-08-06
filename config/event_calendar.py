"""Macro / NSE event blackout calendar for PCS entry skips (PROF-018).

Dates are the *announcement* day of each scheduled risk window (RBI MPC
resolution day, Union Budget). RBI publishes the MPC calendar for a fiscal
year in advance under s.45ZI of the RBI Act — verify against it each year
rather than extrapolating from the previous year's pattern.

FY2026-27 verified against the calendar RBI released 2026-03-23:
Apr 6-8, Jun 3-5, Aug 3-5, Oct 5-7, Dec 2-4 (2026), Feb 3-5 (2027);
the resolution is announced on the third day of each meeting.
"""

from __future__ import annotations

from datetime import date, timedelta

# Known high-impact Indian macro dates (extend yearly)
EVENT_DATES: tuple[date, ...] = (
    # Union Budget
    date(2025, 2, 1),
    date(2026, 2, 1),
    date(2027, 2, 1),
    # RBI MPC resolution days (FY2025-26 historical; FY2026-27 per RBI calendar)
    date(2025, 2, 7),
    date(2025, 4, 9),
    date(2025, 6, 6),
    date(2025, 8, 6),
    date(2025, 10, 1),
    date(2025, 12, 5),
    date(2026, 2, 6),
    date(2026, 4, 8),
    date(2026, 6, 5),
    date(2026, 8, 5),
    date(2026, 10, 7),
    date(2026, 12, 4),
    date(2027, 2, 5),
    # FY2027-28: unpublished at time of writing — add when RBI releases it.
)


def in_event_blackout(
    on: date,
    events: tuple[date, ...] = EVENT_DATES,
    days_before: int = 1,
    days_after: int = 1,
) -> tuple[bool, date | None]:
    """True if ``on`` falls within [event - before, event + after] for any event."""
    for ev in events:
        start = ev - timedelta(days=max(days_before, 0))
        end = ev + timedelta(days=max(days_after, 0))
        if start <= on <= end:
            return True, ev
    return False, None
