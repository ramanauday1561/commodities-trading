"""Experiment mode "minute" (30 Oct 2026): do 1-minute details help predict NIFTY 30 or 60 minutes ahead?

Asked after 30 Oct 2026, when trading every 10-minute lean lost Rs8,868. Shorter candles cannot work: a round trip
costs about Rs120 a lot whatever the length, so on 5-minute candles the leans would have to be right 72% of the time
(1-minute: ~98%), against 65% on 10-minute, 59% on 30-minute and 56% on 60-minute ones. The 30- and 60-minute
versions of the next-candle model came closest (nextcandle_study.py: 53% right, about break-even). This tests whether
1-minute data, used as inputs, lifts those two over the line.
Data: Kaggle "debashis74017/nifty-50-minute-data" (1-minute NIFTY 50 and Bank NIFTY, 2015 - May 2026; the same
dataset the 5-minute history came from), joined to the 10-minute rows of nextcandle_study.rows() for the same days.
Inputs added at the end of each 10-minute candle, from the 1-minute bars before it:
  m_r1, m_r3, m_r5     NIFTY's last 1, 3 and 5 minutes
  m_rv10, m_rv30       volatility of 1-minute moves over the last 10 and 30 minutes, and their ratio (m_rv_ratio)
  m_up10               share of the last 10 minutes that closed up
  m_eff30              how straight the last 30 minutes were: |net move| / sum of |1-minute moves|
  m_bank5, m_lead5     Bank NIFTY's last 5 minutes, and Bank NIFTY minus NIFTY over them
Test: walk-forward by year from 2017 (each year predicted by a model trained only on earlier years), the same LightGBM
settings as nextcandle_study, for the next 30 minutes (3 candles) and 60 minutes (6), with and without these inputs.
Money as there: an at-the-money option moves half as much as NIFTY, minus about 1.85 option points (Rs120 a lot) a
round trip; time decay over 30-60 minutes is not included, so results are a little better than real.
Rule, fixed before the run: the 1-minute inputs pass at a horizon only if its top-20% most confident calls are right
55% of the time or more, earn after costs over all test years and in both halves of them, earn in at least 6 of the
test years, and earn more per trade than the model without them in both halves.
Result: not run yet.
"""
import io
import json
import os
import zipfile

import numpy as np
import pandas as pd

import intraday_data
import nextcandle_study as ns

MIN_FEATS = ["m_r1", "m_r3", "m_r5", "m_rv10", "m_rv30", "m_rv_ratio", "m_up10", "m_eff30", "m_bank5", "m_lead5"]
FILES = {"nifty": "NIFTY 50_minute.csv", "bank": "NIFTY BANK_minute.csv"}
PARAMS = {"objective": "regression", "learning_rate": 0.03, "num_leaves": 15, "min_data_in_leaf": 400,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1}


def minute_days(df):
    """{date: Series of 1-minute closes indexed by bar start (IST, naive)}, session bars only."""
    df = df.rename(columns={"date": "datetime"})
    t = pd.to_datetime(df["datetime"])
    if getattr(t.dt, "tz", None) is not None:
        t = t.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    s = pd.Series(df["close"].astype(float).values, index=t)
    s = s[(s.index.time >= pd.Timestamp("09:15").time()) & (s.index.time <= pd.Timestamp("15:29").time())]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return {d: g for d, g in s.groupby(s.index.date)}


def features(nifty_1m, bank_1m, d, k):
    """The 1-minute inputs at the end of 10-minute candle k on day d (None if the minutes are not there)."""
    g = nifty_1m.get(d)
    if g is None:
        return None
    end = pd.Timestamp(d) + pd.Timedelta(hours=9, minutes=15) + pd.Timedelta(minutes=10 * (k + 1))
    c = g[g.index < end].values
    if len(c) < 31:
        return None
    r = np.diff(c) / c[:-1]
    rv10, rv30 = float(np.std(r[-10:])), float(np.std(r[-30:]))
    path = float(np.abs(np.diff(c[-31:])).sum())
    out = {"m_r1": c[-1] / c[-2] - 1, "m_r3": c[-1] / c[-4] - 1, "m_r5": c[-1] / c[-6] - 1, "m_rv10": rv10, "m_rv30": rv30,
           "m_rv_ratio": rv10 / rv30 if rv30 > 0 else 1.0, "m_up10": float((r[-10:] > 0).mean()),
           "m_eff30": abs(c[-1] - c[-31]) / path if path > 0 else 0.0, "m_bank5": 0.0, "m_lead5": 0.0}
    b = bank_1m.get(d)
    if b is not None:
        bc = b[b.index < end].values
        if len(bc) >= 6:
            out["m_bank5"] = bc[-1] / bc[-6] - 1
            out["m_lead5"] = out["m_bank5"] - out["m_r5"]
    return out


