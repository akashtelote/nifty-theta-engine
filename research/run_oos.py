"""One-shot v2 OOS run (docs/plans/20261017-real-chain-pcs-preregistration-v2.md §4, §6). Run: python -m research.run_oos
Refuses if data/bhavcopy/OOS_RUN.lock exists; the lock is created BEFORE any OOS data is touched."""
import sys
from datetime import date
from pathlib import Path

import polars as pl

from research import bhavcopy, metrics
from research.engine import Chain, Config, forward, run
from research.run_dev import evaluate

LOCK = Path("data/bhavcopy/OOS_RUN.lock")
OOS_START = date(2024, 1, 1)
WINNER = Config(width=200, delta=0.25, min_cw=0.08, exit_mode="hold", dte_lo=3, dte_hi=10)  # v2 DEV winner (A3-corrected)


def index_series(chain):
    """(date, parity-forward of the nearest expiry) daily; price-only index proxy covering the full OOS window."""
    out = []
    for d in chain.dates:
        day = chain.days[d]
        exps = sorted(e for e in day["expiry"].unique().to_list() if e >= d)
        f = next((x for x in (forward(day, e) for e in exps[:2]) if x), None)
        if f:
            out.append((d, f))
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if LOCK.exists():
        sys.exit("OOS already run (lock exists) - refusing.")
    LOCK.write_text("v2 OOS run started\n")
    dev = pl.read_csv("data/bhavcopy/dev_grid_v2.csv")
    dev_pf = dev.filter((pl.col("w") == 200) & (pl.col("d") == 0.25) & (pl.col("cw") == 0.08)
                        & (pl.col("mode") == "hold") & (pl.col("band") == "3-10"))["pf"][0]
    chain = Chain(bhavcopy.load(OOS_START, date(2026, 12, 31)))
    end = chain.dates[-1]
    r = evaluate(chain, WINNER, OOS_START, end)
    dropped: list = []
    run(chain, Config(**{**WINNER.__dict__, "slip": 0.5}), OOS_START, end, dropped)
    m, h = r["mid"][1], r["high"][1]
    for name in ("low", "mid", "high"):
        print(name, r[name][1])
    print("entries dropped (open at data end):", len(dropped), " window end:", end)

    px = index_series(chain)
    bench = metrics.benchmark_cagr([p for p in px if p[0] >= OOS_START])
    ts = r["mid"][0]
    # stress windows: 4 Jun 2024 +-5 trading days; 5 largest index gap-down days (close-to-close, proxy)
    dts = [d for d, _ in px]
    i = min(range(len(dts)), key=lambda k: abs((dts[k] - date(2024, 6, 4)).days))
    w1 = (dts[max(i - 5, 0)], dts[min(i + 5, len(dts) - 1)])
    chg = sorted(((px[k][1] / px[k - 1][1] - 1, px[k][0]) for k in range(1, len(px))))[:5]
    stress = {"2024-06-04+-5td": sum(t.pnl for t in metrics.window(ts, *w1)) / WINNER.equity0}
    for c, d in chg:
        stress[f"gapdown {d} ({c:.2%})"] = sum(t.pnl for t in metrics.window(ts, d, d)) / WINNER.equity0
    print("stress (P&L % equity0):", stress)
    print("benchmark price CAGR (index proxy):", bench)

    crit = {
        "1 n>=40": m.get("n", 0) >= 40,
        "2 PF>=1.30@0.5 & >1.0@1.0": m.get("pf", 0) >= 1.30 and h.get("pf", 0) > 1.0,
        "3 expectancy CI lo>0": m.get("n", 0) > 0 and m["expectancy_ci"][0] > 0,
        "4 maxDD<=20%": m.get("n", 0) > 0 and m["max_dd"] <= 0.20,
        "5 worst trade<=3.5% & week<=6%": m.get("n", 0) > 0 and -m["worst_trade_pct"] <= 0.035 and -m["worst_week_pct"] <= 0.06,
        "6 after-tax CAGR>bench & >=7%": m.get("n", 0) > 0 and m["after_tax_cagr"] > bench and m["after_tax_cagr"] >= 0.07,
        "7 no stress loss>8%": all(v >= -0.08 for v in stress.values()),
        "8 OOS PF>=0.7*DEV PF": m.get("pf", 0) >= 0.7 * dev_pf,
        "9 PF CI lo>1.0": m.get("n", 0) > 0 and m["pf_ci"][0] > 1.0,
    }
    for k, v in crit.items():
        print(("PASS " if v else "FAIL ") + k)
    print("VERDICT:", "INCONCLUSIVE" if m.get("n", 0) < 40 else ("PASS" if all(crit.values()) else "FAIL"), "| DEV PF", dev_pf)
