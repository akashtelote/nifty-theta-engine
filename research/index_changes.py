"""Index-change archive from niftyindices press releases (plan 20261017 E1-E4, task A4).

Source: https://www.niftyindices.com/press-release lists every release back to 2000 (date, PDF link, title).
PDFs are cached in data/index_changes/pdf/ and read with pdfplumber word coordinates (optional extra
`research`; the bot image does not install it). Text extraction alone garbles the tables: some PDFs overlay two
text layers, and the column order differs by year.

A release is a list of sections ("(1) S&P CNX Nifty Index", "2) Nifty Next 50", ...), each with an excluded and an
included table (Sr. No., name, and from ~2011 a Symbol column). Releases before the Symbol column name companies
only; those names are mapped to symbols through the NSE corporate-action feed (comp -> symbol) and the
name/symbol pairs of later releases.

Announcement time is not in the releases, so `announced_time` is null. E1 enters at the first open after the
announce date, which is the rule for both after-hours and in-hours announcements.

Layout: data/index_changes/changes.parquet, one row per (release, index, side, symbol).
CLI: uv run --extra research python -m research.index_changes
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
import requests

ROOT = Path("data/index_changes")
SITE = "https://www.niftyindices.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
FIRST = date(2010, 1, 1)
RELEVANT = r"(?i)replac|change|inclus|exclus"
SKIP = r"(?i)methodolog|investable|iwf|maintenance procedure|launch|guideline|consultation|sgx|nomenclature"

# index names over time -> label (plan A4: Nifty 50, Next 50, Midcap 150 / Midcap 100 before it, Nifty 500)
TARGETS = {"s&p cnx nifty": "NIFTY50", "cnx nifty": "NIFTY50", "nifty 50": "NIFTY50", "nifty50": "NIFTY50",
           "cnx nifty junior": "NEXT50", "nifty junior": "NEXT50", "nifty next 50": "NEXT50",
           "cnx midcap": "MIDCAP100", "cnx midcap 100": "MIDCAP100", "nifty midcap 100": "MIDCAP100",
           "nifty free float midcap 100": "MIDCAP100",  # its 2016-18 name; "Full Midcap 100" is another index
           "nifty midcap 150": "MIDCAP150",
           "s&p cnx 500": "NIFTY500", "cnx 500": "NIFTY500", "nifty 500": "NIFTY500"}
ENUM = re.compile(r"^(?:\(?[A-Z]\.)?\(?(?:\d{1,2}|[a-z])\s*[\).]\s*")  # "(1) ", "1) ", "A.1) ", "2. ", "a) "
SCHEDULED = re.compile(r"(?i)periodic review|semi.?annual review|half.?yearly review|annual review")
MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DATE = rf"({MONTH}\s+\d{{1,2}}\s*,?\s*\d{{4}})"
EFFECTIVE = re.compile(rf"(?i)(?:effective(?:\s+(?:from|on))?|w\.?\s?e\.?\s?f\.?)\s*:?\s*(?:the\s+)?{DATE}")
ANNOUNCED = re.compile(rf"(?i)(?:Date\s*:|Mumbai\s*,)\s*{DATE}")


def listing(session: requests.Session) -> pl.DataFrame:
    r = session.get(SITE + "/press-release", timeout=60)
    r.raise_for_status()
    it = re.findall(r'data-date="([^"]+)".*?<a href=.([^\'"]+).[^>]*>([^<]+)</a>', r.text, re.S)
    if len(it) < 1000:  # the page carried 1,516 releases on 2026-10-17
        raise ValueError(f"press-release listing has only {len(it)} items")
    df = pl.DataFrame(it, schema=["listed", "path", "title"], orient="row")
    return df.with_columns(pl.col("listed").str.strptime(pl.Date, "%b %d, %Y"),
                           pl.col("title").str.replace_all("&amp;", "&").str.replace_all("&#39;", "'"))


def candidates(lst: pl.DataFrame) -> pl.DataFrame:
    # "Change in Indices and Methodology" (2015-08 review) and "... and replacements in indices" carry changes
    keep = pl.col("title").str.contains(r"(?i)replacement|change in indices")
    return lst.filter((pl.col("listed") >= FIRST) & pl.col("title").str.contains(RELEVANT)
                      & (keep | ~pl.col("title").str.contains(SKIP)))


def pdf_path(p: str) -> Path:
    return ROOT / "pdf" / (Path(p).stem + ".pdf")


def fetch(session: requests.Session, paths: list[str]) -> list[str]:
    """Cache each PDF; returns the paths no URL variant served (broken links on the site)."""
    (ROOT / "pdf").mkdir(parents=True, exist_ok=True)
    missing = []
    for p in paths:
        out = pdf_path(p)
        if out.exists():
            continue
        stem = SITE + p.removesuffix(".pdf")
        for url in (SITE + p, stem + ".pdf", stem + ".PDF"):  # some links lack or mis-case the extension
            r = session.get(url, timeout=60)
            if r.ok and r.content.startswith(b"%PDF"):  # a 404 on one variant falls through to the next
                out.write_bytes(r.content)
                break
        else:
            missing.append(p)
        time.sleep(0.3)
    return missing


def lines(path: Path) -> list[list[tuple[str, float]]]:
    """Words grouped into visual lines (tops within 3pt), each as (text, x0), pages in order."""
    import pdfplumber

    out = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            ws = sorted(pg.dedupe_chars().extract_words(x_tolerance=1.5), key=lambda w: (w["top"], w["x0"]))
            cur, top = [], None
            for w in ws:
                if top is not None and w["top"] - top > 3:
                    out.append(sorted(cur, key=lambda t: t[1]))
                    cur = []
                if not cur:
                    top = w["top"]
                cur.append((w["text"], w["x0"]))
            if cur:
                out.append(sorted(cur, key=lambda t: t[1]))
    return out


def to_date(s: str) -> date:
    s = re.sub(r"\s+", " ", s.replace(",", " ").replace(".", "")).strip().replace("Sept ", "Sep ")
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date {s!r}")


def index_label(text: str) -> str | None:
    """Target label of an index header, or None. Only whole-name matches count (not 'Nifty 50 Equal Weight')."""
    t = re.sub(r"\([^)]*\)|\*", " ", ENUM.sub("", text))  # "(Formerly Nifty Midcap 100)", "**" footnote marks
    t = re.sub(r"\s+", " ", t).strip().rstrip(":").strip().lower()
    t = re.sub(r"\s*index$", "", t).strip()
    return TARGETS.get(t)


# Single-index ad hoc releases have no section header; the index is named in the prose ("change in CNX 500 index
# to be effective ..."). Longest name first so "cnx nifty junior" wins over "cnx nifty"; the lookahead rejects
# derived indices ("Nifty 50 Equal Weight").
PROSE = re.compile(r"(?i)\b(" + "|".join(re.escape(k) for k in sorted(TARGETS, key=len, reverse=True))
                   + r")(?=\s*(?:index\b|w\.?\s?e\.?\s?f|to be\b|which\b|with\b|on account\b|and\b|[,.:;)]|$))")


def parse(ls: list[list[tuple[str, float]]]) -> tuple[list[dict], dict]:
    """Rows (index, side, serial, name, symbol, effective, kind) from one release's lines, plus release facts."""
    texts = [" ".join(t for t, _ in ln) for ln in ls]
    full = " ".join(texts)
    starts, pos = [], 0
    for t in texts:
        starts.append(pos)
        pos += len(t) + 1
    # "The company was included in NIFTY 500 w.e.f. March 19, 2020" tells what happened, not when this release's
    # changes take effect (2020-03-19)
    effs = [(m.start(), to_date(m.group(1))) for m in EFFECTIVE.finditer(full)
            if not re.search(r"\b(was|were)\b", full[max(0, m.start() - 60):m.start()])]
    ann = ANNOUNCED.search(full)
    head = full[:full.find("The following")] if "The following" in full else full[:800]
    release_kind = "scheduled" if SCHEDULED.search(head) else "ad_hoc"
    # a preamble can give each group of indices its own reason ("A. Nifty Dividend Opportunities 50 ... as part of
    # the annual review ... C. Nifty Next 50, ..., Nifty 500 ... on account of ... amalgamation", 2016-10-17)
    # a criteria clause ("A. Revision of eligibility criteria ... NIFTY 500", 2020-02-18) gives no reason for a change
    clauses = [(c, "scheduled" if SCHEDULED.search(c) else "ad_hoc") for c in re.split(r"\s(?=[A-Z]\.\s)", head)[1:]
               if not re.search(r"(?i)criteria|methodolog", c)]
    clause_kind = {}
    if len({k for _, k in clauses}) == 2:  # else one reason for the whole release: release_kind and group lines decide
        for c, k in clauses:
            for name in PROSE.findall(c):
                clause_kind.setdefault(TARGETS[name.lower()], k)
    facts = {"announced_pdf": to_date(ann.group(1)) if ann else None, "effective_dates": sorted({d for _, d in effs}),
             "kind": release_kind}
    # "Sr. No. / Index Name" tables (one security, many indices) are not parsed; such releases go in HAND by eye
    heads = [i for i, t in enumerate(texts) if re.search(r"(?i)\bindex name\b", t)]
    if any(index_label(m.group(1)) for h in heads for t in texts[h + 1:h + 40] if (m := re.match(r"^\d{1,2}\s+(.+)", t))):
        facts["index_list"] = True

    rows, idx, side, sym_x, kind, pend, scope, last = [], None, None, None, release_kind, None, 0, None
    for i, (ln, t) in enumerate(zip(ls, texts)):
        group = re.match(r"^[A-Z]\.\s", t) and re.search(r"(?i)replacement|review|revision|change|revocation", t)
        if group or re.search(r"(?i)stands replaced|^\(?\d{1,2}\s*[\).]\s*replacements? on account", t):
            # "A. Semi-Annual Review:" / "B. Replacements on account of revision in criteria:" (2016-02) /
            # "1) Replacements on account of semi-annual review ..." (2023-) / "The earlier list ... stands replaced
            # with the list given hereunder" (2021-09-15 restates the 2021-08 review). A group's reason can sit in
            # its first sentence ("A. Replacements in indices: ... as part of its periodic review", 2024-08).
            nxt = next((k for k in range(i + 1, len(texts)) if ENUM.match(texts[k]) or "following" in texts[k]
                        or re.match(r"^[A-Z]\.\s", texts[k])), len(texts))
            why = " ".join(texts[i:min(nxt, i + 6)])
            kind = ("criteria_revision" if re.search(r"(?i)criteria|methodolog", t) else
                    "scheduled" if SCHEDULED.search(why) or "stands replaced" in why else
                    # no reason given ("B. Replacements in indices:", 2022-02): the preamble's reason holds
                    "ad_hoc" if re.search(r"(?i)on account|pursuant|due to|review", why) else release_kind)
            if group:  # a group names its own indices, so the previous section's index does not carry over
                idx, side, sym_x, pend, scope = None, None, None, None, starts[i]
                continue
        head_part = re.split(r"(?i)\bthe following\b", t)[0]
        # numbered notes ("1. InterGlobe Aviation Ltd. has been removed from ...") are not section headers;
        # neither is a bare serial ("1 Nifty 500" in a table). An un-numbered "CNX FMCG Index" line is one.
        # a long line ending in a lowercase word wraps onto this one ("... their inclusion in / Nifty 50 index")
        wrapped = i > 0 and not ENUM.match(t) and len(ls[i - 1]) > 12 and ls[i - 1][-1][0][:1].islower()
        bare = re.sub(r"\([^)]*\)", " ", t)  # "(Formerly Nifty Smallcap 100)" does not make a header long
        header = not wrapped and index_label(head_part) or not wrapped and (
            not re.match(r"^\d{1,3}$", ln[0][0]) and "following" not in t.lower() and (
                (ENUM.match(t) and len(bare.split()) <= 10
                 and not re.search(r"(?i)\b(has|have|been|is|are|was|were)\b", t))
                or (len(ln) <= 6 and t[:1].isupper() and re.search(r"(?i)\bindex:?$", t))))
        if header:
            idx, side, sym_x, pend, scope = index_label(head_part) or ("other:" + head_part.strip()), None, None, None, \
                starts[i]
            kind = clause_kind.get(idx, release_kind) if clause_kind else kind
        new_side = ("remove" if re.search(r"(?i)\bthe following\b.*\b(excluded|removed|deleted)\b", t) else
                    "add" if re.search(r"(?i)\bthe following\b.*\b(included|added)\b", t) else None)
        if new_side:
            named = re.search(r"(?i)\b(?:excluded|removed|deleted|included|added)\s+(?:from|in|into)\s+"
                              r"((?:Nifty|CNX|S&P)\b.*?)\s+index\b", t)
            if named:  # "... being excluded from Nifty Midcap Select index:"
                idx = index_label(named.group(1)) or "other:" + named.group(1)
            elif idx is None:  # header-less release: the index is named in the prose since the last header
                named = PROSE.findall(full[scope:starts[i]])
                idx = TARGETS[named[-1].lower()] if named else "other:(prose)"
            side, sym_x, pend, last = new_side, None, None, None
            continue
        hx = next((x for w, x in ln if w.lower() == "symbol"), None)  # the heading can sit apart from "Sr. No."
        if hx is not None or re.match(r"(?i)^sr\.?\s*no", t):
            sym_x = hx if hx is not None else sym_x
            continue
        if side is None or idx is None:
            continue
        toks = ln
        if pend is not None:  # a lone number before a numbered row is a page number, not a wrapped serial
            toks, pend = (ln if re.match(r"^\d{1,3}$", ln[0][0]) else [pend] + ln), None
        if not re.match(r"^\d{1,3}$", toks[0][0]):
            continue
        if len(toks) == 1:
            pend = toks[0]
            continue
        serial = int(toks[0][0])
        if last is not None and serial != last + 1:
            if serial != 1:
                continue  # prose that wraps to start with a number ("... 51 / securities.")
            idx = "other:(unlabelled)"  # a fresh table under a header this parser did not recognise
        last = serial
        rest = toks[1:]
        eff = next((d for p, d in reversed(effs) if p <= starts[i]), effs[0][1] if effs else None)
        tail = re.search(rf"\s{DATE}$", " " + " ".join(w for w, _ in rest))
        if tail:  # an "Effective Date" column right of Symbol (2012-04): dates differ by row
            eff, rest = to_date(tail.group(1)), rest[:len(rest) - len(tail.group(1).split())]
        name = [w for w, x in rest if sym_x is None or x < sym_x - 3]
        sym = [w for w, x in rest if sym_x is not None and x >= sym_x - 3]
        if sym_x is not None and not sym and rest and re.match(r"^[A-Z0-9][A-Z0-9&\-]*\*?$", rest[-1][0]):
            # a centred "Symbol" heading starts right of left-aligned symbols; a wrapped name leaves the
            # symbol alone on the serial line (JCHAC, 2022-02)
            name, sym = name[:-1], [rest[-1][0]]
        rows.append({"index": idx, "side": side, "serial": serial, "name": " ".join(name).strip(),
                     "symbol": sym[0].strip("*#") if sym else None, "effective": eff, "kind": kind})
    return rows, facts


