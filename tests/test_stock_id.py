from datetime import date, timedelta

import polars as pl

from research.stock_id import assign, build, parse_symbol_changes

D = [date(2011, 1, 3) + timedelta(i) for i in range(80)]  # every day a session while a filler trades


def rows(*spec):
    """spec: (symbol, isin, first_day_index, last_day_index)"""
    return pl.DataFrame([(D[i], s, isin) for s, isin, a, b in spec for i in range(a, b + 1)],
                        schema={"date": pl.Date, "symbol": pl.Utf8, "isin": pl.Utf8}, orient="row")


CHANGES = parse_symbol_changes(b"NAME OF THE COMPANY,OLD SYMBOL,NEW SYMBOL,EFFECTIVE DATE\n"
                               b"Foo Ltd, OLDF ,NEWF,20-JUN-2011\nBar Ltd,BARX,BARY,23-JUN-2011\n")


def test_chains_rename_isin_switch_and_face_value_split():
    r = rows(("OLDF", None, 0, 0), ("NEWF", None, 1, 2), ("NEWF", "INE111A01011", 3, 4),
             ("NEWF", "INE111A01029", 5, 6),                       # split: same chars 3-9, next session
             ("ZZZ", "INE222B01011", 3, 6))                        # unrelated
    ids, links, amb = build(r, CHANGES)
    assert set(assign(r, ids).filter(pl.col("symbol") != "ZZZ")["perm_id"]) == {"INE111A01029"}
    assert links.height == 3 and amb.is_empty()
    assert ids.filter(pl.col("node") == "INE222B01011")["perm_id"].item() == "INE222B01011"


def test_no_link_on_gap_other_issuer_or_ambiguity():
    r = rows(("AAA", "INE333C01011", 0, 2), ("AAA", "INE333C01029", 4, 6),     # gap day -> no link
             ("BBB", "INE444D01011", 0, 2), ("BBB", "INE555E01011", 3, 6),     # issuer differs
             ("CCC", None, 0, 2), ("CCC", "INE666F01011", 3, 6), ("CCC", "INE666F01029", 3, 6))  # two heirs
    ids, links, amb = build(r, CHANGES)
    assert links.is_empty() and amb.height == 2 and build(r.clear(), CHANGES)[0].is_empty()
    assert (ids["node"] == ids["perm_id"]).all()


FILL = [(f"F{j}", f"INE9{j:02d}Z01011", 0, 79) for j in range(12)]  # 12 rows on every normal session


def test_sym_links_tolerate_gaps_up_to_cap_nearest_wins():
    r = rows(("THIN", None, 0, 1), ("THIN", "INE777G01011", 30, 32),     # 28 missing -> linked
             ("GONE", None, 0, 0), ("GONE", "INE888H01011", 62, 63),     # 61 missing -> not
             ("SPLT", None, 0, 2), ("SPLT", "INE123K01011", 4, 4), ("SPLT", "INE123K01029", 5, 6),  # nearest
             ("BARX", None, 0, 3), ("BARY", None, 9, 12), *FILL)          # rename after 5 missing
    _, links, amb = build(r, CHANGES)
    assert sorted(links.rows()) == [("INE123K01011", "INE123K01029", 0), ("SYM:BARX", "SYM:BARY", 5),
                                    ("SYM:SPLT", "INE123K01011", 1), ("SYM:THIN", "INE777G01011", 28)]
    assert amb.is_empty()


def test_near_empty_special_session_is_not_a_session():
    r = rows(("AAA", "INE333C01011", 0, 2), ("XTRA", "INE321Q01011", 3, 3),  # 1-row special day 3
             ("AAA", "INE333C01029", 4, 6), *FILL)
    r = r.filter(~((pl.col("date") == D[3]) & pl.col("symbol").str.starts_with("F")))
    _, links, _ = build(r, CHANGES)
    assert links.rows() == [("INE333C01011", "INE333C01029", 0)]


def test_pre_isin_rename_needs_list_pair():
    r = rows(("BARX", None, 0, 3), ("BARY", None, 4, 6), ("QQQ", None, 0, 3), ("RRR", None, 4, 6))
    ids, links, _ = build(r, CHANGES)
    assert links.rows() == [("SYM:BARX", "SYM:BARY", 0)]
