"""Macro / NSE event blackout calendar for PCS entry skips (PROF-018).

Dates are approximate scheduled risk windows (RBI policy, Union Budget).
Extend this list as calendars are published each year.
"""

from __future__ import annotations

from datetime import date, timedelta

# Known high-impact Indian macro dates (extend yearly)
EVENT_DATES: tuple[date, ...] = (
    # Union Budget
    date(2025, 2, 1),
    date(2026, 2, 1),
    date(2027, 2, 1),
    # RBI MPC policy (approximate mid-cycle announcements — update as scheduled)
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
    date(2026, 10, 1),
    date(2026, 12, 4),
    date(2027, 2, 5),
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