LEGAL = r"\b(limited|ltd|the|co|company|corporation|corp|inc|pvt|private)\b"
# 2010-11 name-only rows with no name match in the CA feed or symbol-change list; checked by hand against the
# bhavcopy symbols that traded at the time
MANUAL = {"Sesa Goa": "SESAGOA", "Smartlink Network Systems": "SMARTLINK", "Core Projects & Technologies": "COREPROTEC",
          "Pipavav Shipyard": "PIPAVAVYD", "House of Pearl Fashions": "HOPFL", "Vishal Retail": "VISHALRET"}
# 2024-09-25 revoked part of the 2024-08-23 review (Vodafone Idea stays; Central Bank of India not added) and put
# Prism Johnson out of Nifty 500 instead. The release is one table across many indices, so it is coded by hand.
REVOKED = [(date(2024, 8, 23), ix, side, sym) for ix, side, sym in
           [("NIFTY500", "remove", "IDEA"), ("MIDCAP150", "remove", "IDEA"), ("MIDCAP150", "add", "CENTRALBK"),
            ("MIDCAP100", "remove", "IDEA"), ("MIDCAP100", "add", "CENTRALBK")]] + \
    [(date(2024, 2, 28), ix, side, sym) for ix, side, sym in  # 2024-03-19: IREDA not added (BSE instead), VGUARD stays
     [("NIFTY500", "add", "IREDA"), ("MIDCAP150", "add", "IREDA"), ("MIDCAP100", "add", "IREDA"),
      ("NIFTY500", "remove", "VGUARD")]]
