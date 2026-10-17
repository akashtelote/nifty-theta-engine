from datetime import date

import polars as pl

from research import events


def test_calendar_loads_and_is_sane():
    ev = events.load()
    assert set(ev["type"]) == {"rbi", "fomc", "budget", "election"}
    # budgets/elections are announced only weeks ahead, so a blank `announced` would be lookahead
    late = ev.filter(pl.col("type").is_in(["budget", "election"]))
    assert late["announced"].null_count() == 0 and (late["announced"] < late["date"]).all()
    assert ev["source"].null_count() == 0 and ev.height == ev.unique(["date", "type"]).height
    assert ev.filter((pl.col("type") == "budget") & (pl.col("date") == date(2024, 7, 23))).height == 1
    assert not ev.filter((pl.col("type") == "rbi") & (pl.col("date") == date(2020, 3, 27)))["scheduled"][0]
    oct20 = ev.filter((pl.col("type") == "rbi") & pl.col("date").is_between(date(2020, 10, 1), date(2020, 10, 9)))
    assert oct20["held"].to_list() == [False, True] and oct20["announced"][1] == date(2020, 10, 6)


def test_session_mapping():
    ev = events.load().filter(((pl.col("date") == date(2023, 2, 1)) & (pl.col("type") == "budget")) |
                              (pl.col("date") == date(2023, 3, 22)))
    assert ev.height == 2
    s = dict(zip(ev["type"], events.with_session(ev, [date(2023, 2, 1), date(2023, 3, 22), date(2023, 3, 23)])["session"]))
    assert s["budget"] == date(2023, 2, 1)  # intraday: same session
    assert s["fomc"] == date(2023, 3, 23)  # US decision on the 22nd trades on the 23rd in India
