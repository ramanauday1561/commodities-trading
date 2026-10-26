"""Experiment mode "pcr" (26 Oct 2026): does NIFTY's put-call ratio help the from-open signal?

PCR = open interest of NIFTY index puts / calls at the previous session's close, from NSE's daily F&O bhavcopy
(pcr_probe), so it is known before the 09:15 open. Tested on the from-open signal (top-20% most confident days,
walk-forward, ~0.03% costs):
  input           PCR change on the previous session and its level against the past 60 sessions as two extra inputs
  skip_high_pcr   stand aside when PCR is high (z > 1 against the past 60 sessions)
  skip_low_pcr    stand aside when PCR is low (z < -1)
  skip_pcr_jump   stand aside after PCR moved more than 15% in a session
  agree_bull      trade only when the PCR change agrees with the side, reading a rising PCR as bullish (put writing)
  agree_bear      the same, reading a rising PCR as bearish (put buying)
Rule fixed before the run (as vix_study): more per trade than the live signal in both halves and in total, at least
20 trades, and for a filter the trades it skips lose money. Six variants were tried, so a narrow pass is luck.
"""
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

import todaycall as tc
from accuracy_study import _wf_tiers
from pcr_probe import HEAD, pcr
from vix_study import passes, stats


def fetch_pcr(days):
    s = requests.Session()
    try:
        s.get("https://www.nseindia.com/", headers=HEAD, timeout=20)
    except Exception:
        pass

    def one(d):
        for _ in range(3):
            try:
                r = pcr(d, s)
                if r.get("status") == 200:
                    return d, r.get("pcr")
                if r.get("status") == 404:
                    return d, None
            except Exception:
                pass
        return d, None
    with ThreadPoolExecutor(4) as ex:
        return dict(ex.map(one, days))


def main():
    try:
        nd = tc.daily()
        nd = nd[nd.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
        series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
        df = tc.history(nd, series)
        days = [d.date() for d in nd.index]
        first = days.index(df.index[0].date())
        want = days[max(0, first - 65):]
        got = fetch_pcr(want)
        ser = pd.Series({d: v for d, v in got.items() if v}, dtype=float).sort_index()
        pos = {d: i for i, d in enumerate(days)}
        chg, z = [], []
        for d in df.index:
            prev = days[pos[d.date()] - 1]
            h = ser[ser.index <= prev]
            if len(h) > 20 and h.index[-1] == prev:
                chg.append(float(np.log(h.iloc[-1] / h.iloc[-2])))
                w = h.iloc[-60:]
                z.append(float((h.iloc[-1] - w.mean()) / (w.std() + 1e-9)))
            else:
                chg.append(0.0), z.append(0.0)
        chg, z = np.array(chg), np.array(z)
        df["pcr_chg"], df["pcr_z"] = chg, z
        o2c = (1 + df["day"].values) / (1 + df["gap"].values) - 1
        out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date()),
               "pcr_days_downloaded": int(len(ser)), "pcr_days_wanted": len(want), "rows_with_pcr": int((z != 0).sum()),
               "pcr_last": {str(k): v for k, v in ser.tail(3).items()}}

        p, tiers = _wf_tiers(df[tc.OPEN_FEATS].values, o2c)
        top = np.isin(tiers, tc.TRADE_TIERS)
        side = np.sign(p)
        pnl = side * o2c * 100 - tc.TRADE_COST_PCT
        live = stats(pnl[top])
        out["live"] = live

        p2, t2 = _wf_tiers(df[tc.OPEN_FEATS + ["pcr_chg", "pcr_z"]].values, o2c)
        top2 = np.isin(t2, tc.TRADE_TIERS)
        out["input_pcr"] = stats((np.sign(p2) * o2c * 100 - tc.TRADE_COST_PCT)[top2])
        out["input_pcr"]["passes"] = passes(out["input_pcr"], live)

        has = z != 0
        for name, skip in (("skip_high_pcr", z > 1), ("skip_low_pcr", z < -1), ("skip_pcr_jump", np.abs(chg) > np.log(1.15)),
                           ("agree_bull", has & (np.sign(chg) != side)), ("agree_bear", has & (np.sign(chg) != -side))):
            kept, skipped = stats(pnl[top & ~skip]), stats(pnl[top & skip])
            out[name] = {"kept": kept, "skipped": skipped, "sessions_skipped": int(skip.sum()),
                         "passes": passes(kept, live) and skipped.get("trades", 0) > 0 and skipped["avg_pct"] < 0}
        out["passed"] = [k for k, v in out.items() if isinstance(v, dict) and v.get("passes")]
        print("STUDY pcr " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY pcr failed: {e!r}", flush=True)