def _hand(announced, effective, index, kind, pdf, title, rows):
    return [{"announced": announced, "effective": effective, "index": index, "kind": kind, "side": side,
             "serial": n, "name": name, "symbol": sym, "listed": announced, "announced_pdf": announced, "title": title,
             "source_url": SITE + "/Press_Release/" + pdf} for side, n, name, sym in rows]


# Rows read by eye. ind_prs23082021.pdf is a scan; only its Next 50 section is not superseded (2021-09-15 reissued
# the Nifty 500 and Midcap 150 lists; there is no Nifty 50 section).
HAND = _hand(date(2024, 9, 25), date(2024, 9, 30), "NIFTY500", "ad_hoc", "ind_prs25092024.pdf",
             "Replacements in indices", [("remove", 1, "Prism Johnson Ltd.", "PRSMJOHNSN")]) + \
    _hand(date(2021, 8, 23), date(2021, 9, 30), "NEXT50", "scheduled", "ind_prs23082021.pdf",
          "Revision in criteria and replacements in Indices",
          [("remove", 1, "Abbott India Ltd.", "ABBOTINDIA"), ("remove", 2, "Alkem Laboratories Ltd.", "ALKEM"),
           ("remove", 3, "MRF Ltd.", "MRF"), ("remove", 4, "Petronet LNG Ltd.", "PETRONET"),
           ("remove", 5, "United Breweries Ltd.", "UBL"),
           ("add", 1, "Bank of Baroda", "BANKBARODA"),
           ("add", 2, "Cholamandalam Investment and Fin. Co. Ltd.", "CHOLAFIN"),
           ("add", 3, "Jindal Steel & Power Ltd.", "JINDALSTEL"), ("add", 4, "PI Industries Ltd.", "PIIND"),
           ("add", 5, "Steel Authority of India Ltd.", "SAIL")]) + \
    [r for ix in ("MIDCAP150", "MIDCAP100") for r in
     _hand(date(2024, 3, 19), date(2024, 3, 28), ix, "ad_hoc", "ind_prs19032024.pdf", "Replacements in indices",
           [("add", 1, "BSE Ltd.", "BSE")])]
