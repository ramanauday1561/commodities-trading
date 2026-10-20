"""Diagnostic (20 Oct 2026): does the CL=F contract roll distort the NIFTY pre-open crude input?

WTI's November contract expires 20 Oct 2026; Yahoo's CL=F then switches to December, which trades lower (backwardation),
so the 'crude' move from Monday's NIFTY close looks like a bigger fall than oil had. Prints the recent bars of CL=F, Brent
and the dated contracts, the call for the next session previewed now with crude as is / Brent / zero, and how often
CL=F and Brent disagreed by > 2% in the history (roll days).
"""
import json
from datetime import date

import numpy as np
import pandas as pd

import todaycall as tc
from accuracy_study import _wf_tiers

PROBE = ["CL=F", "BZ=F", "CLX26.NYM", "CLZ26.NYM", "BZZ26.NYM", "BZF27.NYM"]


def bars():
    out = {}
    for t in PROBE:
        try:
            s = tc.hourly(t, period="5d")
            s = s[s.index >= pd.Timestamp("2026-10-19 08:00", tz="UTC")]
            out[t] = {str(k)[5:16]: round(float(v), 2) for k, v in s.items()}
        except Exception as e:
            out[t] = repr(e)
    return out


def preview(nd, series, day, now):
    df = tc.history(nd, series)
    gap, d = df["gap"].values, df["day"].values
    o2c = (1 + d) / (1 + gap) - 1
    cutoff = min(now, tc.utc_at(day, tc.CUTOFF))
    prev_day = nd.index[-1].date()
    f = tc.overnight_features(series, prev_day, day, cutoff, nd["close"].iloc[-1] / nd["close"].iloc[-2] - 1)
    x = np.array([f[k] for k in tc.FRESH_FEATS])
    X = df[tc.FRESH_FEATS].values
    close, fo = tc.call_block(X, d, x, o2c), tc.call_block(X, o2c, x, o2c)
    m = tc.ridge_fit(X, d)
    per1 = {k: round(float(w / s) * 1e-2 * 100, 3) for k, w, s in zip(tc.FRESH_FEATS, m[2], m[1])}
    return df, {"moves_pct": {k: round(v * 100, 2) for k, v in f.items()},
                "close": {k: close[k] for k in ("direction", "pred_pct", "tier")},
                "from_open": {k: fo[k] for k in ("direction", "pred_pct", "tier")},
                "nifty_pct_per_1pct_input": per1}


def score(df, feats):
    out = {}
    o2c = (1 + df["day"].values) / (1 + df["gap"].values) - 1
    for name, y in (("close", df["day"].values), ("from_open", o2c)):
        p, tiers = _wf_tiers(df[feats].values, y)
        ok = tiers != "na"
        hit = np.sign(p) == np.sign(y)
        strong = ok & np.isin(tiers, ["very_strong", "strong"])
        out[name] = {"days": int(ok.sum()), "hit_all": round(float(hit[ok].mean()), 3),
                     "hit_top20": round(float(hit[strong].mean()), 3), "top20_days": int(strong.sum()),
                     "top20_from_open_avg_pct": round(float((np.sign(p[strong]) * o2c[strong]).mean() * 100 - 0.03), 3)}
    return out


def main():
    out = {"bars": bars()}
    nd_all = tc.daily()
    day = date(2026, 10, 21)
    nd = nd_all[nd_all.index.date < day]
    now = pd.Timestamp.now(tz="UTC")
    series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
    brent = tc.hourly("BZ=F")
    df, out["preview_cl"] = preview(nd, series, day, now)
    df_bz, out["preview_brent"] = preview(nd, {**series, "crude": brent}, day, now)
    flat = {**series, "crude": pd.Series(1.0, index=series["crude"].index)}
    _, out["preview_no_crude_move"] = preview(nd, flat, day, now)
    j = df.join(df_bz[["crude"]], rsuffix="_bz")
    diff = (j["crude"] - j["crude_bz"]).abs()
    out["cl_vs_brent_gt2pct"] = {str(k.date()): [round(j.loc[k, "crude"] * 100, 2), round(j.loc[k, "crude_bz"] * 100, 2)]
                                 for k in diff[diff > 0.02].index}
    out["backtest_cl"] = score(df, tc.FRESH_FEATS)
    out["backtest_brent"] = score(df_bz, tc.FRESH_FEATS)
    out["backtest_no_crude"] = score(df, [k for k in tc.FRESH_FEATS if k != "crude"])
    print("STUDY crudeprobe " + json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
