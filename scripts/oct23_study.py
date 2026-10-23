"""Experiment mode "oct23" (23 Oct 2026): three ideas from 23 Oct, tested before any change.

At 06:33 the pre-open call said "down, very strong"; by 08:57 it was "slightly up, no view", mainly because Infosys's
ADR rose 3.8% ahead of Infosys's own results that evening. NIFTY opened +0.24% and fell about 1% from the open.
  A. ADRs on their own company's results: a run-up or reaction in HDFC Bank / ICICI / Infosys around their own results
     is about that stock, not the market. Variants: drop the ADR input on those sessions, or keep only its move in
     excess of the Nasdaq (nq) move.
  B. Earlier cutoff: the same models with overnight inputs up to 06:33 IST instead of 09:10 IST.
  C. High oil: are the calls worse after Brent rose sharply over the past week, and does a 5-day Brent input help?
Every variant: walk-forward (each day's model from earlier days only), close call, gap call and from-open signal,
scored on all days, the top-20% most confident (cut-off from earlier days), after ~0.03% costs, and in both halves.
"""
import json

import numpy as np
import pandas as pd

import todaycall as tc
from accuracy_study import _wf_tiers
from preopen_study import results_dates

ADR = {"hdb": "HDFCBANK", "ibn": "ICICIBANK", "infy": "INFY"}


def score(df, feats):
    day, gap = df["day"].values, df["gap"].values
    o2c = (1 + day) / (1 + gap) - 1
    out = {}
    for name, y, f in (("close", day, feats), ("gap", gap, [k for k in feats if k not in ("prev_day",)] or feats),
                       ("from_open", o2c, [k for k in feats if k != "crude"])):
        p, tiers = _wf_tiers(df[f].values, y)
        ok, top = tiers != "na", np.isin(tiers, ["very_strong", "strong"])
        hit = np.sign(p) == np.sign(y)
        idx = np.where(ok)[0]
        h = len(idx) // 2
        r = {"days": int(ok.sum()), "hit": round(float(hit[ok].mean()), 3),
             "halves": [round(float(hit[idx[:h]].mean()), 3), round(float(hit[idx[h:]].mean()), 3)],
             "top20_hit": round(float(hit[top].mean()), 3) if top.any() else None}
        if name == "from_open":
            pnl = np.sign(p[top]) * o2c[top] * 100 - tc.TRADE_COST_PCT
            k = len(pnl) // 2
            r.update({"trades": int(top.sum()), "win": round(float((pnl > 0).mean()), 3), "avg_pct": round(float(pnl.mean()), 3),
                      "avg_halves": [round(float(pnl[:k].mean()), 3), round(float(pnl[k:].mean()), 3)]})
        out[name] = r
    return out


def main():
    try:
        nd = tc.daily()
        nd = nd[nd.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
        series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
        base = tc.history(nd, series)
        out = {"days": len(base), "from": str(base.index[0].date()), "to": str(base.index[-1].date())}
        out["live"] = score(base, tc.FRESH_FEATS)

        # A. ADRs around their own company's results (results dated from the previous session up to this session)
        rd = results_dates()
        days = list(nd.index)
        pos = {d: i for i, d in enumerate(days)}
        own = {}
        for k, name in ADR.items():
            ds = next((v for t, v in rd.items() if t.startswith(name)), [])
            own[k] = np.array([pos.get(d, 0) > 0 and any(days[pos[d] - 1] <= x <= d for x in ds) for d in base.index])
        out["A_sessions_flagged"] = {k: int(v.sum()) for k, v in own.items()}
        drop, excess = base.copy(), base.copy()
        for k, m in own.items():
            drop.loc[m, k] = 0.0
            excess.loc[m, k] = base.loc[m, k] - base.loc[m, "nq"]
        out["A_drop_on_results"] = score(drop, tc.FRESH_FEATS)
        out["A_excess_on_results"] = score(excess, tc.FRESH_FEATS)

        # B. overnight inputs up to 06:33 IST (01:03 UTC) instead of 09:10 IST
        saved = tc.CUTOFF
        try:
            tc.CUTOFF = (1, 3)
            early = tc.history(nd, series)
        finally:
            tc.CUTOFF = saved
        early = early.reindex(base.index).dropna()
        out["B_cutoff_0633"] = score(early, tc.FRESH_FEATS)
        out["B_live_same_days"] = score(base.loc[early.index], tc.FRESH_FEATS)

        # C. high oil: Brent's 5-day move up to the previous close
        brent = pd.Series(tc.hourly("BZ=F")).resample("1D").last().dropna()
        brent.index = brent.index.tz_localize(None)
        b5 = (brent / brent.shift(5) - 1).shift(1).reindex(base.index.normalize(), method="ffill").fillna(0.0).values
        oil = base.copy()
        oil["brent5"] = b5
        out["C_with_brent5"] = score(oil, tc.FRESH_FEATS + ["brent5"])
        hot = b5 > np.quantile(b5[b5 != 0], 0.8) if (b5 != 0).any() else np.zeros(len(b5), bool)
        p, tiers = _wf_tiers(base[tc.FRESH_FEATS].values, base["day"].values)
        ok = tiers != "na"
        hit = np.sign(p) == np.sign(base["day"].values)
        out["C_close_hit_high_oil_vs_other"] = {"high_oil_days": int((ok & hot).sum()),
                                                "high_oil": round(float(hit[ok & hot].mean()), 3),
                                                "other": round(float(hit[ok & ~hot].mean()), 3)}
        print("STUDY oct23 " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY oct23 failed: {e!r}", flush=True)
