"""Experiment mode "leanfilters" (9 Nov 2026, asked by the user): do any of three filters make the Next 10 leans pay,
and how far off is the app's "the option moves half as much as NIFTY" pricing from Kite's real option prices?

Why: on Kite's real option prices (paper_accounts.py) every lean made +Rs2,517 in 4 days (4-9 Nov), the * leans
+Rs5,213, leans on candles expected to move at least 1.2x the usual size +Rs18,669 (almost all on 6 Nov), and leans
with the day's move -Rs6,271 on the choppy 9 Nov after +Rs16,521 on the trending 6 Nov. Four days prove nothing; the
9-year 5-minute history decides.

Part 2, the pricing (calibrate): every pair of consecutive option snapshots ~10 minutes apart in the options-live
branch (options_live.py, Kite quotes since 4 Nov 2026): the at-the-money CALL and PUT of the next expiry at the first
snapshot, their price change against NIFTY's change. Fitted together: option change = a + b x (NIFTY change on the
option's side), so b is the real "share of NIFTY's move" (the app assumes 0.5) and a the time decay per 10 minutes
(the app assumes 0). Costs (1.85 option points a round trip, about Rs120 a lot) come on top of both.

Part 1, the filters (main): the leans exactly as the 9-year test made them (nextcandle_study.day_record: LightGBM,
walk-forward by year from 2017, each year from a model trained only on the years before), and the size forecast as
movesize_study / the live page (the expected size against the usual size at that candle, from the same training
years). Three filters, fixed before the run:
  F1 star:   the lean's confidence in its training years' top 20% (the page's *).
  F2 big:    expected size of the move at least 1.2x the usual size at that time of day.
  F3 trend:  at least 30 minutes into the day (3 candles), the day trending, and the lean on the day's side: NIFTY's
             move since the open is at least 40% of the total distance it has travelled (the sum of its 10-minute
             moves, the opening candle's included), and the lean agrees with the move since the open.
Each priced twice: the app's way (0.5 x NIFTY's move - 1.85) and Part 2's (b x NIFTY's move + a - 1.85).
Rule, fixed before the run (stricter than one test's, as three filters are tried): a filter is worth a paper account
on the page only if, priced Part 2's way, its trades earn after costs on average over 2017-2026, in both halves of
those years, since 2022, and in at least 7 of the 10 years, with at least 300 trades. With fewer than 100 saved quote
pairs Part 2 is not trusted, and the app's pricing decides.
Result (run locally 9 Nov 2026 on the intraday-data and options-live branches; 85,014 test candles, 2017-01-02 to
2026-11-09; Rs a lot after costs):
  Part 2: 256 quote pairs over 4 days (4-9 Nov 2026): an at-the-money option moved 0.569x NIFTY's move on its side
    (by day 0.51-0.66; the app assumed 0.5), and -0.08 option points per 10 minutes besides (by day -0.75 to +0.46;
    the app assumed 0); the fit explains 92.5% of the moves (left over: 4.3 points a pair). The app's pricing was
    about right, slightly pessimistic on the move and slightly kind on time decay; real pricing changes each result
    below by 0.05 option points at most.
  Part 1, real pricing (the app's in brackets):
    every lean   85,014 trades, right 51.1%, -1.64 pts a trade, -Rs106 (-Rs103), 0 of 10 years up
    F1 star      16,396 trades, right 53.0%, -1.11 pts, -Rs72 (-Rs74), halves -1.23 / -1.03, since 2022 -0.99, 0 of 10
    F2 big       17,538 trades, right 51.3%, -1.47 pts, -Rs95 (-Rs94), 0 of 10
    F3 trend     13,168 trades, right 51.6%, -1.53 pts, -Rs99 (-Rs97), 0 of 10
  All three FAIL, every year. The * leans are the least bad (best years 2022 -0.60 and 2024 -0.62 pts), but a lean is
  right 53% at best and a round trip costs 1.85 option points: the right side has to win by more than costs, and it
  does not. The +Rs5,213 of the * leans over 4-9 Nov 2026 (31 trades) is luck within what four days can show; nothing
  changes in the app, and the paper accounts keep counting.
"""
import csv
import glob
import json
import os
from datetime import date

