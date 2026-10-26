"""Experiment mode "streak" (26 Oct 2026): does the last few days' run help the from-open signal?

26 Oct 2026: NIFTY had lost 2.36% over four sessions, opened lower on Infosys and rallied 1.6% from the low ("bargain
buying after a four-day fall"). The signal only knows the previous day's move (prev_day). Tested, with closes known
before the open: the 3-day and 5-day move to the previous close, and the number of down (or up) closes in a row
(negative for down), as extra inputs to the from-open signal (top-20% most confident days, walk-forward, ~0.03% costs).
Also reported: the average open-to-close move after 3+ down closes in a row vs other days.
Rule fixed before the run (as vix_study): more per trade than the live signal in both halves and in total.
"""
import json

import numpy as np
import pandas as pd

import todaycall as tc
from accuracy_study import _wf_tiers
from vix_study import passes, stats


def streak_features(nd, index):
    c = nd["close"]
    pos = {d: i for i, d in enumerate(nd.index)}
    r3, r5, run = [], [], []
    for d in index:
        i = pos[d]
        r3.append(float(c.iloc[i - 1] / c.iloc[i - 4] - 1) if i >= 4 else 0.0)
        r5.append(float(c.iloc[i - 1] / c.iloc[i - 6] - 1) if i >= 6 else 0.0)
        n, j = 0, i - 1
        sign = np.sign(c.iloc[j] - c.iloc[j - 1]) if j >= 1 else 0
        while j >= 1 and sign != 0 and np.sign(c.iloc[j] - c.iloc[j - 1]) == sign:
            n, j = n + 1, j - 1
        run.append(float(n * sign))
    return np.array(r3), np.array(r5), np.array(run)


def main():
    try:
        nd = tc.daily()
        nd = nd[nd.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
        series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
        df = tc.history(nd, series)
        df["ret3"], df["ret5"], df["streak"] = streak_features(nd, df.index)
        o2c = (1 + df["day"].values) / (1 + df["gap"].values) - 1
        out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date())}
        p, tiers = _wf_tiers(df[tc.OPEN_FEATS].values, o2c)
        top = np.isin(tiers, tc.TRADE_TIERS)
        live = stats((np.sign(p) * o2c * 100 - tc.TRADE_COST_PCT)[top])
        out["live"] = live
        for name, extra in (("ret3", ["ret3"]), ("ret5", ["ret5"]), ("streak", ["streak"]), ("all_three", ["ret3", "ret5", "streak"])):
            p2, t2 = _wf_tiers(df[tc.OPEN_FEATS + extra].values, o2c)
            top2 = np.isin(t2, tc.TRADE_TIERS)
            v = stats((np.sign(p2) * o2c * 100 - tc.TRADE_COST_PCT)[top2])
            v["passes"] = passes(v, live)
            out[f"input_{name}"] = v
        down3 = df["streak"].values <= -3
        out["after_3_down_closes"] = {"sessions": int(down3.sum()), "avg_o2c_pct": round(float(o2c[down3].mean() * 100), 3),
                                      "up_share": round(float((o2c[down3] > 0).mean()), 3),
                                      "other_avg_o2c_pct": round(float(o2c[~down3].mean() * 100), 3),
                                      "other_up_share": round(float((o2c[~down3] > 0).mean()), 3)}
        out["passed"] = [k for k, v in out.items() if isinstance(v, dict) and v.get("passes")]
        print("STUDY streak " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY streak failed: {e!r}", flush=True)
