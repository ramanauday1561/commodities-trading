"""Experiment mode "nextcandle" (29 Oct 2026): can the app predict the next 10-minute NIFTY candle well enough to buy a
CALL or PUT on it?

Asked by the user on 29 Oct 2026: "predict the next candle based on the app we have so that I can buy put or call".
Data: the stored 5-minute history (intraday_data.py: NIFTY, Bank NIFTY, India VIX from 2015), joined into the same
10-minute candles as the Live page (09:15, 09:25, ... 15:15). At the end of each candle, only what is known then:
  NIFTY's last three 10-minute moves and its last 30 minutes, the move since the open and since yesterday's close, the
  opening gap, the day's range so far and where the price sits in it, the time of day, Bank NIFTY's last 10 and 30
  minutes, India VIX's change since yesterday and over 30 minutes, yesterday's move.
Target: the next candle's move, close to close (enter at this candle's close, exit at the next one's).
Model: LightGBM, walk-forward by year (each year predicted by a model trained only on the years before it, from 2017),
  and two plain rules beside it: "the next candle follows the last one" and "it reverses".
Money: an at-the-money option moves about half as much as NIFTY; a round trip on one lot (65) costs about Rs 120
  (brokerage, STT, fees and the bid-ask spread), about 1.85 option points, so a trade earns 0.5 x NIFTY points - 1.85.
Rule fixed before the run: the model is usable for CALL / PUT only if its top-20% most confident trades win at least
55% of the time, earn after option costs in both halves of the test years and in at least 6 of the 10 test years.
Result (29 Oct 2026, 99,915 candles, 2,855 days, test years 2017-2026; HORIZON=3 and 6 run the same way): nothing passed.
  next 10 minutes (the average candle moves 10.9 NIFTY points): the model's top-20% calls were right 53.1% of the time
    (51.1% for all calls), but lost 1.12 option points a trade after costs (about -Rs73 a lot), and lost in all 10
    years. "Follow the last candle" was right 49.3%, "reverse it" 50.6%: both lost more.
  next 30 minutes (18.9 points on average): 53.3% right, -0.27 option points a trade, 4 of 10 years up.
  next 60 minutes (26.6 points): 53.1% right, -0.10 option points a trade (about -Rs6 a lot), 4 of 10 years up.
The model sees a little more than a coin flip, but a 10-minute candle is too small for an option trade to cover its
costs; longer horizons get close to break-even and no further. Not used for CALL / PUT.
"""
import json
import os

import numpy as np
import pandas as pd

import intraday_data

DELTA, COST_OPT_PTS = 0.5, 1.85
FEATS = ["r1", "r2", "r3", "r30", "since_open", "vs_prev", "gap", "range", "pos", "tod", "bank_r1", "bank_r30",
         "vix_day", "vix_r30", "prev_day"]


def tens(g):
    """5-minute candles -> 10-minute candles from 09:15 (the last, 15:25, is only 5 minutes and is dropped)."""
    g = g.copy()
    start = g.index.normalize() + pd.Timedelta(hours=9, minutes=15)
    k = ((g.index - start) / pd.Timedelta(minutes=10)).astype(int)
    out = g.groupby(k).agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"),
                           n=("Close", "size"))
    return out[out["n"] == 2]


def rows(nifty, bank, vix, h=1, live=False):
    """One row per finished 10-minute candle; live=True keeps today's last candles (their outcome is not known yet)."""
    ds = sorted(nifty)
    out = []
    for a, d in zip(ds, ds[1:]):
        g, pg = nifty[d], nifty[a]
        if len(g) < (2 if live else 70):
            continue
        t, pc = tens(g), float(pg["Close"].iloc[-1])
        prev_day = pc / float(nifty[ds[ds.index(a) - 1]]["Close"].iloc[-1]) - 1 if ds.index(a) else 0.0
        least = 2 if live else 60
        bt = tens(bank[d]) if d in bank and len(bank[d]) > least else None
        vt = tens(vix[d]) if d in vix and len(vix[d]) > least else None
        vpc = float(vix[a]["Close"].iloc[-1]) if a in vix and len(vix[a]) else np.nan
        c = t["Close"].values
        opn = float(t["Open"].iloc[0])
        for k in range(1, len(t) - (0 if live else h)):
            hi, lo = t["High"].values[:k + 1].max(), t["Low"].values[:k + 1].min()
            r = lambda i: c[i] / c[i - 1] - 1 if i >= 1 else c[0] / opn - 1
            row = {"d": d, "k": k, "price": c[k], "y": c[k + h] / c[k] - 1 if k + h < len(c) else np.nan,
                   "r1": r(k), "r2": r(k - 1), "r3": r(k - 2) if k >= 2 else 0.0,
                   "r30": c[k] / c[max(k - 3, 0)] - 1, "since_open": c[k] / opn - 1, "vs_prev": c[k] / pc - 1,
                   "gap": opn / pc - 1, "range": (hi - lo) / pc, "pos": (c[k] - lo) / (hi - lo) if hi > lo else 0.5,
                   "tod": k * 10, "prev_day": prev_day}
            if bt is not None and k in bt.index and k - 1 in bt.index:
                bc = bt["Close"]
                row["bank_r1"] = bc[k] / bc[k - 1] - 1
                row["bank_r30"] = bc[k] / bc[max(k - 3, bt.index[0])] - 1 if max(k - 3, bt.index[0]) in bt.index else 0.0
            if vt is not None and k in vt.index and np.isfinite(vpc):
                vc = vt["Close"]
                row["vix_day"] = vc[k] / vpc - 1
                row["vix_r30"] = vc[k] / vc[max(k - 3, vt.index[0])] - 1 if max(k - 3, vt.index[0]) in vt.index else 0.0
            out.append(row)
    df = pd.DataFrame(out)
    df[FEATS] = df[FEATS].fillna(0.0)
    df["year"] = pd.to_datetime(df["d"]).dt.year
    return df