# "Sr. No. / Index Name" releases: a spun-off entity listed at a price joins at once, then is excluded and index
# funds sell it. pdf: (announced, effective, [(name, symbol, indices)]). Zero-price dummy inclusions
# (ind_prs15072025 DUMMYDBRLT, ind_prs23042026 DUMMYVEDL1-4) are left out: holders get the shares, nobody buys.
EXCLUDED = {
    "ind_prs05092023": (date(2023, 9, 5), date(2023, 9, 7), [("Jio Financial Services Ltd.", "JIOFIN", "N50 N500")]),
    "ind_prs23082024_1": (date(2024, 8, 23), date(2024, 8, 30),
                          [("Tata Motors Ltd. 'A' Ordinary Shares - DVR", "TATAMTRDVR", "N500")]),
    "ind_prs13092024": (date(2024, 9, 13), date(2024, 9, 17), [("Raymond Lifestyle Ltd.", "RAYMONDLSL", "N500")]),
    "ind_prs19092024": (date(2024, 9, 19), date(2024, 9, 23),
                        [("Sanofi Consumer Healthcare India Ltd.", "SANOFICONR", "N500")]),
    "ind_prs06022025_1": (date(2025, 2, 6), date(2025, 2, 10), [("ITC Hotels Ltd.", "ITCHOTELS", "N50 N500")]),
    "ind_prs25062025_2": (date(2025, 6, 25), date(2025, 6, 27),
                          [("Siemens Energy India Ltd.", "ENRIN", "NEXT50 N500"),
                           ("Aditya Birla Lifestyle Brands Ltd.", "ABLBL", "N500 MID150 MID100")]),
    "ind_prs08072025": (date(2025, 7, 8), date(2025, 7, 10), [("Raymond Realty Ltd.", "RAYMONDREL", "N500")]),
    "ind_prs13112025": (date(2025, 11, 13), date(2025, 11, 17), [("Tata Motors Ltd.", "TMCV", "N50 N500")]),
    "ind_prs26112025": (date(2025, 11, 26), date(2025, 11, 28),
                        [("Advent Hotels International Ltd.", "ADVENTHTL", "N500")]),
    "ind_prs11122025_1": (date(2025, 12, 11), date(2025, 12, 15),
                          [("SKF India (Industrial) Ltd.", "SKFINDUS", "N500")]),
    "ind_prs20022026_1": (date(2026, 2, 20), date(2026, 2, 24), [("Kwality Wall's (India) Ltd.", "KWIL", "N50 N500")]),
    "ind_prs17062026": (date(2026, 6, 17), date(2026, 6, 19),
                        [("Vedanta Power Ltd.", "VEDPOWER", "NEXT50 N500"),
                         ("Vedanta Iron and Steel Ltd.", "VISL", "NEXT50 N500")]),
    "ind_prs19062026": (date(2026, 6, 19), date(2026, 6, 23), [("Vedanta Aluminium Metal Ltd.", "VAML", "NEXT50 N500")]),
    "ind_prs22062026": (date(2026, 6, 22), date(2026, 6, 24), [("Vedanta Oil and Gas Ltd.", "VOGL", "NEXT50 N500")]),
}
_IX = {"N50": "NIFTY50", "NEXT50": "NEXT50", "N500": "NIFTY500", "MID150": "MIDCAP150", "MID100": "MIDCAP100"}
HAND += [r for pdf, (a, e, secs) in EXCLUDED.items() for ix in _IX
         for r in _hand(a, e, _IX[ix], "ad_hoc", pdf + ".pdf", "Exclusion from indices",
                        [("remove", n, name, sym) for n, (name, sym) in
                         enumerate(((name, sym) for name, sym, ixs in secs if ix in ixs.split()), 1)])]
