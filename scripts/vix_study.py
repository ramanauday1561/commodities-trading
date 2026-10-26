"""Experiment mode "vix" (26 Oct 2026): does India VIX help the from-open signal?

India VIX was tested as an input to the close call (preopen_study, Oct 2026) and did not help. Tested here, for the
from-open signal (top-20% most confident days, walk-forward, ~0.03% costs), with VIX known before the open (the
previous session's close):
  input    VIX change on the previous session and its level against the past year as two extra inputs
  filters  stand aside when VIX is high (level in the top third of the past year), when it rose more than 5% on the
           previous session, or when it fell more than 5%
Also reported: the from-open trades and the size of NIFTY's open-to-close move by VIX level (low / middle / high
third of the past year), to see whether VIX changes what a trade earns.
Rule fixed before the run: a variant passes only if its trades earn more per trade than the live signal in both
halves and in total, and for a filter, the trades it skips lose money. With several variants tried, a pass that only
just clears the live signal is treated as luck.
"""
import json

import numpy as np
import pandas as pd

import todaycall as tc
from accuracy_study import _wf_tiers
from preopen_study import daily_close


def vix_features(index, vix):
    chg, z, pct = [], [], []
    for d in index:
        pv = vix.loc[:d - pd.Timedelta(days=1)]                     # up to the previous session's close
        if len(pv) > 30:
            hist = pv.iloc[-250:]
            chg.append(float(np.log(pv.iloc[-1] / pv.iloc[-2])))
            z.append(float((pv.iloc[-1] - hist.mean()) / (hist.std() + 1e-9)))
            pct.append(float((hist < pv.iloc[-1]).mean()))
        else:
            chg.append(0.0), z.append(0.0), pct.append(0.5)
    return np.array(chg), np.array(z), np.array(pct)


def stats(pnl):
    if not len(pnl):
        return {"trades": 0}
    k = len(pnl) // 2
    return {"trades": int(len(pnl)), "win": round(float((pnl > 0).mean()), 3), "avg_pct": round(float(pnl.mean()), 3),
            "total_pct": round(float(pnl.sum()), 2),
            "avg_halves": [round(float(pnl[:k].mean()), 3) if k else None, round(float(pnl[k:].mean()), 3)]}


def passes(v, live):
    return (v.get("trades", 0) >= 20 and v["total_pct"] > live["total_pct"]
            and all(a is not None and b is not None and a > b for a, b in zip(v["avg_halves"], live["avg_halves"])))


def main():
    try:
        nd = tc.daily()
        nd = nd[nd.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
        series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
        df = tc.history(nd, series)
        vix = daily_close("^INDIAVIX")
        vix.index = pd.to_datetime(vix.index).tz_localize(None) if getattr(vix.index, "tz", None) else pd.to_datetime(vix.index)
        idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
        chg, z, pct = vix_features(idx, vix)
        df["vix_chg"], df["vix_z"] = chg, z
        o2c = (1 + df["day"].values) / (1 + df["gap"].values) - 1
        out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date()),
               "vix_last": round(float(vix.iloc[-1]), 2), "vix_rows": int((z != 0).sum())}

        p, tiers = _wf_tiers(df[tc.OPEN_FEATS].values, o2c)
        top = np.isin(tiers, tc.TRADE_TIERS)
        pnl = np.sign(p) * o2c * 100 - tc.TRADE_COST_PCT
        live = stats(pnl[top])
        out["live"] = live

        p2, t2 = _wf_tiers(df[tc.OPEN_FEATS + ["vix_chg", "vix_z"]].values, o2c)
        top2 = np.isin(t2, tc.TRADE_TIERS)
        out["input_vix"] = stats((np.sign(p2) * o2c * 100 - tc.TRADE_COST_PCT)[top2])
        out["input_vix"]["passes"] = passes(out["input_vix"], live)

        for name, skip in (("skip_high_vix", pct > 2 / 3), ("skip_vix_up_5pct", chg > np.log(1.05)),
                           ("skip_vix_down_5pct", chg < np.log(0.95))):
            kept, skipped = stats(pnl[top & ~skip]), stats(pnl[top & skip])
            out[name] = {"kept": kept, "skipped": skipped, "sessions_skipped": int(skip.sum()),
                         "passes": passes(kept, live) and skipped.get("trades", 0) > 0 and skipped["avg_pct"] < 0}

        out["by_vix_level"] = {}
        for name, m in (("low", pct <= 1 / 3), ("middle", (pct > 1 / 3) & (pct <= 2 / 3)), ("high", pct > 2 / 3)):
            out["by_vix_level"][name] = {"sessions": int(m.sum()), "abs_o2c_pct": round(float(np.abs(o2c[m]).mean() * 100), 3),
                                         "trades": stats(pnl[top & m])}
        out["passed"] = [k for k, v in out.items() if isinstance(v, dict) and v.get("passes")]
        print("STUDY vix " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY vix failed: {e!r}", flush=True)
