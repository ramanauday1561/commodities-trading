"""Experiment mode "resultsize" (25 Oct 2026): how many NIFTY stocks should count as "heavyweight results"?

The from-open signal stands aside on the session after one of the heaviest stocks reports (results_calendar.HEAVY, 11
names). Tested here: the 5, 11, 20 or all 50 heaviest. For each list, the same walk-forward from-open signal (top-20%
most confident days, cut-off from earlier days, ~0.03% costs) trades only on sessions with no result from that list
since the previous session. Reported: the trades kept and what they earned (all, and in both halves), what the skipped
trades would have earned (skipping is only worth it if those lose), how often NIFTY moved more than 1% on flagged vs
other sessions, and which tickers Yahoo could serve dates for.
Rule fixed before the run: switch from 11 only to a list whose kept trades earn more per trade than 11's in both
halves, with a higher total and skipped trades that lose money; otherwise keep 11.
Result (25 Oct 2026, 2023-10-26 to 2026-10-23, 81 trades without any skip): 11 kept. See results_calendar's docstring.
"""
import json
import time

import numpy as np
import pandas as pd

import todaycall as tc
from accuracy_study import _wf_tiers

# NIFTY 50 by approximate free-float weight, heaviest first (the first 11 are results_calendar.HEAVY)
NIFTY50 = ["HDFCBANK", "ICICIBANK", "RELIANCE", "INFY", "BHARTIARTL", "LT", "ITC", "TCS", "AXISBANK", "KOTAKBANK",
           "SBIN", "M&M", "BAJFINANCE", "HINDUNILVR", "SUNPHARMA", "HCLTECH", "NTPC", "MARUTI", "ULTRACEMCO", "TITAN",
           "ETERNAL", "TMPV", "POWERGRID", "TATASTEEL", "BEL", "TRENT", "ASIANPAINT", "BAJAJFINSV", "ADANIPORTS",
           "JSWSTEEL", "HINDALCO", "NESTLEIND", "ONGC", "GRASIM", "TECHM", "SBILIFE", "COALINDIA", "CIPLA", "BAJAJ-AUTO",
           "HDFCLIFE", "SHRIRAMFIN", "JIOFIN", "WIPRO", "TATACONSUM", "APOLLOHOSP", "EICHERMOT", "DRREDDY", "ADANIENT",
           "HEROMOTOCO", "INDUSINDBK"]
SIZES = (0, 5, 11, 20, 50)


def earnings(names):
    import yfinance as yf
    out = {}
    for n in names:
        for attempt in range(2):
            try:
                ed = yf.Ticker(f"{n}.NS").get_earnings_dates(limit=40)
                if ed is not None and len(ed):
                    out[n] = sorted({(pd.Timestamp(x).tz_localize(None) if pd.Timestamp(x).tzinfo else pd.Timestamp(x)).date()
                                     for x in ed.index})
                break
            except Exception as e:
                if attempt:
                    print(f"results {n}: {e!r}", flush=True)
                time.sleep(2)
        time.sleep(0.5)
    return out


def flags(index, cal, names):
    days = [d.date() for d in index]
    out = [False]
    for i in range(1, len(days)):
        out.append(any(days[i - 1] <= x < days[i] for n in names for x in cal.get(n, [])))
    return np.array(out)


def trade_stats(pnl):
    if not len(pnl):
        return {"trades": 0}
    k = len(pnl) // 2
    return {"trades": int(len(pnl)), "win": round(float((pnl > 0).mean()), 3), "avg_pct": round(float(pnl.mean()), 3),
            "total_pct": round(float(pnl.sum()), 2),
            "avg_halves": [round(float(pnl[:k].mean()), 3) if k else None, round(float(pnl[k:].mean()), 3)]}


def main():
    try:
        nd = tc.daily()
        nd = nd[nd.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
        series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
        df = tc.history(nd, series)
        day, gap = df["day"].values, df["gap"].values
        o2c = (1 + day) / (1 + gap) - 1
        p, tiers = _wf_tiers(df[tc.OPEN_FEATS].values, o2c)
        top = np.isin(tiers, tc.TRADE_TIERS)
        pnl = np.sign(p) * o2c * 100 - tc.TRADE_COST_PCT
        cal = earnings(NIFTY50)
        out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date()),
               "tickers_served": len(cal), "missing": [n for n in NIFTY50 if n not in cal]}
        # session flags over the whole daily history, then lined up with the study days
        for n in SIZES:
            f = pd.Series(flags(nd.index, cal, NIFTY50[:n]), index=nd.index).reindex(df.index).fillna(False).values.astype(bool)
            big = np.abs(day) > 0.01
            out[f"top{n}"] = {"flagged_sessions": int(f.sum()), "flagged_share": round(float(f.mean()), 3),
                              "big_move_rate": {"flagged": round(float(big[f].mean()), 3) if f.any() else None,
                                                "other": round(float(big[~f].mean()), 3)},
                              "kept": trade_stats(pnl[top & ~f]), "skipped": trade_stats(pnl[top & f])}
        base = out["top11"]["kept"]
        best = 11
        for n in (5, 20, 50):
            k, s = out[f"top{n}"]["kept"], out[f"top{n}"]["skipped"]
            if (k.get("trades") and all(a > b for a, b in zip(k["avg_halves"], base["avg_halves"]))
                    and k["total_pct"] > base["total_pct"] and s.get("trades") and s["avg_pct"] < 0
                    and k["total_pct"] > out[f"top{best}"]["kept"]["total_pct"]):
                best = n
        out["choice"] = best
        print("STUDY resultsize " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY resultsize failed: {e!r}", flush=True)
