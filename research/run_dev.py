"""Pre-registered DEV grid (docs/plans/20261016-real-chain-pcs-preregistration.md §3-§4). Run: python -m research.run_dev"""
import itertools
import sys
from datetime import date

import polars as pl

from research import bhavcopy, metrics
from research.engine import EXIT_MODES, Chain, Config, run

START, END = date(2019, 1, 1), date(2023, 12, 31)
BANDS = ((3, 10), (10, 17))
MODE_RANK = {"hold": 0, "mgmt": 1, "stop2x": 2}


def grid():
    for w, d, m, b in itertools.product((100, 200, 300), (0.15, 0.20, 0.25), EXIT_MODES, BANDS):
        yield Config(width=w, delta=d, exit_mode=m, dte_lo=b[0], dte_hi=b[1])


def evaluate(chain, cfg, start, end):
    out = {}
    for name, slip in (("low", 0.25), ("mid", 0.5), ("high", 1.0)):
        c = Config(**{**cfg.__dict__, "slip": slip})
        ts = run(chain, c, start, end)
        out[name] = (ts, metrics.summarize(ts, cfg.equity0, start, end))
    return out


def eligible(r):
    m, h = r["mid"][1], r["high"][1]
    return (m.get("n", 0) >= 100 and h.get("pf", 0) >= 1.2 and m["max_dd"] <= 0.25
            and -m["worst_trade_pct"] <= 0.035)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    chain = Chain(bhavcopy.load(START, date(2024, 1, 31)))
    rows, res = [], {}
    for cfg in grid():
        r = evaluate(chain, cfg, START, END)
        res[cfg] = r
        m, h = r["mid"][1], r["high"][1]
        if m.get("n", 0) == 0:
            rows.append(dict(w=cfg.width, d=cfg.delta, mode=cfg.exit_mode, band=f"{cfg.dte_lo}-{cfg.dte_hi}", n=0, ok=False))
            continue
        rows.append(dict(w=cfg.width, d=cfg.delta, mode=cfg.exit_mode, band=f"{cfg.dte_lo}-{cfg.dte_hi}", n=m["n"],
                         win=round(m["win_rate"], 3), pf=round(m["pf"], 2), pf_hi=round(h.get("pf", 0), 2),
                         pf_lo=round(r["low"][1].get("pf", 0), 2), exp=round(m["expectancy"]), cagr=round(m["cagr"], 4),
                         at_cagr=round(m["after_tax_cagr"], 4), dd=round(m["max_dd"], 3),
                         worst=round(m["worst_trade_pct"], 4), calmar=round(m["cagr"] / m["max_dd"], 2) if m["max_dd"] else None,
                         ok=eligible(r)))
    df = pl.DataFrame(rows)
    pl.Config.set_tbl_rows(100); pl.Config.set_tbl_cols(30); pl.Config.set_tbl_width_chars(250)
    print(df)
    df.write_csv("data/bhavcopy/dev_grid.csv")
    cands = [c for c in res if eligible(res[c])]
    if not cands:
        print("\nNO ELIGIBLE CANDIDATE -> verdict FAIL, OOS never run.")
    else:
        key = lambda c: (-res[c]["mid"][1]["cagr"] / res[c]["mid"][1]["max_dd"], c.width, c.delta, MODE_RANK[c.exit_mode])
        w = min(cands, key=key)
        print("\nDEV WINNER:", w)
