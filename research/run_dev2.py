"""Pre-registered v2 DEV grid (docs/plans/20261017-real-chain-pcs-preregistration-v2.md §2-§3). Run: python -m research.run_dev2"""
import itertools
import sys
from datetime import date

import polars as pl

from research import bhavcopy, metrics
from research.engine import Chain, Config
from research.run_dev import BANDS, END, START, eligible, evaluate

MODE_RANK = {"hold": 0, "stop2x": 1}


def grid():
    for w, d, cw, m, b in itertools.product((100, 200), (0.25, 0.30), (0.08, 0.12), ("hold", "stop2x"), BANDS):
        yield Config(width=w, delta=d, min_cw=cw, exit_mode=m, dte_lo=b[0], dte_hi=b[1])


def stress_loss(r, cfg):  # winner must lose <= 8% of equity0 in Feb-Mar 2020 (mid slip)
    ts = metrics.window(r["mid"][0], date(2020, 2, 1), date(2020, 3, 31))
    return sum(t.pnl for t in ts) / cfg.equity0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    chain = Chain(bhavcopy.load(START, date(2024, 1, 31)))
    rows, res = [], {}
    for cfg in grid():
        r = evaluate(chain, cfg, START, END)
        res[cfg] = r
        m, h = r["mid"][1], r["high"][1]
        row = dict(w=cfg.width, d=cfg.delta, cw=cfg.min_cw, mode=cfg.exit_mode, band=f"{cfg.dte_lo}-{cfg.dte_hi}", n=m.get("n", 0))
        if row["n"]:
            row.update(win=round(m["win_rate"], 3), pf=round(m["pf"], 2), pf_hi=round(h.get("pf", 0), 2),
                       exp=round(m["expectancy"]), cagr=round(m["cagr"], 4), at_cagr=round(m["after_tax_cagr"], 4),
                       dd=round(m["max_dd"], 3), worst=round(m["worst_trade_pct"], 4),
                       s2020=round(stress_loss(r, cfg), 4), ok=eligible(r) and stress_loss(r, cfg) >= -0.08)
        rows.append(row)
    df = pl.DataFrame(rows, infer_schema_length=None)
    pl.Config.set_tbl_rows(100); pl.Config.set_tbl_cols(30); pl.Config.set_tbl_width_chars(250)
    print(df)
    df.write_csv("data/bhavcopy/dev_grid_v2.csv")
    cands = [c for c in res if res[c]["mid"][1].get("n") and eligible(res[c]) and stress_loss(res[c], c) >= -0.08]
    if not cands:
        print("\nNO ELIGIBLE CANDIDATE -> verdict FAIL, OOS never run, no v3.")
    else:
        key = lambda c: (-res[c]["mid"][1]["cagr"] / res[c]["mid"][1]["max_dd"], c.width, c.delta, -c.min_cw,
                         MODE_RANK[c.exit_mode], c.dte_lo)
        w = min(cands, key=key)
        print("\nDEV WINNER:", w)
        for name in ("low", "mid", "high"):  # §5 full report for the winner only
            print(name, res[w][name][1])
        dropped: list = []
        from research.engine import run
        run(chain, w, START, END, dropped)
        print("entries dropped (open at data end):", len(dropped))
