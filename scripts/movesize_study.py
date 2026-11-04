"""Experiment mode "movesize" (5 Nov 2026, asked by the user): how big will the next 10-minute NIFTY move be?

Why: the Next 10 min page's direction leans are nearly a coin flip (nextcandle_study: right 53% at best, losing after
option costs in every year), but the SIZE of the next move should be more predictable (busy and quiet spells cluster).
For an option buyer the size matters: an at-the-money option needs NIFTY to move about 7.4 points the right way just
to cover a round trip's costs (1.85 option points at a delta of 0.5).
Data: the stored 5-minute history (intraday_data.py; Kite's candles since 19 May 2026), joined into the Live page's
10-minute candles; the same inputs as nextcandle_study.rows() plus the size of the last three moves and the average
size of today's moves so far. Target: the size of the next candle's move, close to close, in NIFTY points.
Model: LightGBM, walk-forward by year from 2017 (each year predicted by a model trained only on the years before).
Baselines: (1) the average size at that time of day in the training years; (2) the average size of the last three
candles.
Rules, fixed before the run:
  A. The size forecast goes on the page only if its average error (MAE, points) beats both baselines overall by at
     least 3% and in at least 8 of the 10 test years, and the candles it ranks in its top 10% really move at least 1.5
     times as much as its bottom 10% in every test year.
  B. The direction leans become usable on big-move candles only if, on the candles the size model ranks in its top
     20%, the leans win at least 55%, earn after option costs in both halves and in at least 6 of the 10 years
     (nextcandle_study's rule).
Result (run 41815386034, 4 Nov 2026; 101,877 candles, 2,911 days, test years 2017-2026; the average move 11.0 points):
  A passes. Average error 7.80 points against 8.76 (time of day) and 8.71 (last three candles): 10.4% better than the
    better baseline, and better than both in all 10 years. Its top 10% moved 2.7-4.3 times its bottom 10% every year
    (2026: 8.8 against 28.6 points). Shown on the Next 10 min page beside the lean (nextcandle.py).
  B fails. On the candles it ranks in its top 20%, the leans were right 51.2% and lost 1.33 option points (-Rs87 a lot)
    a trade after costs, in every year, though 50-80% of those candles moved more than the 7.4 points that cover costs:
    a big move does not help when its direction is a coin flip. The leans stay information.
"""
import json
import os

import numpy as np
import pandas as pd

import intraday_data
import nextcandle_study as ns

SIZE_FEATS = ns.FEATS + ["a1", "a2", "a3", "day_abs"]
PARAMS = {"objective": "regression", "learning_rate": 0.03, "num_leaves": 15, "min_data_in_leaf": 400,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1}


def add_size(df):
    """The size inputs: the last three moves' sizes and the average size of today's moves so far."""
    df = df.copy()
    df["a1"], df["a2"], df["a3"] = df["r1"].abs(), df["r2"].abs(), df["r3"].abs()
    df["day_abs"] = df.groupby("d")["a1"].transform(lambda s: s.expanding().mean())
    df["size"] = df["y"].abs() * df["price"]                       # the next move, NIFTY points
    return df


def fit(tr, target, feats, rounds=300):
    import lightgbm as lgb
    y = tr[target].clip(tr[target].quantile(0.01), tr[target].quantile(0.99))
    return lgb.train(PARAMS, lgb.Dataset(tr[feats].values, y.values), num_boost_round=rounds)


def size_year(tr, te):
    """One test year: the model's and the baselines' errors (points), the deciles, the leans on big-move candles."""
    m = fit(tr.assign(rel=tr["size"] / tr["price"]), "rel", SIZE_FEATS)
    pred = m.predict(te[SIZE_FEATS].values) * te["price"].values
    tod = tr.assign(rel=tr["size"] / tr["price"]).groupby("k")["rel"].mean()
    b1 = te["k"].map(tod).fillna(tr["size"].mean() / tr["price"].mean()).values * te["price"].values
    b2 = (te[["a1", "a2", "a3"]].mean(axis=1) * te["price"]).values
    act = te["size"].values
    dec = pd.qcut(pd.Series(pred).rank(method="first"), 10, labels=False).values
    top_bottom = float(act[dec == 9].mean() / act[dec == 0].mean())
    out = {"candles": int(len(te)), "mae_model": round(float(np.abs(pred - act).mean()), 2),
           "mae_time_of_day": round(float(np.abs(b1 - act).mean()), 2), "mae_last3": round(float(np.abs(b2 - act).mean()), 2),
           "corr": round(float(pd.Series(pred).corr(pd.Series(act), method="spearman")), 3),
           "top10_vs_bottom10": round(top_bottom, 2), "avg_size": round(float(act.mean()), 1),
           "deciles_pts": [round(float(act[dec == k].mean()), 1) for k in range(10)]}
    # B: the direction leans (nextcandle's model) on the candles the size model ranks in its top 20%
    d = fit(tr, "y", ns.FEATS)
    side = np.sign(d.predict(te[ns.FEATS].values))
    cut = np.quantile(m.predict(tr[SIZE_FEATS].values), 0.8)
    big = m.predict(te[SIZE_FEATS].values) >= cut
    pts = ns.money(side, te["y"].values, te["price"].values)
    out["leans_big"] = {"trades": int(big.sum()), "hit": round(float((side == np.sign(te["y"].values))[big].mean()), 3),
                        "pts": round(float(pts[big].mean()), 2), "covers_cost_share": round(float((act[big] > 7.4).mean()), 3)}
    return out