# 2021-09-15 restated the Nifty 500 / Midcap 150 lists of the scanned 2021-08-23 review after revoking the REIT
# inclusions. A restated change that was on the 08-23 list (read by eye, pp. 3-6) was news on 08-23.
RESTATED = ("ind_prs15092021.pdf", date(2021, 8, 23), {
    ("NIFTY500", "remove"): set("AKZOINDIA BALMLAWRIE BLISSGVS DISHTV DCAL FCONSUMER GRSE GEPIL GILLETTE GULFOILLUB HSCL "
                                "HUHTAMAKI JTEKTINDIA MAHSCOOTER MAHSEAMLES MASFIN RAYMOND RESPONIND SHOPERSTOP "
                                "SUNCLAYLTD SWANENERGY TATAINVEST VSTIND".split()),
    ("NIFTY500", "add"): set("ANURAS BIRET CGPOWER EMBASSY EQUITASBNK FACT HATHWAY HOMEFIRST IRFC INDIGOPNTS JUBLINGREA "
                             "JUBLPHARMA KALYANKJIL LXCHEM LODHA MASTEK MINDSPACE NAZARA POONAWALLA PRAJIND RAILTEL "
                             "TATASTLLP TTML".split()),
    ("MIDCAP150", "remove"): set("AKZOINDIA ASTRAZEN BANKBARODA BBTC CESC CHOLAFIN CREDITACC GILLETTE GODREJAGRO IDBI "
                                 "IIFLWAM IBULHSGFIN JINDALSTEL JMFINANCIL MOTILALOFS PIIND PGHL SJVN SAIL "
                                 "VGUARD".split()),
    ("MIDCAP150", "add"): set("ABBOTINDIA AFFLE ALKEM ALKYLAMINE APLAPOLLO BLUEDART EMBASSY HINDCOPPER INDIANB IRFC "
                              "KAJARIACER LINDEINDIA LODHA MINDSPACE MRF NATIONALUM PETRONET UBL".split())})
# ind_prs13052020: the changes of 2020-02-18, 03-12 and 03-19 due 2020-03-27 (deferred 03-23) "shall stand null and
# void", except Nifty 50 / Nifty Bank, already rebalanced 03-19; the review was re-run 2020-06-10. The 2020-03-16
# accelerations (effective 03-19) happened. (pdfs, effective, kept index, source)
VOIDED = (("ind_prs18022020.pdf", "ind_prs12032020.pdf", "ind_prs19032020.pdf"), date(2020, 3, 27), "NIFTY50",
          SITE + "/Press_Release/ind_prs13052020.pdf")
# ind_prs13112013: 2013-11-15 became a trading holiday, so the changes of 2013-11-07 took effect 2013-11-18.
# (announced, old effective, new effective, source)
REDATED = (date(2013, 11, 7), date(2013, 11, 15), date(2013, 11, 18), SITE + "/Press_Release/ind_prs13112013.pdf")
# index-name-table PDFs read by eye (EXCLUDED, the dummy inclusions, the 2024 revocations)
REVIEWED = set(EXCLUDED) | {"ind_prs15072025", "ind_prs23042026", "ind_prs19032024", "ind_prs25092024"}


def norm(name: str) -> str:
    """Comparable company name: lowercase, '&' -> 'and', no punctuation or legal suffixes."""
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and "))
    return " ".join(re.sub(LEGAL, " ", s).split())


def name_pairs(parsed: pl.DataFrame) -> pl.DataFrame:
    """norm name -> symbol from release rows that carry both, the NSE CA feed and the symbol-change list."""
    ca = [{"name": r["comp"], "symbol": r["symbol"]}
          for f in sorted(Path("data/equity_ref/ca").glob("*.json")) for r in json.loads(f.read_text(encoding="utf-8"))
          if r.get("comp") and r.get("symbol")]
    sc = pl.read_csv("data/equity_ref/symbolchange.csv", infer_schema_length=0)
    sc = pl.concat([sc.select(name=pl.col(sc.columns[0]), symbol=pl.col(c).str.strip_chars()) for c in sc.columns[1:3]])
    own = parsed.filter(pl.col("symbol").is_not_null()).select("name", "symbol")
    manual = pl.DataFrame(list(MANUAL.items()), schema={"name": pl.Utf8, "symbol": pl.Utf8}, orient="row")
    return (pl.concat([own, pl.DataFrame(ca, schema={"name": pl.Utf8, "symbol": pl.Utf8}), sc, manual])
            .with_columns(key=pl.col("name").map_elements(norm, return_dtype=pl.Utf8))
            .filter(pl.col("key") != "").select("key", "symbol").unique())