import numpy as np
import pandas as pd

import intraday_data
import movesize_study as ms
import nextcandle_study as ns

COST, STEP, LOT = 1.85, 50, 65
PARAMS = {"objective": "regression", "learning_rate": 0.03, "num_leaves": 15, "min_data_in_leaf": 400,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1}
ER_MIN, BIG, MIN_K = 0.4, 1.2, 2


def _mins(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


# ---------------------------------------------------------------- Part 2: the pricing, from Kite's saved quotes
def pairs(optlive_dir):
    """[(day, t0, side +1 CALL / -1 PUT, NIFTY change, option change)] for the at-the-money options of the next expiry."""
    out = []
    for path in sorted(glob.glob(os.path.join(optlive_dir, "snapshots", "*.csv"))):
        day = os.path.basename(path)[:-4]
        runs, spot = {}, {}
        with open(path) as f:
            for r in csv.DictReader(f):
                try:
                    runs.setdefault(r["at"], {})[(r["expiry"], float(r["strike"]), r["type"])] = float(r["ltp"])
                    spot[r["at"]] = float(r["spot"])
                except (KeyError, TypeError, ValueError):
                    continue
        times = sorted(runs, key=_mins)
        for t0, t1 in zip(times, times[1:]):
            if not 8 <= _mins(t1) - _mins(t0) <= 14 or t0 not in spot or t1 not in spot:
                continue
            exps = sorted({k[0] for k in runs[t0] if k[0] > day})
            if not exps:
                continue
            k = float(round(spot[t0] / STEP) * STEP)
            for typ, side in (("CE", 1), ("PE", -1)):
                key = (exps[0], k, typ)
                if key in runs[t0] and key in runs[t1]:
                    out.append((day, t0, side, spot[t1] - spot[t0], runs[t1][key] - runs[t0][key], exps[0]))
    return out


def calibrate(optlive_dir):
    """b (the option's share of NIFTY's move on its side) and a (option points per 10 minutes besides that)."""
    p = pairs(optlive_dir)
    if not p:
        return {"pairs": 0}
    x = np.array([s * dn for _, _, s, dn, _, _ in p])
    y = np.array([do for _, _, _, _, do, _ in p])
    b, a = np.polyfit(x, y, 1)
    resid = y - (a + b * x)
    by_day = {}
    for d in sorted({q[0] for q in p}):
        m = np.array([q[0] == d for q in p])
        if m.sum() >= 10:
            bd, ad = np.polyfit(x[m], y[m], 1)
            by_day[d] = {"pairs": int(m.sum()), "b": round(float(bd), 3), "a": round(float(ad), 2),
                         "days_to_expiry": (date.fromisoformat(p[int(np.argmax(m))][5]) - date.fromisoformat(d)).days}
    return {"pairs": len(p), "days": len(by_day), "b": round(float(b), 3), "a": round(float(a), 2),
            "r2": round(float(1 - resid.var() / y.var()), 3), "resid_sd": round(float(resid.std()), 2), "by_day": by_day}


# ---------------------------------------------------------------- Part 1: the filters over 9 years
def trend_inputs(df):
    """er: |move since the open| / the distance travelled since the open (the opening candle's move included), in log
    moves, so a day that only goes one way scores exactly 1."""
    df = df.copy()
    lr = np.log1p(df["r1"])
    first = np.log1p(df["since_open"]) - lr                          # log(c0 / open) on the day's first row
    first = first.where(df["k"] == df.groupby("d")["k"].transform("min"))
    df["path"] = lr.abs().groupby(df["d"]).cumsum() + first.groupby(df["d"]).transform("first").abs()
    df["er"] = (np.log1p(df["since_open"]).abs() / df["path"]).where(df["path"] > 0, 0.0)
    return df


def walk_forward(df, first_year=2017):
    """Test rows with: pred, star, size_pts, typical_pts (each year from models trained on the years before)."""
    import lightgbm as lgb
    df = ms.add_size(df)
    df = trend_inputs(df)
    out = []
    for y in sorted(df["year"].unique()):
        if y < first_year:
            continue
        tr, te = df[(df["year"] < y) & df["y"].notna()], df[(df["year"] == y) & df["y"].notna()].copy()
        yt = tr["y"].clip(tr["y"].quantile(0.01), tr["y"].quantile(0.99))
        m = lgb.train(PARAMS, lgb.Dataset(tr[ns.FEATS].values, yt.values), num_boost_round=300)
        cut = np.quantile(np.abs(m.predict(tr[ns.FEATS].values)), 0.8)
        rel = tr["size"] / tr["price"]
        s = lgb.train(PARAMS, lgb.Dataset(tr[ms.SIZE_FEATS].values, rel.clip(rel.quantile(0.01), rel.quantile(0.99)).values),
                      num_boost_round=300)
        typical = rel.groupby(tr["k"]).mean()
        te["pred"] = m.predict(te[ns.FEATS].values)
        te["star"] = np.abs(te["pred"]) >= cut
        te["size_pts"] = s.predict(te[ms.SIZE_FEATS].values) * te["price"]
        te["typical_pts"] = te["k"].map(typical) * te["price"]
        out.append(te)
    return pd.concat(out)


def filters(t):
    side = np.sign(t["pred"])
    return {"every lean": np.ones(len(t), bool),
            "F1 star": t["star"].values,
            "F2 big (size >= 1.2x usual)": (t["size_pts"] >= BIG * t["typical_pts"]).values,
            "F3 trend (with the day, er >= 0.4)": ((t["k"] >= MIN_K) & (t["er"] >= ER_MIN) & (side == np.sign(t["since_open"]))).values}


def summary(t, mask, b, a):
    s = t[mask]
    side = np.sign(s["pred"].values)
    move = side * s["y"].values * s["price"].values                     # NIFTY points the right way
    pts = b * move + a - COST
    yrs = pd.Series(pts, index=s["year"].values).groupby(level=0).mean()
    half = len(yrs) // 2
    rec = pts[s["year"].values >= 2022]
    return {"trades": int(len(s)), "right": round(float((move > 0).mean()), 3) if len(s) else None,
            "pts": round(float(pts.mean()), 2) if len(s) else None, "rs_per_lot": int(round(pts.mean() * LOT)) if len(s) else None,
            "halves": [round(float(yrs.iloc[:half].mean()), 2), round(float(yrs.iloc[half:].mean()), 2)] if half else None,
            "since_2022": round(float(rec.mean()), 2) if len(rec) else None,
            "years_up": f"{int((yrs > 0).sum())}/{len(yrs)}", "by_year": {str(k): round(float(v), 2) for k, v in yrs.items()}}


def passes(r):
    up, n = (int(x) for x in r["years_up"].split("/"))
    return bool(r["trades"] >= 300 and r["pts"] > 0 and all(h > 0 for h in r["halves"]) and (r["since_2022"] or 0) > 0 and up >= 7)


def main():
    try:
        cal = calibrate(os.environ.get("OPTLIVE_DIR", "optlive"))
        trusted = cal.get("pairs", 0) >= 100
        b, a = (cal["b"], cal["a"]) if trusted else (0.5, 0.0)
        d = os.environ.get("INTRADAY_DIR", "intra")
        df = ns.rows(*(intraday_data.load(d, k) for k in ("nifty", "banknifty", "vix")), h=1)
        t = walk_forward(df)
        out = {"pricing": cal, "pricing_used": {"b": b, "a": a, "trusted": trusted}, "candles": int(len(t)),
               "from": str(t["d"].min()), "to": str(t["d"].max()), "filters": {}}
        for name, mask in filters(t).items():
            app, real = summary(t, mask, 0.5, 0.0), summary(t, mask, b, a)
            out["filters"][name] = {"app pricing": app, "real pricing": real, "passes": passes(real)}
        print("STUDY leanfilters " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY leanfilters failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
