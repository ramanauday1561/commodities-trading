"""Experiment mode "hourly" (21 Oct 2026): can NIFTY's 1-hour candles forecast the next hour, or the rest of the day?

Before building hourly forecasts (2-3 days of work and hourly runs), test whether they would beat "no change".
Hourly bars: ~2 years from Yahoo. At every hourly bar end in the session (10:15 ... 15:15 IST) two targets:
  next_hour     close of the next bar vs now
  rest_of_day   the day's close vs now
Inputs known at that moment: last bar's move, last two bars, move since the open, move since yesterday's close (the gap
included), where the price sits in today's range, the opening gap, yesterday's move, hour of day.
Models, walk-forward by day (each day's model trained only on earlier days, from day 60): ridge (like the live NIFTY
calls) and LightGBM (refit every 20 days); rules: momentum (follow the last bar) and reversal (fade it).
Scored on direction (vs the share of up moves) and on what a trade earns after ~0.03% costs, on all snapshots and on
the 20% most confident ones (cut-off from earlier days), in each half of the test period and by hour.
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd

import todaycall as tc
from open_study import hourly_ohlc

COST = tc.TRADE_COST_PCT
FEATS = ["r1", "r2", "since_open", "since_prev", "pos", "gap", "prev_day", "hour"]
MIN_DAYS = 60


def snapshots():
    nd = tc.daily()
    bars = hourly_ohlc(tc.NIFTY)                                  # indexed by bar END (UTC)
    bars["day"] = bars.index.normalize()
    prev_close = nd["close"].shift(1)
    rows = []
    for day, g in bars.groupby("day"):
        d = pd.Timestamp(day.date())
        if d not in nd.index or pd.isna(prev_close.get(d)) or len(g) < 4:
            continue
        pc, opn, close = float(prev_close.loc[d]), float(nd["open"].loc[d]), float(nd["close"].loc[d])
        prev_day = pc / float(nd["close"].shift(2).loc[d]) - 1 if not pd.isna(nd["close"].shift(2).loc[d]) else 0.0
        c = g["close"].values
        hi, lo = np.maximum.accumulate(g["high"].values), np.minimum.accumulate(g["low"].values)
        for i in range(len(g) - 1):                               # the last bar has no "next hour"
            r1 = c[i] / (c[i - 1] if i else opn) - 1
            r2 = c[i] / (c[i - 2] if i >= 2 else opn) - 1
            rng = max(hi[i], opn) - min(lo[i], opn)
            rows.append({"d": d, "hour": i, "r1": r1, "r2": r2, "since_open": c[i] / opn - 1, "since_prev": c[i] / pc - 1,
                         "pos": (c[i] - min(lo[i], opn)) / rng - 0.5 if rng > 0 else 0.0, "gap": opn / pc - 1,
                         "prev_day": prev_day, "next_hour": c[i + 1] / c[i] - 1, "rest_of_day": close / c[i] - 1})
    return pd.DataFrame(rows)


def walk_forward(df, target, kind):
    days = df["d"].unique()
    pred = np.full(len(df), np.nan)
    model = None
    for k, day in enumerate(days):
        if k < MIN_DAYS:
            continue
        tr, te = (df["d"] < day).values, (df["d"] == day).values
        X, y = df.loc[tr, FEATS].values, df.loc[tr, target].values
        if kind == "ridge":
            pred[te] = [tc.ridge_predict(m, x) for m in [tc.ridge_fit(X, y)] for x in df.loc[te, FEATS].values]
        else:
            if model is None or k % 20 == 0:
                lo, hi = np.percentile(y, [1, 99])
                model = lgb.train(dict(objective="regression", learning_rate=0.03, num_leaves=8, min_data_in_leaf=80,
                                       feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0,
                                       verbose=-1, seed=0, deterministic=True, force_row_wise=True, num_threads=2),
                                  lgb.Dataset(X, np.clip(y, lo, hi)), num_boost_round=150)
            pred[te] = model.predict(df.loc[te, FEATS].values)
    return pred


def score(df, pred, target):
    ok = ~np.isnan(pred) & (pred != 0)
    y, p = df[target].values, pred
    out = {}
    conf, top = np.abs(p), np.zeros(len(p), bool)
    seen = []
    for d, idx in df[ok].groupby("d").groups.items():           # cut-off from earlier days only
        ii = np.array(list(idx))
        if len(seen) >= 200:
            top[ii] = conf[ii] >= np.quantile(seen, 0.8)
        seen.extend(conf[ii])
    for name, m in (("all", ok), ("top20", ok & top)):
        if not m.any():
            continue
        hit = np.sign(p[m]) == np.sign(y[m])
        pnl = np.sign(p[m]) * y[m] * 100 - COST
        h = len(pnl) // 2
        out[name] = {"n": int(m.sum()), "hit": round(float(hit.mean()), 3), "up_rate": round(float((y[m] > 0).mean()), 3),
                     "avg_trade_pct": round(float(pnl.mean()), 3), "first_half_avg": round(float(pnl[:h].mean()), 3),
                     "second_half_avg": round(float(pnl[h:].mean()), 3),
                     "first_half_hit": round(float(hit[:h].mean()), 3), "second_half_hit": round(float(hit[h:].mean()), 3)}
    out["by_hour_hit"] = {int(hr): round(float((np.sign(p[ok & (df["hour"].values == hr)]) ==
                                                np.sign(y[ok & (df["hour"].values == hr)])).mean()), 3)
                          for hr in sorted(df["hour"].unique()) if (ok & (df["hour"].values == hr)).any()}
    return out


def main():
    try:
        df = snapshots()
        days = df["d"].unique()
        test = df["d"] >= days[MIN_DAYS]
        out = {"days": len(days), "from": str(days[0].date()), "to": str(days[-1].date()), "snapshots": int(len(df)),
               "test_snapshots": int(test.sum()), "cost_pct": COST}
        for target in ("next_hour", "rest_of_day"):
            res = {"avg_abs_move_pct": round(float(df.loc[test, target].abs().mean() * 100), 3)}
            res["ridge"] = score(df, walk_forward(df, target, "ridge"), target)
            res["lightgbm"] = score(df, walk_forward(df, target, "lgb"), target)
            r1 = np.where(test, df["r1"].values, np.nan)
            res["momentum"] = score(df, r1, target)
            res["reversal"] = score(df, -r1, target)
            out[target] = res
        print("STUDY hourly " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY hourly failed: {e!r}", flush=True)