def resolve(parsed: pl.DataFrame, pairs: pl.DataFrame, traded: pl.DataFrame) -> pl.DataFrame:
    """Fills missing symbols and checks every symbol against the bhavcopy. traded: symbol, first, last (dates
    the symbol had EQ/BE rows). A symbol is valid when it traded on some day in [announced - 60d, effective].
    Name-only rows take the exact-name candidate that is valid, else the closest name (difflib >= 0.9) that is.
    Adds `symbol_source` (release | name | fuzzy | None) and `valid`."""
    import difflib

    span = {r["symbol"]: (r["first"], r["last"]) for r in traded.iter_rows(named=True)}
    by_key: dict[str, list[str]] = {}
    for k, s in pairs.iter_rows():
        by_key.setdefault(k, []).append(s)
    keys = list(by_key)

    def ok(sym, lo, hi):
        f = span.get(sym)
        return f is not None and f[0] <= hi and f[1] >= lo

    out = []
    for r in parsed.iter_rows(named=True):
        lo = r["announced"] - timedelta(days=60)
        hi = r["effective"] or r["announced"]
        src, sym = ("release", r["symbol"]) if r["symbol"] else (None, None)
        if sym is None:
            k = norm(r["name"])
            sym = next((s for s in by_key.get(k, []) if ok(s, lo, hi)), None)
            src = "name" if sym else None
            if sym is None:
                for m in difflib.get_close_matches(k, keys, n=5, cutoff=0.9):
                    sym = next((s for s in by_key[m] if ok(s, lo, hi)), None)
                    if sym:
                        src = "fuzzy"
                        break
        out.append({**r, "symbol": sym, "symbol_source": src, "valid": sym is not None and ok(sym, lo, hi)})
    return pl.DataFrame(out, infer_schema_length=None)