def add_minutes(df, nifty_1m, bank_1m):
    """df (nextcandle_study.rows) restricted to days with 1-minute data, with MIN_FEATS added."""
    rows, keep = [], []
    for i, (d, k) in enumerate(zip(df["d"], df["k"])):
        f = features(nifty_1m, bank_1m, d, int(k))
        if f is not None:
            rows.append(f)
            keep.append(i)
    out = df.iloc[keep].reset_index(drop=True)
    return pd.concat([out, pd.DataFrame(rows)], axis=1)


def walk(df, feats):
    """Top-20% (cut from the training predictions) per test year: trades, right, option points per trade."""
    import lightgbm as lgb
    res = {}
    for y in sorted(df["year"].unique()):
        if y < 2017:
            continue
        tr, te = df[df["year"] < y], df[df["year"] == y]
        if len(te) < 100:
            continue
        m = lgb.train(PARAMS, lgb.Dataset(tr[feats].values, tr["y"].clip(tr["y"].quantile(0.01), tr["y"].quantile(0.99)).values),
                      num_boost_round=300)
        cut = np.quantile(np.abs(m.predict(tr[feats].values)), 0.8)
        res[str(y)] = ns.evaluate(te, m.predict(te[feats].values), cut)
    tops = [(v["top_hit"], v["top_pts"], v["top_trades"]) for v in res.values() if v["top_trades"]]
    n = sum(t for _, _, t in tops)
    half = len(tops) // 2
    avg = lambda part: sum(p * t for _, p, t in part) / max(sum(t for _, _, t in part), 1)
    return {"top_trades": n, "top_hit": round(sum(h * t for h, _, t in tops) / n, 3), "top_pts": round(avg(tops), 2),
            "top_rs_per_lot": round(avg(tops) * 65), "halves_pts": [round(avg(tops[:half]), 2), round(avg(tops[half:]), 2)],
            "years_up": f"{sum(p > 0 for _, p, _ in tops)}/{len(tops)}",
            "by_year_pts": {y: v["top_pts"] for y, v in res.items()}}


def passes(new, base):
    up, n = (int(x) for x in new["years_up"].split("/"))
    return bool(new["top_hit"] >= 0.55 and new["top_pts"] > 0 and all(h > 0 for h in new["halves_pts"]) and up >= 6
                and all(a > b for a, b in zip(new["halves_pts"], base["halves_pts"])))


def load_minutes(get=None):
    if get is None:
        import requests
        get = lambda: requests.get(intraday_data.KAGGLE, headers={"User-Agent": "Mozilla/5.0 (compatible; commodities-trading/1.0)"},
                                   timeout=900).content
    z = zipfile.ZipFile(io.BytesIO(get()))
    names = {os.path.basename(n): n for n in z.namelist()}
    out = {}
    for key, fname in FILES.items():
        if fname not in names:
            print(f"minute: {fname} not in the zip; files: {sorted(n for n in names if 'minute' in n)[:40]}", flush=True)
            out[key] = {}
            continue
        out[key] = minute_days(pd.read_csv(z.open(names[fname])))
    return out


def main():
    try:
        m = load_minutes()
        if not m["nifty"]:
            raise RuntimeError("no 1-minute NIFTY data")
        d = os.environ.get("INTRADAY_DIR", "intra")
        five = [intraday_data.load(d, k) for k in ("nifty", "banknifty", "vix")]
        days = sorted(m["nifty"])
        out = {"minute_days": len(days), "from": str(days[0]), "to": str(days[-1])}
        for h in (3, 6):
            df = add_minutes(ns.rows(*five, h=h), m["nifty"], m["bank"])
            base, new = walk(df, ns.FEATS), walk(df, ns.FEATS + MIN_FEATS)
            out[f"{10 * h} min"] = {"rows": len(df), "without 1-minute inputs": base, "with 1-minute inputs": new,
                                    "passes": passes(new, base)}
            print(f"minute: {10 * h} min done", flush=True)
        print("STUDY minute " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY minute failed: {e!r}", flush=True)
