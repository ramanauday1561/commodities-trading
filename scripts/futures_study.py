"""Experiment mode "futures" (5 Nov 2026, asked by the user): the 09:15 signal traded in NIFTY futures, on Kite's real
futures prices.

Why: in options the signal lost after time decay and costs (option_study.py: the 11-year walk-forward lost 2.29 option
points a trade, losing since 2022). Futures have no time decay and cost much less: about 0.04% of NIFTY a round trip
(brokerage, 0.02% STT on the sale, exchange fees, stamp duty, a point of slippage each way). Until now the signal's
"from the open" numbers used NIFTY's index open and close; futures open at their own price (the index plus a premium
that shrinks to expiry) and that open can differ from the index's.
Data: Kite's continuous NIFTY futures, daily (futures_data.py); the signal's days from long_signal_study.py's 11-year
walk-forward (Dukascopy overnight inputs) and the live version's last 2 years (as option_study.py), top-20% days only,
standing aside after heavyweight results and US news, as live.
Trade: buy (signal up) or sell (down) at the futures' 09:15 open, close at the futures' close; with the live stop, out
at 0.5% against the open when the day's low (long) or high (short) reached it, plus 0.02% slippage. Rs for one lot
of 65 at that day's futures price.
Rule, fixed before the run: worth trading in futures only if the 11-year walk-forward's trades with the stop earn
after costs over all years, in both halves, since 2022, and in at least 2 of 3 years. Beside it, for information:
the same trades without the stop, the same days on the index (what the app has shown), and trading the signal's
direction every day.
"""
import json
import os

import numpy as np
import pandas as pd

import futures_data
import long_signal_study as ls
import overnight_data
import todaycall as tc

COST_PCT, STOP_PCT, SLIP_PCT, LOT = 0.04, 0.5, 0.02, 65
GIFT_ERA_ON = pd.Timestamp("2022-01-01").date()


def trade(side, o, h, lo, c, stop=True):
    """% of the futures price after costs for one day, entered at the open."""
    if stop:
        if side > 0 and lo <= o * (1 - STOP_PCT / 100):
            return -STOP_PCT - SLIP_PCT - COST_PCT
        if side < 0 and h >= o * (1 + STOP_PCT / 100):
            return -STOP_PCT - SLIP_PCT - COST_PCT
    return side * (c / o - 1) * 100 - COST_PCT


def summary(rows):
    """rows: [(date, pct, rs)] -> trades, won, averages, halves, years, since 2022."""
    if not rows:
        return {"trades": 0}
    rows = sorted(rows)
    pct = np.array([p for _, p, _ in rows])
    rs = np.array([r for _, _, r in rows])
    half = len(rows) // 2
    years = {}
    for d, p, _ in rows:
        years.setdefault(d.year, []).append(p)
    recent = [p for d, p, _ in rows if d >= GIFT_ERA_ON]
    return {"trades": len(rows), "won": round(float((pct > 0).mean()), 3), "avg_pct": round(float(pct.mean()), 3),
            "rs_per_lot": int(round(rs.mean())), "total_rs": int(round(rs.sum())),
            "halves_pct": [round(float(pct[:half].mean()), 3), round(float(pct[half:].mean()), 3)] if half else None,
            "since_2022_pct": round(float(np.mean(recent)), 3) if recent else None,
            "years_up": f"{sum(np.sum(v) > 0 for v in years.values())}/{len(years)}",
            "by_year_pct": {str(y): round(float(np.mean(v)), 3) for y, v in sorted(years.items())}}


def evaluate(days, fut, nd, stop=True, index=False):
    out = []
    for d, side in days.items():
        ts = pd.Timestamp(d)
        src = nd if index else fut
        if ts not in src.index:
            continue
        r = src.loc[ts]
        o, h, lo, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        p = trade(side, o, h, lo, c, stop)
        out.append((d, p, p / 100 * o * LOT))
    return summary(out)


def main():
    try:
        fut = futures_data.load_daily(os.environ.get("FUTURES_DIR", "fut"))
        if fut.empty:
            raise RuntimeError("no futures data: run mode kitefutures first")
        nd = ls.nifty_daily()
        od = os.environ.get("OVERNIGHT_DIR", "od")
        series = {k: overnight_data.load(od, k) for k in ("es", "nq", "nikkei", "hangseng")}
        series.update({k: ls.us_close_series(t) for k, t in (("hdb", "HDB"), ("ibn", "IBN"), ("infy", "INFY"))})
        df = tc.history(nd, series)
        end = min(series[k].index[-1] for k in ("es", "nq", "nikkei", "hangseng")).tz_convert(None).normalize()
        df = df[(df.index >= ls.FIRST) & (df.index <= end)]
        p, t = ls.wf(df[ls.LONG].values, ((1 + df["day"]) / (1 + df["gap"]) - 1).values)
        skip = ls.skip_days(df, nd)
        long_days = {d: (1 if p[j] > 0 else -1) for j, d in enumerate(df.index.date) if t[j] in tc.TRADE_TIERS and not skip[j]}
        every_day = {d: (1 if p[j] > 0 else -1) for j, d in enumerate(df.index.date) if np.isfinite(p[j]) and p[j] != 0}
        yd = tc.history(nd, {k: tc.hourly(s) for k, s in {**tc.OVERNIGHT, **tc.INDIA}.items()})
        p2, t2 = ls.wf(yd[tc.OPEN_FEATS].values, ((1 + yd["day"]) / (1 + yd["gap"]) - 1).values)
        skip2 = ls.skip_days(yd, nd)
        live_days = {d: (1 if p2[j] > 0 else -1) for j, d in enumerate(yd.index.date) if t2[j] in tc.TRADE_TIERS and not skip2[j]}
        out = {"futures_days": int(len(fut)), "from": str(fut.index.min().date()), "to": str(fut.index.max().date()),
               "costs": f"{COST_PCT}% a round trip, stop {STOP_PCT}% + {SLIP_PCT}% slippage, lot {LOT}"}
        for name, days in (("11-year walk-forward", long_days), ("live version, last 2 years", live_days)):
            out[name] = {"signal_days": len(days),
                         "futures, with the stop": evaluate(days, fut, nd, stop=True),
                         "futures, no stop": evaluate(days, fut, nd, stop=False),
                         "index, with the stop (as the app shows)": evaluate(days, fut, nd, stop=True, index=True)}
        out["the lean every day, futures, with the stop"] = evaluate(every_day, fut, nd, stop=True)
        m = out["11-year walk-forward"]["futures, with the stop"]
        out["passes"] = bool(m.get("trades", 0) >= 30 and m["avg_pct"] > 0 and all(h > 0 for h in m["halves_pct"])
                             and (m["since_2022_pct"] or 0) > 0
                             and int(m["years_up"].split("/")[0]) * 3 >= 2 * int(m["years_up"].split("/")[1]))
        both = fut.index.intersection(pd.DatetimeIndex([pd.Timestamp(x) for x in nd.index]))
        gap = (fut.loc[both, "open"] / nd.loc[both, "open"] - 1) * 100
        out["futures open vs index open, %"] = {"mean": round(float(gap.mean()), 3), "p10": round(float(gap.quantile(0.1)), 3),
                                                 "p90": round(float(gap.quantile(0.9)), 3)}
        print("STUDY futures " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY futures failed: {e!r}", flush=True)
