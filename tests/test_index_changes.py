from datetime import date

import polars as pl

from research import index_changes as ic


def L(*words):
    """A line of words placed left to right; a word given as (text, x) keeps its x."""
    out, x = [], 50.0
    for w in words:
        t, x = (w if isinstance(w, tuple) else (w, x))
        out.append((t, x))
        x += 60
    return out


def test_sections_symbol_column_and_kinds():
    ls = [L("Date:", "February", "22,", "2016"),
          L("periodic", "review.", "effective", "from", "April", "1,", "2016"),
          L("A.", "Semi-Annual", "Review:"),
          L("1)", "Nifty", "50", "Index"),
          L("The", "following", "scrips", "are", "being", "excluded:"),
          L("Sr.", "No.", "Scrip", "Name", ("Symbol", 400)),
          L("1", "Cairn", "India", "Ltd.", ("CAIRN", 400)),
          L("The", "following", "scrips", "are", "being", "included:"),
          L("Sr.", "No.", "Scrip", "Name", ("Symbol", 407)),  # centred heading, symbols start left of it
          L("1", "Eicher", "Motors", "Ltd.", ("EICHERMOT", 384)),
          L("2)", "Nifty", "Equal", "Weight", "Index"),
          L("The", "following", "scrip", "is", "being", "included:"),
          L("Sr.", "No.", "Name", ("Symbol", 400)),
          L("1", "Some", "Co", ("SOMECO", 400)),
          L("B.", "Replacements", "on", "account", "of", "revision", "in", "criteria:"),
          L("3)", "Nifty", "Free", "Float", "Midcap", "100", "Index", "(Formerly", "Nifty", "Midcap", "100)"),
          L("The", "following", "scrip", "is", "being", "excluded:"),
          L("Sr.", "No.", "Name", ("Symbol", 400)),
          L("1",),  # a lone serial joins the next line
          L(("Foo", 110), ("Ltd.", 170), ("FOO", 400))]
    rows, facts = ic.parse(ls)
    assert facts == {"announced_pdf": date(2016, 2, 22), "effective_dates": [date(2016, 4, 1)], "kind": "scheduled"}
    got = [(r["index"], r["side"], r["name"], r["symbol"], r["kind"]) for r in rows]
    assert got == [("NIFTY50", "remove", "Cairn India Ltd.", "CAIRN", "scheduled"),
                   ("NIFTY50", "add", "Eicher Motors Ltd.", "EICHERMOT", "scheduled"),
                   ("other:2) Nifty Equal Weight Index", "add", "Some Co", "SOMECO", "scheduled"),
                   ("MIDCAP100", "remove", "Foo Ltd.", "FOO", "criteria_revision")]


def test_prose_index_and_name_only():
    ls = [L("The", "Committee", "has", "decided", "to", "make", "the", "following", "change", "in"),
          L("S&P", "CNX", "500", "Index", "which", "will", "become", "effective", "from", "May", "18,", "2011:"),
          L("The", "following", "company", "is", "being", "excluded:"),
          L("Sr.", "No.", "Company", "Name"),
          L("1", "Binani", "Cement", "Ltd.")]
    rows, facts = ic.parse(ls)
    assert facts["kind"] == "ad_hoc"
    assert [(r["index"], r["side"], r["name"], r["symbol"], r["effective"]) for r in rows] == \
        [("NIFTY500", "remove", "Binani Cement Ltd.", None, date(2011, 5, 18))]
    assert ic.PROSE.findall("change in CNX Nifty Junior index; Nifty 50 Equal Weight") == ["CNX Nifty Junior"]


def test_subheaders_notes_serials_and_row_dates():
    ls = [L("Mumbai,", "August", "23,", "2024"),
          L("effective", "from", "September", "30,", "2024"),
          L("1)", "Replacements", "on", "account", "of", "semi-annual", "review:"),
          L("a)", "Nifty", "Next", "50"),
          L("The", "following", "companies", "are", "being", "excluded:"),
          L("Sr.", "No.", "Company", "Name", ("Symbol", 400), ("Effective", 460), ("Date", 510)),
          L("1", "Zuari", "Ltd.", ("ZUARI", 365), ("April", 465), ("9,", 494), ("2012", 506)),
          L("2", ("JCHAC", 365)),  # name wrapped onto the next line
          L("Note:"),
          L("1.", "InterGlobe", "Aviation", "Ltd.", "has", "been", "removed", "from", "Nifty", "Next", "50"),
          L("The", "following", "companies", "are", "being", "included:"),
          L("Sr.", "No.", "Company", "Name", ("Symbol", 400)),
          L("1", "Hindustan", "Zinc", "Ltd.", ("HINDZINC", 400)),
          L("51", "securities."),  # wrapped prose, not a row
          L("Sr.", "No.", "Company", "Name", ("Symbol", 400)),
          L("1", "Other", "Co", ("OTHER", 400)),  # a new table under an unrecognised header
          L("CNX", "FMCG", "Index"),
          L("The", "following", "company", "is", "being", "included:"),
          L("Sr.", "No.", "Company", "Name", ("Symbol", 400)),
          L("1", "Foo", "Ltd.", ("FOO", 400)),
          L("The", "following", "company", "is", "being", "excluded", "from", "Nifty", "Midcap", "Select", "index:"),
          L("Sr.", "No.", "Company", "Name", ("Symbol", 400)),
          L("1", "Bar", "Ltd.", ("BAR", 400))]
    rows, _ = ic.parse(ls)
    assert [(r["index"], r["side"], r["serial"], r["symbol"], r["effective"]) for r in rows] == [
        ("NEXT50", "remove", 1, "ZUARI", date(2012, 4, 9)),
        ("NEXT50", "remove", 2, "JCHAC", date(2024, 9, 30)),
        ("NEXT50", "add", 1, "HINDZINC", date(2024, 9, 30)),
        ("other:(unlabelled)", "add", 1, "OTHER", date(2024, 9, 30)),
        ("other:CNX FMCG Index", "add", 1, "FOO", date(2024, 9, 30)),
        ("other:Nifty Midcap Select", "remove", 1, "BAR", date(2024, 9, 30))]


