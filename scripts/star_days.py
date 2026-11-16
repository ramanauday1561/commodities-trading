"""The nine-year yardstick for one day of automatic * picks (16 Nov 2026, for the Money and Next 10 pages' "today vs the
backtest" line): per number of * picks in a day, the spread of the day's Rs after costs under the server's rule (ATM
option, 1 lot, 10% stop, out after 30 minutes), priced as star_target_study's nine-year layer (stops booked at the
10-minute close they are seen at). Not a test of anything: a yardstick, so one day is read against nine years.

Usage: INTRADAY_DIR=... OPTLIVE_DIR=... python scripts/star_days.py > docs/star-days.json
"""
import json
import os

import numpy as np
import pandas as pd


def main():
    import intraday_data
    import leanfilter_study as lf
    import nextcandle_study as ns
    import star_target_study as st
    import star_hold_study as sh
    optlive = os.environ.get("OPTLIVE_DIR", "optlive")
    cal = lf.calibrate(optlive)
    b, a = (cal["b"], cal["a"]) if cal.get("pairs", 0) >= 100 else (0.5, 0.0)
    df = ns.rows(*(intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), k) for k in ("nifty", "banknifty", "vix")), h=1)
    t = lf.walk_forward(df)
    t = t[~((t["d"] >= sh.CAS_FROM) & (t["k"] >= sh.CAS_K))].sort_values(["d", "k"])
    p = st.nine_year(t, b, a)
    ok = t["star"].values & sh.forward(t, 3)[0].notna().values
    p["d"] = t["d"].values[ok]
    trade = p["today (10% stop)"]
    days = p.assign(rs=trade).groupby("d")["rs"].agg(["sum", "count"])
    by_n = {}
    for n in range(1, 7):
        s = days["sum"][days["count"] == n] if n < 6 else days["sum"][days["count"] >= 6]
        if len(s) >= 30:
            by_n[str(n)] = {"days": int(len(s)), "p10": int(s.quantile(.1)), "p50": int(s.quantile(.5)), "p90": int(s.quantile(.9)),
                            "up_share": round(float((s > 0).mean()), 3), "q": [int(s.quantile(x / 20)) for x in range(21)]}
    out = {"made": pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d"), "from": str(t["d"].min()), "to": str(t["d"].max()),
           "rule": "ATM option, 1 lot, 10% stop, out after 30 minutes", "per_trade": int(round(trade.mean())),
           "trade_p10": int(trade.quantile(.1)), "trade_p90": int(trade.quantile(.9)), "right": round(float((trade > 0).mean()), 3),
           "star_days_share": round(len(days) / t["d"].nunique(), 3), "by_picks": by_n}
    print(json.dumps(out, separators=(",", ":")))


if __name__ == "__main__":
    main()
