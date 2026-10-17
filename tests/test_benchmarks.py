from datetime import date

import pytest

from research.benchmarks import check_gaps, parse, parse_tbill


def test_parse_price_and_tri():
    p = parse([{"HistoricalDate": "03 Jan 2005", "OPEN": "1,818.55", "HIGH": "1836.65", "LOW": "1816.60",
                "CLOSE": "1834.75", "INDEX_NAME": "Nifty 500"},
               {"HistoricalDate": "03 Jan 2005", "OPEN": "1818.55", "HIGH": "1836.65", "LOW": "1816.60",
                "CLOSE": "1834.75", "INDEX_NAME": "Nifty 500"}], "price")
    assert p.height == 1 and p.row(0) == (date(2005, 1, 3), 1818.55, 1836.65, 1816.6, 1834.75)
    t = parse([{"Date": "04 Jan 2005", "TotalReturnsIndex": "-"},
               {"Date": "03 Jan 2005", "TotalReturnsIndex": "2282.29"}], "tri")
    assert t["date"].to_list() == [date(2005, 1, 3), date(2005, 1, 4)] and t["tri"].to_list() == [2282.29, None]
    assert parse([], "tri").columns == ["date", "tri"]


def test_parse_rejects_conflicting_duplicates():
    with pytest.raises(ValueError):
        parse([{"Date": "03 Jan 2005", "TotalReturnsIndex": "100"},
               {"Date": "03 Jan 2005", "TotalReturnsIndex": "101"}], "tri")


def test_check_gaps_flags_missing_null_head_and_tail():
    t = parse([{"Date": "03 Jan 2005", "TotalReturnsIndex": "1"}, {"Date": "04 Jan 2005", "TotalReturnsIndex": "-"},
               {"Date": "06 Jan 2005", "TotalReturnsIndex": "2"}], "tri")
    days = [date(2004, 12, 31)] + [date(2005, 1, d) for d in (3, 4, 5, 6, 7)]
    assert check_gaps(t, days, "tri") == [date(2004, 12, 31), date(2005, 1, 4), date(2005, 1, 5), date(2005, 1, 7)]
    assert check_gaps(parse([], "tri"), [date(2005, 1, 3)], "tri") == [date(2005, 1, 3)]


def test_parse_tbill_keeps_15to91_bucket_and_rejects_dupes():
    cols = ["src_line", "mat_term_d_rn", "time_period", "obs_value"]
    rows = [[2, "15TO91", "2005-02-28", 5.0448], [1, "15TO91", "2005-01-31", 5.141], [3, "92TO182", "2005-01-31", 5.3]]
    t = parse_tbill(cols, rows)
    assert t.rows() == [(date(2005, 1, 31), 5.141), (date(2005, 2, 28), 5.0448)]
    with pytest.raises(ValueError):
        parse_tbill(cols, rows + [[4, "15TO91", "2005-01-31", 5.2]])


def test_parse_tbill_requires_contiguous_months_from_2005():
    cols = ["src_line", "mat_term_d_rn", "time_period", "obs_value"]
    with pytest.raises(ValueError):  # 2005-02 missing
        parse_tbill(cols, [[1, "15TO91", "2005-01-31", 5.1], [2, "15TO91", "2005-03-31", 5.2]])
    with pytest.raises(ValueError):  # starts after 2005-01
        parse_tbill(cols, [[1, "15TO91", "2005-02-28", 5.1]])
    assert parse_tbill(cols, [[1, "15TO91", "2004-08-31", 5.0], [2, "15TO91", "2005-01-31", 5.1]]).height == 2