def test_norm_and_resolve():
    assert ic.norm("The Tata Power Co. Ltd.") == ic.norm("TATA POWER COMPANY LIMITED") == "tata power"
    assert ic.norm("Larsen & Toubro") == "larsen and toubro"
    parsed = pl.DataFrame({"name": ["Tata Power Co. Ltd.", "Unknown Ltd", "Acme Ltd"],
                           "symbol": [None, None, "ACME"],
                           "announced": [date(2011, 2, 10)] * 3, "effective": [date(2011, 3, 1)] * 3})
    pairs = pl.DataFrame({"key": ["tata power", "tata power"], "symbol": ["OLDTP", "TATAPOWER"]})
    traded = pl.DataFrame({"symbol": ["OLDTP", "TATAPOWER", "ACME"],
                           "first": [date(2005, 1, 3), date(2005, 1, 3), date(2012, 1, 2)],
                           "last": [date(2009, 1, 2), date(2026, 9, 30), date(2026, 9, 30)]})
    out = ic.resolve(parsed, pairs, traded)
    assert out.select("symbol", "symbol_source", "valid").rows() == \
        [("TATAPOWER", "name", True), (None, None, False), ("ACME", "release", False)]  # ACME not yet listed


def test_page_numbers_and_numbered_header_after_long_line():
    ls = [L("1)", "Nifty", "500", "Index"),
          L("The", "following", "companies", "are", "being", "excluded:"),
          L("Sr.", "No.", "Company", "Name", ("Symbol", 400)),
          L("1", "Foo", "Ltd.", ("FOO", 400)),
          L("1",),  # page number
          L("2", "Bar", "Ltd.", ("BAR", 400)),
          L("The", "replacements", "will", "also", "be", "applicable", "to", "the", "following", "indices", "which",
            "are", "derived", "from", "the", "parent"),
          L("2)", "Nifty", "Free", "Float", "Midcap", "100", "Index", "(Formerly", "Nifty", "Midcap", "100)"),
          L("The", "following", "company", "is", "being", "included:"),
          L("Sr.", "No.", "Company", "Name", ("Symbol", 400)),
          L("1", "Baz", "Ltd.", ("BAZ", 400))]
    rows, _ = ic.parse(ls)
    assert [(r["index"], r["side"], r["serial"], r["symbol"]) for r in rows] == [
        ("NIFTY500", "remove", 1, "FOO"), ("NIFTY500", "remove", 2, "BAR"), ("MIDCAP100", "add", 1, "BAZ")]


def test_index_name_table_is_flagged():
    ls = [L("Sr.", "No.", "Index", "Name"), L("1", "Nifty", "50"), L("2", "Nifty", "Bank")]
    assert ic.parse(ls)[1].get("index_list") is True
    assert "index_list" not in ic.parse([L("Sr.", "No.", "Index", "Name"), L("1", "Nifty", "Bank")])[1]
    assert {r["index"] for r in ic.HAND if r["source_url"].endswith("ind_prs05092023.pdf")} == {"NIFTY50", "NIFTY500"}