def parse_all(lst: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    """Every target-index row of every cached release, with listing date, PDF date and source URL; plus the PDFs
    with an index-name table for a target index that nobody has read (not in REVIEWED)."""
    recs, unread = [], []
    for r in lst.unique("path").iter_rows(named=True):
        p = pdf_path(r["path"])
        if not p.exists():
            continue
        rows, facts = parse(lines(p))
        if facts.get("index_list") and p.stem not in REVIEWED:
            unread.append(p.name)
        for x in rows:
            recs.append({**x, "listed": r["listed"], "announced_pdf": facts["announced_pdf"],
                         "title": r["title"], "source_url": SITE + r["path"]})
    return pl.DataFrame(recs, infer_schema_length=None), sorted(unread)


def build(lst: pl.DataFrame, traded: pl.DataFrame) -> tuple[pl.DataFrame, list[str], pl.DataFrame]:
    """changes.parquet rows, unread index-name-table PDFs, and the cancelled pairs left out (cancel_pairs).
    traded: symbol, first, last (bhavcopy spans)."""
    raw, unread = parse_all(lst)
    raw = raw.with_columns(announced=pl.coalesce("announced_pdf", "listed"), announced_time=pl.lit(None, pl.Time))
    pdf, first, was = RESTATED
    on_first = pl.Series([was.get((ix, sd), set()).__contains__(sy) for ix, sd, sy in
                          raw.select("index", "side", "symbol").iter_rows()], dtype=pl.Boolean)
    raw = raw.with_columns(announced=pl.when(pl.col("source_url").str.ends_with(pdf) & on_first)
                           .then(pl.lit(first)).otherwise("announced"))
    revoked = pl.DataFrame(REVOKED, schema=["announced", "index", "side", "symbol"], orient="row")
    tgt = (raw.filter(~pl.col("index").str.starts_with("other:"), pl.col("announced") >= FIRST)  # one PDF of 2005
           .join(revoked, on=["announced", "index", "side", "symbol"], how="anti"))
    tgt = pl.concat([tgt, pl.DataFrame(HAND).with_columns(announced_time=pl.lit(None, pl.Time))], how="diagonal_relaxed")
    out = resolve(tgt, name_pairs(raw), traded)
    # a release listed twice (e.g. a corrigendum under a second link) gives the same row twice
    out = merge_repeats(out.unique(["announced", "effective", "index", "side", "name", "symbol"],
                                   keep="first", maintain_order=True))
    out, voided = void_and_redate(out)
    out, cancelled = cancel_pairs(out)
    cancelled = pl.concat([voided.with_columns(why=pl.lit("voided")), cancelled.with_columns(why=pl.lit("cancelled"))])
    return (out.select("announced", "announced_time", "effective", "index", "symbol", "side", "kind", "name", "serial",
                       "symbol_source", "valid", "listed", "announced_pdf", "title", "source_url", "rescheduled_by")
            .sort("announced", "index", "side", "serial")), unread, cancelled


def merge_repeats(out: pl.DataFrame) -> pl.DataFrame:
    # a later release that repeats a change before it takes effect only moves its date (2017-03-07 brings three
    # 2017-02-16 Nifty 500 changes forward for the SBI merger; 2020-03-16 SHREECEM): keep the first announcement
    # (when the news came out) with the later effective date, and drop the repeat
    # ponytail: one repeat per change (seen so far); a chain of three would keep the middle effective date
    k = ["index", "side", "symbol"]
    nxt = pl.col("repeat").shift(-1).over(k).fill_null(False)
    return (out.sort("announced", "source_url")
            .with_columns(repeat=(pl.col("symbol").is_not_null()
                                  & (pl.col("announced") > pl.col("announced").shift().over(k))
                                  & (pl.col("announced") <= pl.col("effective").shift().over(k))).fill_null(False))
            .with_columns(rescheduled_by=pl.when(nxt).then(pl.col("source_url").shift(-1).over(k)),
                          effective=pl.when(nxt).then(pl.col("effective").shift(-1).over(k)).otherwise("effective"))
            .filter(~pl.col("repeat")).drop("repeat"))


def void_and_redate(out: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(kept, voided): applies VOIDED and REDATED, citing the later release in rescheduled_by. Runs after
    merge_repeats, so a voided-release change accelerated by a later release no longer has the voided date."""
    pdfs, eff, keep_ix, _ = VOIDED
    void = (pl.col("source_url").str.split("/").list.last().is_in(pdfs) & (pl.col("effective") == eff)
            & (pl.col("index") != keep_ix))
    a, old, new, src = REDATED
    move = (pl.col("announced") == a) & (pl.col("effective") == old)
    out = out.with_columns(rescheduled_by=pl.when(move).then(pl.lit(src)).otherwise("rescheduled_by"),
                           effective=pl.when(move).then(pl.lit(new)).otherwise("effective"))
    return out.filter(~void), out.filter(void)


def cancel_pairs(out: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(kept, cancelled). A change undone by the opposite change for the same (index, symbol), announced after it
    but before it took effect and effective no later, never happened (2020-03-19: Yes Bank not added to Midcap
    100/150 after all; 2020-03-12: Shilpa Medicare stays in Nifty 500). Both rows go; the replacement (PVR,
    GAYAPROJ) is a row of the later release."""
    i = out.with_row_index("_i")
    k = ["index", "symbol"]
    pairs = (i.join(i, on=k, suffix="_b")
             .filter(pl.col("side") != pl.col("side_b"), pl.col("announced_b") > pl.col("announced"),
                     pl.col("announced_b") <= pl.col("effective"), pl.col("effective_b") <= pl.col("effective")))
    gone = pl.concat([pairs["_i"], pairs["_i_b"]]).unique()
    return (i.filter(~pl.col("_i").is_in(gone.implode())).drop("_i"),
            i.filter(pl.col("_i").is_in(gone.implode())).drop("_i"))


# Halves whose semi-annual review left a required index alone, checked against the release: in 2010-H2 the
# 2010-08-18 review covered Nifty 50, Junior and sectoral indices only (CNX 500 / CNX Midcap were not reviewed).
NO_CHANGE = {("2010-H2", "NIFTY500"), ("2010-H2", "MIDCAP")}
# unserved PDFs whose title names a target index (the rest are fixed-income, SDL, IPO, SME); no archive.org copy
MISSING_TARGET = {"ind_prs02032012.pdf": "Change in S&P CNX 500 Index w.e.f March 7, 2012 (ad hoc)"}


def review_check(ch: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    """One row per half-year (H1 = announced Jan-Jun, H2 = Jul-Dec) with the review releases found and the
    add/remove counts per index. Review rows are kind scheduled or criteria_revision (a criteria change applied at a
    semi-annual review, 2016-02). A half is complete when Next 50, Nifty 500 and a Midcap index (100 or 150) all
    have review rows, or are in NO_CHANGE; Nifty 50 is not required (some reviews leave it). Per half, not per
    release: the 2014-08-26 Midcap review came out a week after the rest. A review section mislabelled ad hoc shows
    in report's mixed-kind list instead."""
    s = ch.filter(pl.col("kind").is_in(["scheduled", "criteria_revision"]), pl.col("announced").is_between(start, end))
    s = s.with_columns(half=pl.format("{}-H{}", pl.col("announced").dt.year(),
                                      pl.when(pl.col("announced").dt.month() <= 6).then(1).otherwise(2)))
    per = s.group_by("half", "index").agg(a=(pl.col("side") == "add").sum(), r=(pl.col("side") == "remove").sum())
    txt = (per.with_columns(c=pl.format("{}+{}-{}", "index", "a", "r")).group_by("half")
           .agg(pl.col("c").sort().str.join(" ")))
    req = pl.when(pl.col("index").str.starts_with("MIDCAP")).then(pl.lit("MIDCAP")).otherwise("index")
    have = set(s.select("half", req).iter_rows()) | NO_CHANGE
    rel = s.group_by("half").agg(releases=pl.col("announced").unique().sort().cast(pl.Utf8).str.join(","))
    halves = pl.DataFrame({"half": [f"{y}-H{h}" for y in range(start.year, end.year + 1) for h in (1, 2)]})
    lacking = pl.DataFrame({"half": halves["half"], "lacking": [
        " ".join(r for r in ("NEXT50", "NIFTY500", "MIDCAP") if (h, r) not in have) for h in halves["half"]]})
    return (halves.join(rel, on="half", how="left").join(txt, on="half", how="left").join(lacking, on="half")
            .with_columns(complete=pl.col("lacking") == ""))


def report(ch: pl.DataFrame, missing: list[str], unread: list[str], cancelled: pl.DataFrame) -> str:
    dev = review_check(ch, date(2010, 1, 1), date(2018, 12, 31))
    later = review_check(ch, date(2019, 1, 1), ch["announced"].max())
    # a serial seen twice in one table means two tables were merged under one header
    dup = ch.filter(pl.len().over("source_url", "effective", "index", "side", "serial") > 1) \
        .select("source_url", "index", "side", "serial", "symbol").sort("source_url", "index", "side", "serial")
    # a review release whose target indices disagree on kind (2020-02-18 once had its Nifty 500 section ad hoc);
    # legitimate when one section has its own reason (2016-10-17 Cairn amalgamation)
    mixed = (ch.filter((pl.col("kind") == "ad_hoc").any().over("source_url")
                       & (pl.col("kind") == "scheduled").any().over("source_url"))
             .group_by("source_url", "index", "kind").len().sort("source_url", "index", "kind"))
    moved = ch.filter(pl.col("rescheduled_by").is_not_null()).select("announced", "effective", "index", "side",
                                                                       "symbol", "rescheduled_by")
    target_missing = [m for m in missing if m.rsplit("/", 1)[-1] in MISSING_TARGET]
    unbal = (ch.group_by("source_url", "index", "kind").agg(a=(pl.col("side") == "add").sum(),
                                                             r=(pl.col("side") == "remove").sum())
             .filter(pl.col("a") != pl.col("r")))
    bad = ch.filter(~pl.col("valid"))
    datediff = ch.filter(pl.col("announced_pdf").is_not_null() & (pl.col("announced_pdf") != pl.col("listed"))) \
        .select("source_url", "listed", "announced_pdf").unique()
    with pl.Config(tbl_rows=-1, tbl_width_chars=220, fmt_str_lengths=120, tbl_hide_dataframe_shape=True):
        return "\n".join([
            f"rows {ch.height}; releases {ch['source_url'].n_unique()}; by kind {dict(ch['kind'].value_counts().iter_rows())}",
            f"symbol source {dict(ch['symbol_source'].value_counts().iter_rows())}",
            f"PDFs not served ({len(missing)}): " + ", ".join(missing),
            f"of which change a target index, rows MISSING from the archive ({len(target_missing)}): "
            + "; ".join(f"{m} = {MISSING_TARGET[m.rsplit('/', 1)[-1]]}" for m in target_missing),
            f"index-name-table PDFs naming a target index, not yet read into HAND ({len(unread)}): " + ", ".join(unread),
            f"\nDEV semi-annual reviews complete (Next 50, Nifty 500, Midcap all present; NO_CHANGE {sorted(NO_CHANGE)}): "
            f"{dev['complete'].sum()} of {dev.height} half-years", str(dev),
            f"\n2019 onwards: {later['complete'].sum()} of {later.height} half-years complete", str(later),
            f"\nduplicate serials within a table, i.e. merged tables ({dup.height}):", str(dup),
            f"\nreleases mixing scheduled and ad hoc target sections ({mixed['source_url'].n_unique()}):", str(mixed),
            f"\nchanges re-announced before taking effect: first announcement kept, effective date moved ({moved.height}):",
            str(moved.sort("announced")),
            f"\nrows left out ({cancelled.height}): voided = 2020-03-27 changes declared null and void by "
            f"{VOIDED[3]}; cancelled = undone by the opposite change before taking effect (both rows)",
            str(cancelled.group_by("why", "source_url", "effective", "index").len()
                .sort("why", "source_url", "effective", "index")),
            str(cancelled.filter(pl.col("why") == "cancelled")
                .select("announced", "effective", "index", "side", "symbol", "kind", "source_url")
                .sort("index", "symbol", "announced")),
            "\nhand-coded (HAND): revocations of 2024-03-19 (IREDA) and 2024-09-25 (IDEA) undo parts of the 2024-02 and "
            "2024-08 reviews (REVOKED); Next 50 of 2021-08-23 (scanned PDF); ad hoc exclusions listed by index name "
            "(spun-off entities, TATAMTRDVR); VOIDED (2020-03-27 changes, ind_prs13052020) and REDATED (2013-11-07 "
            "changes effective 2013-11-18, ind_prs13112013). Zero-price dummy inclusions of demerged entities are left out: holders "
            "receive those shares, nobody buys them. Other scans (<100 chars/page) checked by eye, none touch a target "
            "index: ind_prs10092018, 18092018, 24092018(_1), 25092018, 23082021_1",
            "REIT/InvIT units (e.g. EMBASSY, 2026-08) trade outside the EQ/BE series, so they show as invalid below",
            f"\nadds != removes per release and index ({unbal.height}; DVR additions and mergers are legitimate):",
            str(unbal.sort("source_url")),
            f"\nrows without an effective date ({ch['effective'].null_count()}):",
            str(ch.filter(pl.col("effective").is_null()).select("announced", "index", "side", "symbol", "source_url")),
            f"\nrows without a valid symbol ({bad.height}):",
            str(bad.select("announced", "index", "side", "name", "symbol", "symbol_source", "source_url")),
            f"\nPDF date != listing date ({datediff.height}):", str(datediff.sort("listed")),
        ])


if __name__ == "__main__":
    from research import equity

    s = requests.Session()
    s.headers.update(HEADERS)
    lst = candidates(listing(s))
    ROOT.mkdir(parents=True, exist_ok=True)
    lst.write_csv(ROOT / "listing.csv")
    missing = fetch(s, lst["path"].to_list())
    traded = equity.load().group_by("symbol").agg(first=pl.col("date").min(), last=pl.col("date").max())
    ch, unread, cancelled = build(lst, traded)
    ch.write_parquet(ROOT / "changes.parquet")
    txt = report(ch, missing, unread, cancelled)
    (ROOT / "report.txt").write_text(txt, encoding="utf-8")
    print(txt)
