"""LightGBM forecaster trained on an instrument's complete daily history.

Direct multi-horizon models predict the log-return of the close 1..HORIZON days ahead from price-only
features (returns, volatility, trend, RSI, ranges, calendar). Quantile models give P10/P90, a classifier
gives P(up), and a range model shapes the candle's high/low. Walk-forward backtest: for each test day the
model is retrained only on data that was known before that day.
"""
import numpy as np
import pandas as pd
import lightgbm as lgb

from evalutil import full_stats

HORIZON = 4
MIN_TRAIN = 300           # minimum training rows before a prediction is allowed
WARMUP = 252              # rows dropped while long rolling windows fill up
PARAMS = dict(learning_rate=0.03, num_leaves=8, min_data_in_leaf=60, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, num_threads=2, seed=0,
              deterministic=True, force_row_wise=True)
ROUNDS = 120


def features(df):
    """Scale-free features; row i only uses candles up to and including i."""
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]
    r1 = np.log(c).diff()
    f = pd.DataFrame(index=df.index)
    for n in (1, 2, 3, 5, 10, 21, 63):
        f[f"ret{n}"] = np.log(c).diff(n)
    for n in (5, 10, 21, 63):
        f[f"vol{n}"] = r1.rolling(n).std()
    f["vol_ratio"] = f["vol5"] / f["vol63"]
    f["range"] = (h - l) / c
    f["body"] = (c - o) / o
    f["upper_wick"] = (h - np.maximum(o, c)) / c
    f["lower_wick"] = (np.minimum(o, c) - l) / c
    f["atr14"] = ((h - l) / c).rolling(14).mean()
    for n in (10, 20, 50, 200):
        f[f"dist_sma{n}"] = c / c.rolling(n).mean() - 1
    f["dist_hi252"] = c / h.rolling(252).max() - 1
    f["dist_lo252"] = c / l.rolling(252).min() - 1
    d = c.diff()
    up, dn = d.clip(lower=0).rolling(14).mean(), (-d.clip(upper=0)).rolling(14).mean()
    f["rsi14"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    macd = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    f["macd"] = (macd - macd.ewm(span=9).mean()) / c
    if (v > 0).mean() > 0.5:
        f["vol_z"] = np.log1p(v) - np.log1p(v).rolling(20).mean()
    f["dow"] = df.index.dayofweek
    f["month"] = df.index.month
    return f.replace([np.inf, -np.inf], np.nan)


def fit(X, y, objective, alpha=None):
    p = dict(PARAMS, objective=objective)
    if alpha is not None:
        p["alpha"] = alpha
    return lgb.train(p, lgb.Dataset(X, y), num_boost_round=ROUNDS)


def winsorize(y):
    lo, hi = np.percentile(y, [1, 99])
    return np.clip(y, lo, hi)


def run_gbm(full, future, last_close, indices):
    feats = features(full)
    logc = np.log(full["close"].values)
    n = len(full)
    X = feats.values
    valid = np.arange(n) >= WARMUP

    def target(h):                      # log-return of close h days after row i (NaN at the end)
        t = np.full(n, np.nan)
        t[:n - h] = logc[h:] - logc[:n - h]
        return t

    # ---- walk-forward backtest, 1 day ahead ----
    bt, cal = {"days": 0}, None
    if indices:
        y1 = target(1)
        rows = []
        for t in indices:
            tr = np.where(valid & ~np.isnan(y1) & (np.arange(n) <= t - 2))[0]   # targets known before day t
            if len(tr) < MIN_TRAIN:
                continue
            m = fit(X[tr], winsorize(y1[tr]), "regression")
            pred = float(full["close"].iloc[t - 1] * np.exp(m.predict(X[[t - 1]])[0]))
            rows.append((t, float(full["close"].iloc[t - 1]), float(full["close"].iloc[t]), pred))
        if rows:
            bt, cal = full_stats(np.array(rows), n, full.index)

    # ---- forecast: train on everything known now ----
    last = X[[n - 1]]
    ys = target(1)
    rng_t = np.full(n, np.nan)          # next-day (high-low)/close
    rng_t[:n - 1] = ((full["high"] - full["low"]) / full["close"]).values[1:]
    tr = np.where(valid & ~np.isnan(rng_t))[0]
    exp_range = float(max(fit(X[tr], winsorize(rng_t[tr]), "regression").predict(last)[0], 0.0))
    out, prev_close, used = [], last_close, 0
    for k, day in enumerate(future, start=1):
        y = target(k)
        tr = np.where(valid & ~np.isnan(y))[0]
        used = len(tr)
        yw = winsorize(y[tr])
        mean = float(fit(X[tr], yw, "regression").predict(last)[0])
        q10 = float(fit(X[tr], yw, "quantile", 0.1).predict(last)[0])
        q90 = float(fit(X[tr], yw, "quantile", 0.9).predict(last)[0])
        p_up = float(fit(X[tr], (y[tr] > 0).astype(float), "binary").predict(last)[0])
        c = last_close * np.exp(mean)
        o = prev_close
        wick = max(exp_range * c - abs(c - o), 0) / 2
        row = {"time": day.strftime("%Y-%m-%d"), "open": round(o, 2), "high": round(max(o, c) + wick, 2),
               "low": round(min(o, c) - wick, 2), "close": round(c, 2),
               "close_p10": round(last_close * np.exp(min(q10, mean)), 2),
               "close_p90": round(last_close * np.exp(max(q90, mean)), 2), "prob_up": round(p_up, 3)}
        if cal:
            w = k ** 0.5
            row["cal_p10"], row["cal_p90"] = round(c * (1 + cal[0] * w), 2), round(c * (1 + cal[1] * w), 2)
        out.append(row)
        prev_close = c
    return out, bt, used