def test_long_formerly_header_and_mixed_preamble():
    ls = [L("Date:", "October", "17,", "2016"),
          L("A.", "Nifty", "Quality", "30", "indices", "as", "part", "of", "the", "annual", "review,"),
          L("C.", "Nifty", "Next", "50,", "Nifty", "500", "and", "Nifty", "Midcap", "150", "indices", "on", "account",
            "of", "amalgamation"),
          L("1)", "Nifty", "Midcap", "150", "Index"),
          L("The", "following", "scrip", "is", "being", "excluded:"),
          L("Sr.", "No.", "Name", ("Symbol", 400)),
          L("1", "Cairn", "India", ("CAIRN", 400)),
          L("2)", "Nifty", "Free", "Float", "Smallcap", "100", "Index", "(Formerly", "Nifty", "Smallcap", "100)"),
          L("The", "following", "scrip", "is", "being", "excluded:"),
          L("Sr.", "No.", "Name", ("Symbol", 400)),
          L("1", "Small", "Co", ("SMALL", 400))]
    rows, facts = ic.parse(ls)
    assert facts["kind"] == "scheduled"  # the release as a whole mentions an annual review
    assert [(r["index"], r["symbol"], r["kind"]) for r in rows] == [
        ("MIDCAP150", "CAIRN", "ad_hoc"), ("other:2) Nifty Free Float Smallcap 100 Index (Formerly Nifty Smallcap 100)",
                                           "SMALL", "scheduled")]  # named by no clause: release kind


def test_merge_repeats():
    d = date
    df = pl.DataFrame({"announced": [d(2017, 2, 16), d(2017, 3, 7), d(2017, 2, 16), d(2018, 2, 1)],
                       "effective": [d(2017, 3, 31), d(2017, 3, 16), d(2017, 3, 31), d(2018, 3, 1)],
                       "index": ["NIFTY500"] * 4, "side": ["add"] * 4, "symbol": ["MGL", "MGL", "FOO", "MGL"],
                       "source_url": ["a", "b", "a", "c"]})
    out = ic.merge_repeats(df).sort("symbol", "announced")
    assert out.select("announced", "effective", "symbol", "rescheduled_by").rows() == [
        (d(2017, 2, 16), d(2017, 3, 31), "FOO", None),
        (d(2017, 2, 16), d(2017, 3, 16), "MGL", "b"),
        (d(2018, 2, 1), d(2018, 3, 1), "MGL", None)]  # announced after the earlier change took effect: a new event


def test_cancel_pairs():
    d = date
    df = pl.DataFrame({"announced": [d(2020, 2, 18), d(2020, 3, 19), d(2020, 3, 19), d(2020, 2, 18), d(2020, 5, 1)],
                       "effective": [d(2020, 3, 27), d(2020, 3, 27), d(2020, 3, 27), d(2020, 3, 27), d(2020, 6, 1)],
                       "index": ["MIDCAP150"] * 5, "side": ["add", "remove", "add", "remove", "remove"],
                       "symbol": ["YESBANK", "YESBANK", "PVR", "FOO", "PVR"]})
    kept, gone = ic.cancel_pairs(df)
    assert sorted(gone["symbol"]) == ["YESBANK", "YESBANK"]
    assert sorted(kept["symbol"]) == ["FOO", "PVR", "PVR"]  # PVR removal comes after the add took effect


def test_criteria_clause_and_past_effective_date():
    ls = [L("Date:", "February", "18,", "2020"),
          L("A.", "Revision", "of", "eligibility", "criteria", "for", "NIFTY", "500", "index"),
          L("B.", "Replacements", "as", "part", "of", "its", "periodic", "review", "effective", "from", "March", "27,",
            "2020"),
          L("The", "company", "was", "included", "in", "NIFTY", "500", "w.e.f.", "March", "19,", "2020"),
          L("1)", "NIFTY", "500"),
          L("The", "following", "company", "is", "being", "included:"),
          L("Sr.", "No.", "Name", ("Symbol", 400)),
          L("1", "Alkyl", "Amines", ("ALKYLAMINE", 400))]
    rows, _ = ic.parse(ls)
    assert [(r["index"], r["kind"], r["effective"]) for r in rows] == [("NIFTY500", "scheduled", date(2020, 3, 27))]


def test_void_and_redate():
    d, u = date, ic.SITE + "/Press_Release/"
    df = pl.DataFrame({"announced": [d(2020, 2, 18), d(2020, 2, 18), d(2020, 2, 18), d(2020, 6, 10), d(2013, 11, 7)],
                       "effective": [d(2020, 3, 27), d(2020, 3, 19), d(2020, 3, 27), d(2020, 6, 26), d(2013, 11, 15)],
                       "index": ["NIFTY500", "NEXT50", "NIFTY50", "NIFTY500", "NIFTY500"],
                       "symbol": ["A", "SHREECEM", "B", "C", "FRL"],
                       "source_url": [u + "ind_prs18022020.pdf"] * 3 + [u + "ind_prs10062020.pdf", u + "x.pdf"],
                       "rescheduled_by": [None, u + "ind_prs16032020.pdf", None, None, None]})
    kept, void = ic.void_and_redate(df)
    assert void["symbol"].to_list() == ["A"]  # accelerated (03-19) and Nifty 50 rows stand
    assert kept["symbol"].to_list() == ["SHREECEM", "B", "C", "FRL"]
    frl = kept.row(3, named=True)
    assert frl["effective"] == d(2013, 11, 18) and frl["rescheduled_by"].endswith("ind_prs13112013.pdf")
