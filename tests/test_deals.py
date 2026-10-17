from datetime import date

from research.deals import months, parse

CSV = ('"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ","Quantity Traded ",'
       '"Trade Price / Wght. Avg. Price ","Remarks "\n'
       '"01-MAR-2024","ASHOKAMET","Ashoka Metcast Limited","AKHIL  RETAIL PVT LTD ","SELL","2,50,000","1,025.10","-"\n'
       '"04-JAN-2016","SFCL","Star Ferro & Cement Ltd.","KANTA  AGARWAL","B","4,25,000","128.50",\n')


def test_parse_csv():
    d = parse(CSV, "block_deals")
    assert d.height == 2 and d["kind"].to_list() == ["block", "block"]
    r = d.row(0, named=True)
    assert (r["date"], r["qty"], r["price"], r["client"], r["side"]) == (
        date(2024, 3, 1), 250_000, 1025.10, "AKHIL RETAIL PVT LTD", "SELL")
    assert d["remarks"][1] is None and d["side"][1] == "BUY"
    assert parse(CSV.split("\n")[0] + "\n", "bulk_deals").height == 0  # month without deals


def test_months_cover_range():
    m = months(date(2023, 11, 1), date(2024, 2, 15))
    assert m[0] == (date(2023, 11, 1), date(2023, 11, 30)) and m[2] == (date(2024, 1, 1), date(2024, 1, 31))
    assert m[-1] == (date(2024, 2, 1), date(2024, 2, 15)) and len(m) == 4