def size_only(tr, te):
    """The size forecast's errors on te from a model fitted on tr, beside the two baselines (points), and per day."""
    m = fit(tr.assign(rel=tr["size"] / tr["price"]), "rel", SIZE_FEATS)
    pred = m.predict(te[SIZE_FEATS].values) * te["price"].values
    tod = tr.assign(rel=tr["size"] / tr["price"]).groupby("k")["rel"].mean()
    b1 = te["k"].map(tod).fillna(tr["size"].mean() / tr["price"].mean()).values * te["price"].values
    b2 = (te[["a1", "a2", "a3"]].mean(axis=1) * te["price"]).values
    act = te["size"].values
    days = pd.DataFrame({"d": te["d"].values, "m": np.abs(pred - act), "b": np.abs(b1 - act)}).groupby("d").mean()
    q = pd.Series(pred).rank(pct=True).values
    return {"candles": int(len(te)), "days": int(te["d"].nunique()), "mae_model": round(float(np.abs(pred - act).mean()), 2),
            "mae_time_of_day": round(float(np.abs(b1 - act).mean()), 2), "mae_last3": round(float(np.abs(b2 - act).mean()), 2),
            "corr": round(float(pd.Series(pred).corr(pd.Series(act), method="spearman")), 3),
            "top20_pts": round(float(act[q > 0.8].mean()), 1), "bottom20_pts": round(float(act[q <= 0.2].mean()), 1),
            "days_model_better": int((days["m"] < days["b"]).sum())}


def kite_era(df, since="2026-05-19"):
    """5 Nov 2026: the size forecast on the days with Kite's own candles (intraday_data repair, from 19 May 2026),
    each month predicted by a model fitted on everything before that month."""
    df = df.copy()
    df["month"] = pd.to_datetime(df["d"]).dt.strftime("%Y-%m")
    s = pd.Timestamp(since).date()
    res = {}
    for m in sorted(df[df["d"] >= s]["month"].unique()):
        res[m] = size_only(df[df["month"] < m], df[(df["month"] == m) & (df["d"] >= s)])
    n = sum(v["candles"] for v in res.values())
    w = lambda k: round(sum(v[k] * v["candles"] for v in res.values()) / n, 2)
    days = sum(v["days"] for v in res.values())
    better = sum(v["days_model_better"] for v in res.values())
    return {"since": since, "by_month": res, "candles": n, "days": days, "mae_model": w("mae_model"),
            "mae_time_of_day": w("mae_time_of_day"), "mae_last3": w("mae_last3"),
            "better_than_usual_pct": round((1 - w("mae_model") / w("mae_time_of_day")) * 100, 1),
            "days_model_better": f"{better} of {days}", "months_better": f"{sum(v['mae_model'] < v['mae_time_of_day'] for v in res.values())} of {len(res)}"}


def main():
    try:
        d = os.environ.get("INTRADAY_DIR", "intra")
        df = add_size(ns.rows(*(intraday_data.load(d, k) for k in ("nifty", "banknifty", "vix")), h=1)).dropna(subset=["y"])
        out = {"candles": int(len(df)), "days": int(df["d"].nunique()), "from": str(df["d"].min()), "to": str(df["d"].max()),
               "avg_size_pts": round(float(df["size"].mean()), 1)}
        res = {}
        for y in ([] if os.environ.get("MOVESIZE_KITE_ONLY") else sorted(df["year"].unique())):
            if y < 2017:
                continue
            res[str(y)] = size_year(df[df["year"] < y], df[df["year"] == y])
        if os.environ.get("MOVESIZE_KITE_ONLY"):         # experiment mode movesizekite: only the Kite-era grade
            out["kite_era"] = kite_era(df)
            print("STUDY movesize " + json.dumps(out), flush=True)
            return out
        out["by_year"] = res
        n = sum(v["candles"] for v in res.values())
        w = lambda k: sum(v[k] * v["candles"] for v in res.values()) / n
        mm, m1, m2 = w("mae_model"), w("mae_time_of_day"), w("mae_last3")
        beat = sum(v["mae_model"] < min(v["mae_time_of_day"], v["mae_last3"]) for v in res.values())
        out["A_size"] = {"mae_model": round(mm, 2), "mae_time_of_day": round(m1, 2), "mae_last3": round(m2, 2),
                         "better_than_best_baseline_pct": round((1 - mm / min(m1, m2)) * 100, 1),
                         "years_better": f"{beat}/{len(res)}",
                         "top10_vs_bottom10_min": min(v["top10_vs_bottom10"] for v in res.values())}
        out["A_size"]["passes"] = bool(mm <= 0.97 * min(m1, m2) and beat >= 8 and out["A_size"]["top10_vs_bottom10_min"] >= 1.5)
        lb = [v["leans_big"] for v in res.values()]
        t = sum(x["trades"] for x in lb)
        hit = sum(x["hit"] * x["trades"] for x in lb) / t
        pts = sum(x["pts"] * x["trades"] for x in lb) / t
        half = len(lb) // 2
        halves = [sum(x["pts"] * x["trades"] for x in part) / sum(x["trades"] for x in part)
                  for part in (lb[:half], lb[half:]) if part]
        out["B_leans_on_big_moves"] = {"trades": t, "hit": round(hit, 3), "pts": round(pts, 2), "rs_per_lot": round(pts * 65),
                                       "halves_pts": [round(h, 2) for h in halves], "years_up": f"{sum(x['pts'] > 0 for x in lb)}/{len(lb)}"}
        out["B_leans_on_big_moves"]["passes"] = bool(hit >= 0.55 and all(h > 0 for h in halves) and sum(x["pts"] > 0 for x in lb) >= 6)
        print("STUDY movesize " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY movesize failed: {e!r}", flush=True)


def kite_main():
    os.environ["MOVESIZE_KITE_ONLY"] = "1"
    return main()
