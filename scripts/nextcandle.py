"""The next 10-minute candle: the model's lean, shown as information next to its tested record (29 Oct 2026).

The user asked for a next-candle prediction to buy a CALL or PUT on. nextcandle_study.py tested it on 11 years: the
model's top-20% calls were right 53.1% of the time but lost about Rs73 a lot a trade after option costs, in every year
from 2017. The user chose to see the lean anyway, as information, always beside that record; it is never a CALL / PUT.
  python scripts/nextcandle.py train <intraday_dir> <out_dir>   nightly: fit on all stored candles, write
                                                               <out_dir>/nextcandle-model.txt and nextcandle-meta.json
  lean(model_dir, now)                                         live.py: the lean after the last finished candle
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import nextcandle_study as ns

PARAMS = {"objective": "regression", "learning_rate": 0.03, "num_leaves": 15, "min_data_in_leaf": 400,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1, "seed": 1}
RECORD = {"right_pct": 53.1, "rs_per_lot": -73, "years_up": "0 of 10",
          "text": "tested 2017-2026: its most confident calls were right 53% of the time but lost about Rs73 a lot per "
                  "trade after option costs, in every year"}


def train(intra_dir, out_dir):
    import lightgbm as lgb
    import intraday_data
    df = ns.rows(*(intraday_data.load(intra_dir, k) for k in ("nifty", "banknifty", "vix")))
    y = df["y"].clip(df["y"].quantile(0.01), df["y"].quantile(0.99))
    m = lgb.train(PARAMS, lgb.Dataset(df[ns.FEATS].values, y.values), num_boost_round=300)
    cut = float(np.quantile(np.abs(m.predict(df[ns.FEATS].values)), 0.8))
    os.makedirs(out_dir, exist_ok=True)
    m.save_model(os.path.join(out_dir, "nextcandle-model.txt"))
    meta = {"trained_until": str(df["d"].max()), "candles": len(df), "confident_cut": cut, "record": RECORD}
    json.dump(meta, open(os.path.join(out_dir, "nextcandle-meta.json"), "w"))
    print(f"nextcandle: trained on {len(df)} candles to {meta['trained_until']}", flush=True)
    return meta


def yahoo_days(symbol):
    """The last few days of 5-minute candles as {date: DataFrame} (IST, naive), like intraday_data.load()."""
    import yfinance as yf
    raw = yf.download(symbol, period="5d", interval="5m", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    idx = pd.DatetimeIndex(raw.index)
    raw.index = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert("Asia/Kolkata").tz_localize(None)
    raw = raw[(raw.index.time >= pd.Timestamp("09:15").time()) & (raw.index.time <= pd.Timestamp("15:25").time())]
    return {d: g[["Open", "High", "Low", "Close"]] for d, g in raw.groupby(raw.index.date)}


def lean(model_dir, now, get=yahoo_days):
    """{"at", "lean", "pts", "confident", "record"} for the candle after the last finished one today, or None."""
    import lightgbm as lgb
    mp, meta_p = os.path.join(model_dir, "nextcandle-model.txt"), os.path.join(model_dir, "nextcandle-meta.json")
    if not os.path.exists(mp) or not os.path.exists(meta_p):
        return None
    days = {k: get(s) for k, s in (("nifty", "^NSEI"), ("bank", "^NSEBANK"), ("vix", "^INDIAVIX"))}
    today = now.date()
    if today not in days["nifty"]:
        return None
    df = ns.rows(days["nifty"], days["bank"], days["vix"], live=True)
    df = df[df["d"] == today]
    if df.empty:
        return None
    last = df.iloc[-1]
    meta = json.load(open(meta_p))
    p = float(lgb.Booster(model_file=mp).predict(df[ns.FEATS].values[-1:])[0])
    start = pd.Timestamp(today) + pd.Timedelta(hours=9, minutes=15) + pd.Timedelta(minutes=10 * (int(last["k"]) + 1))
    return {"at": start.strftime("%H:%M"), "lean": "up" if p > 0 else "down", "pts": round(p * float(last["price"]), 1),
            "confident": abs(p) >= meta["confident_cut"], "record": meta["record"]}


if __name__ == "__main__":
    if sys.argv[1:2] == ["train"]:
        train(sys.argv[2], sys.argv[3])
