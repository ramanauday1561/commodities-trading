"""Experiment mode "exits" (26 Oct 2026): stop-loss and take-profit rules for the from-open trade.

The live trade is held from the 09:15 open to the close. Tested on the same walk-forward from-open signal, with
NIFTY's 1-hour candles (high / low) for the path through the day:
  stop X%       exit when NIFTY moves X% against the trade (0.3, 0.5, 0.75, 1.0)
  target Y%     exit when it moves Y% in favour (0.5, 0.75, 1.0, 1.5)
  stop + target (0.5 / 1.0, 0.75 / 1.5, 0.5 / 0.75)
  wider         trading the top 50% most confident days instead of the top 20%, with a 0.5% or 0.75% stop (can a stop
                make the weaker days worth trading?)
Exits fill at the stop / target level; when one candle touches both, the stop is assumed first (the cautious reading).
A stop can be skipped over by a fast move, so stop results are a little optimistic. Costs ~0.03% per trade as before.
Rule fixed before the run: more per trade than the live hold-to-close by at least 0.02% in both halves, and a higher
total. With 13 variants tried, anything that only just passes is likely luck.
"""
import json

import numpy as np
import pandas as pd
import yfinance as yf

import todaycall as tc
from accuracy_study import _wf_tiers
from vix_study import stats

STOPS = (0.3, 0.5, 0.75, 1.0)
TARGETS = (0.5, 0.75, 1.0, 1.5)
BOTH = ((0.5, 1.0), (0.75, 1.5), (0.5, 0.75))


def candles():
    raw = yf.download(tc.NIFTY, period="730d", interval="1h", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["High", "Low"])
    idx = pd.to_datetime(raw.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    raw.index = idx.tz_convert("Asia/Kolkata")
    return {d: g[["High", "Low"]].values for d, g in raw.groupby(raw.index.date)}


def trade(side, opn, close, bars, stop=None, target=None):
    """Move earned (fraction) by a trade from the open: side +1 long / -1 short."""
    for hi, lo in bars:
        worst = (lo / opn - 1) * side if side > 0 else (hi / opn - 1) * side
        best = (hi / opn - 1) * side if side > 0 else (lo / opn - 1) * side
        if stop is not None and worst <= -stop / 100:
            return -stop / 100
        if target is not None and best >= target / 100:
            return target / 100
    return (close / opn - 1) * side


def main():
    try:
        nd = tc.daily()
        nd = nd[nd.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
        series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
        df = tc.history(nd, series)
        o2c = (1 + df["day"].values) / (1 + df["gap"].values) - 1
        p, tiers = _wf_tiers(df[tc.OPEN_FEATS].values, o2c)
        side = np.sign(p)
        top20 = np.isin(tiers, tc.TRADE_TIERS)
        top50 = np.isin(tiers, tc.TRADE_TIERS + ("lean",))
        bars = candles()
        days = [d.date() for d in df.index]
        opens = nd["open"].reindex(df.index).values
        closes = nd["close"].reindex(df.index).values
        have = np.array([d in bars and len(bars[d]) > 0 for d in days])

        def run(mask, stop=None, target=None):
            pnl = [trade(side[i], opens[i], closes[i], bars.get(days[i], []), stop, target) * 100 - tc.TRADE_COST_PCT
                   for i in np.where(mask)[0]]
            r = stats(np.array(pnl))
            if pnl:
                cum = np.cumsum(pnl)
                r["max_drawdown_pct"] = round(float(np.max(np.maximum.accumulate(cum) - cum)), 2)
                r["worst_pct"] = round(float(min(pnl)), 2)
            return r

        mask = top20 & have
        out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date()),
               "trade_days_with_candles": int(mask.sum()), "trade_days": int(top20.sum())}
        live = run(mask)
        out["hold_to_close"] = live
        variants = {}
        for s in STOPS:
            variants[f"stop_{s}"] = run(mask, stop=s)
        for t in TARGETS:
            variants[f"target_{t}"] = run(mask, target=t)
        for s, t in BOTH:
            variants[f"stop_{s}_target_{t}"] = run(mask, stop=s, target=t)
        out["top50_hold_to_close"] = run(top50 & have)
        for s in (0.5, 0.75):
            variants[f"top50_stop_{s}"] = run(top50 & have, stop=s)
        for k, v in variants.items():
            v["passes"] = (v.get("trades", 0) >= 20 and v["total_pct"] > live["total_pct"] and
                           all(a is not None and b is not None and a >= b + 0.02
                               for a, b in zip(v["avg_halves"], live["avg_halves"])))
        out.update(variants)
        out["passed"] = [k for k, v in variants.items() if v["passes"]]
        print("STUDY exits " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY exits failed: {e!r}", flush=True)