def money(side, y, price):
    """Option points per trade: half the NIFTY move on the right side, minus the round-trip cost."""
    return DELTA * side * y * price - COST_OPT_PTS


def evaluate(df, pred, conf_cut):
    """Hit rate and option points per trade, all and top-20% by confidence (cut from the training predictions)."""
    side = np.sign(pred)
    hit = side == np.sign(df["y"].values)
    pts = money(side, df["y"].values, df["price"].values)
    top = np.abs(pred) >= conf_cut
    r = {"trades": int(len(df)), "hit": round(float(hit.mean()), 3), "pts": round(float(pts.mean()), 2),
         "top_trades": int(top.sum()), "top_hit": round(float(hit[top].mean()), 3) if top.any() else None,
         "top_pts": round(float(pts[top].mean()), 2) if top.any() else None}
    r["top_rs_per_lot"] = round(r["top_pts"] * 65) if r["top_pts"] is not None else None
    return r


def day_record(nifty, bank, vix, params=None):
    """Trading every lean with 1 lot of an at-the-money option, day by day (walk-forward by year from 2017): the
    record the Next 10 min page shows beside each day's score (30 Oct 2026: that day lost Rs8,868 on 36 leans and
    looked like a failure, but most days lose)."""
    import lightgbm as lgb
    df = rows(nifty, bank, vix, h=1)
    params = params or {"objective": "regression", "learning_rate": 0.03, "num_leaves": 15, "min_data_in_leaf": 400,
                        "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0,
                        "verbose": -1}
    days = []
    for y in sorted(df["year"].unique()):
        if y < 2017:
            continue
        tr, te = df[df["year"] < y], df[df["year"] == y]
        m = lgb.train(params, lgb.Dataset(tr[FEATS].values, tr["y"].clip(tr["y"].quantile(0.01), tr["y"].quantile(0.99)).values),
                      num_boost_round=300)
        t = te[["d", "y", "price"]].assign(rs=money(np.sign(m.predict(te[FEATS].values)), te["y"].values, te["price"].values) * 65)
        days.append(t.groupby("d")["rs"].sum())
    rs = pd.concat(days)
    return {"days": int(len(rs)), "from": str(rs.index.min()), "to": str(rs.index.max()),
            "profit_share": round(float((rs > 0).mean()), 3), "avg_rs": int(round(rs.mean())),
            "quantiles": {str(q): int(round(rs.quantile(q / 100))) for q in (1, 5, 10, 25, 50, 75, 90, 95, 99)}}


def main(h=None):
    import lightgbm as lgb
    h = h or int(os.environ.get("HORIZON", "1"))           # candles ahead: 1 = the next 10 minutes, 3 = 30, 6 = 60
    try:
        d = os.environ.get("INTRADAY_DIR", "intra")
        df = rows(*(intraday_data.load(d, k) for k in ("nifty", "banknifty", "vix")), h=h)
        out = {"horizon_min": 10 * h, "candles": len(df), "days": int(df["d"].nunique()), "from": str(df["d"].min()), "to": str(df["d"].max()),
               "avg_abs_move_pts": round(float((df["y"].abs() * df["price"]).mean()), 1)}
        params = {"objective": "regression", "learning_rate": 0.03, "num_leaves": 15, "min_data_in_leaf": 400,
                  "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1}
        years, res = sorted(df["year"].unique()), {}
        for y in years:
            if y < 2017:
                continue
            tr, te = df[df["year"] < y], df[df["year"] == y]
            ytr = tr["y"].clip(tr["y"].quantile(0.01), tr["y"].quantile(0.99))
            m = lgb.train(params, lgb.Dataset(tr[FEATS].values, ytr.values), num_boost_round=300)
            cut = np.quantile(np.abs(m.predict(tr[FEATS].values)), 0.8)
            res[str(y)] = {"model": evaluate(te, m.predict(te[FEATS].values), cut),
                           "follow": evaluate(te, te["r1"].values, np.quantile(np.abs(tr["r1"]), 0.8)),
                           "reverse": evaluate(te, -te["r1"].values, np.quantile(np.abs(tr["r1"]), 0.8))}
        out["by_year"] = res
        for name in ("model", "follow", "reverse"):
            tops = [(v[name]["top_hit"], v[name]["top_pts"], v[name]["top_trades"]) for v in res.values()]
            n = sum(t for _, _, t in tops)
            hit = sum(h * t for h, _, t in tops) / n
            pts = sum(p * t for _, p, t in tops) / n
            half = len(tops) // 2
            halves = [sum(p * t for _, p, t in part) / sum(t for _, _, t in part) for part in (tops[:half], tops[half:])]
            out[name] = {"top_trades": n, "top_hit": round(hit, 3), "top_pts": round(pts, 2), "top_rs_per_lot": round(pts * 65),
                         "halves_pts": [round(h, 2) for h in halves], "years_up": f"{sum(p > 0 for _, p, _ in tops)}/{len(tops)}",
                         "all_hit": round(float(np.mean([v[name]["hit"] for v in res.values()])), 3)}
            out[name]["passes"] = bool(hit >= 0.55 and all(h > 0 for h in halves) and sum(p > 0 for _, p, _ in tops) >= 6)
        print("STUDY nextcandle " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY nextcandle failed: {e!r}", flush=True)
