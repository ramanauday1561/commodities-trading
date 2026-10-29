"""LightGBM forecaster trained on an instrument's complete daily history.

Direct multi-horizon models predict the log-return of the close 1..HORIZON days ahead from price-only
features (returns, volatility, trend, RSI, ranges, calendar). Quantile models give P10/P90, a classifier
gives P(up), and a range model shapes the candle's high/low. Walk-forward backtest: for each test day the
model is retrained only on data that was known before that day.

Likely range: the quantile models make it wider on volatile days and narrower on calm ones; a single factor, measured
on the backtest days, scales it so that 8 in 10 real closes fell inside. Big-move risk: a classifier for "the next
close moves more than big_move_pct", scored against the plain historical frequency of such days.
(Both were chosen with scripts/experiment.py, mode "risk": better interval score and Brier score on 375 test days for
all four instruments.)
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


def features(df, exo=None):
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
    if exo is not None:
        f = pd.concat([f, exo.reindex(df.index)], axis=1)
    return f.replace([np.inf, -np.inf], np.nan)


def fit(X, y, objective, alpha=None):
    p = dict(PARAMS, objective=objective)
    if alpha is not None:
        p["alpha"] = alpha
    return lgb.train(p, lgb.Dataset(X, y), num_boost_round=ROUNDS)


def winsorize(y):
    lo, hi = np.percentile(y, [1, 99])
    return np.clip(y, lo, hi)


def auc(p, y):
    """Chance a random big-move day scored higher than a random calm day (0.5 = no skill)."""
    p, y = np.asarray(p), np.asarray(y)
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    r = pd.Series(np.concatenate([pos, neg])).rank().values
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def run_gbm(full, future, last_close, indices, exo=None, big_move_pct=None):
    feats = features(full, exo)
    logc = np.log(full["close"].values)
    n = len(full)
    X = feats.values
    valid = np.arange(n) >= WARMUP

    def target(h):                      # log-return of close h days after row i (NaN at the end)
        t = np.full(n, np.nan)
        t[:n - h] = logc[h:] - logc[:n - h]
        return t

    # ---- walk-forward backtest, 1 day ahead ----
    bt, cal, bt_rows = {"days": 0}, None, None
    y1 = target(1)
    thr = np.log(1 + big_move_pct / 100) if big_move_pct else None
    big = (np.abs(y1) > thr).astype(float) if thr else None
    z, risk_bt = [], []                   # range misses in half-widths; (p, base rate, outcome) for big moves
    if indices:
        rows = []
        for t in indices:
            tr = np.where(valid & ~np.isnan(y1) & (np.arange(n) <= t - 2))[0]   # targets known before day t
            if len(tr) < MIN_TRAIN:
                continue
            x, yw, actual = X[[t - 1]], winsorize(y1[tr]), y1[t - 1]
            m = float(fit(X[tr], yw, "regression").predict(x)[0])
            q10 = min(float(fit(X[tr], yw, "quantile", 0.1).predict(x)[0]), m)
            q90 = max(float(fit(X[tr], yw, "quantile", 0.9).predict(x)[0]), m)
            if q90 > q10:
                z.append(abs(actual - (q10 + q90) / 2) / ((q90 - q10) / 2))
            if thr:
                risk_bt.append((float(fit(X[tr], big[tr], "binary").predict(x)[0]), float(big[tr].mean()),
                                float(abs(actual) > thr)))
            pred = float(full["close"].iloc[t - 1] * np.exp(m))
            rows.append((t, float(full["close"].iloc[t - 1]), float(full["close"].iloc[t]), pred))
        if rows:
            bt_rows = np.array(rows)
            bt, cal = full_stats(bt_rows, n, full.index)
    scale = float(np.quantile(z, 0.8)) if len(z) >= 30 else 1.0     # makes the quantile range hold 8 in 10 closes

    # ---- forecast: train on everything known now ----
    last = X[[n - 1]]
    rng_t = np.full(n, np.nan)          # next-day (high-low)/close
    rng_t[:n - 1] = ((full["high"] - full["low"]) / full["close"]).values[1:]
    tr = np.where(valid & ~np.isnan(rng_t))[0]
    exp_range = float(max(fit(X[tr], winsorize(rng_t[tr]), "regression").predict(last)[0], 0.0))
    out, prev_close, used, half_widths = [], last_close, 0, []
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
        half = scale * (max(q90, mean) - min(q10, mean)) / 2                  # log-return half-width of the likely range
        half_widths.append(half)
        o = prev_close
        wick = max(exp_range * c - abs(c - o), 0) / 2
        row = {"time": day.strftime("%Y-%m-%d"), "open": round(o, 2), "high": round(max(o, c) + wick, 2),
               "low": round(min(o, c) - wick, 2), "close": round(c, 2),
               "close_p10": round(last_close * np.exp(min(q10, mean)), 2),
               "close_p90": round(last_close * np.exp(max(q90, mean)), 2), "prob_up": round(p_up, 3)}
        row["cal_p10"], row["cal_p90"] = round(c * np.exp(-half), 2), round(c * np.exp(half), 2)
        out.append(row)
        prev_close = c
    risk = None
    if thr:
        tr = np.where(valid & ~np.isnan(y1))[0]
        p_now = float(fit(X[tr], big[tr], "binary").predict(last)[0])
        risk = {"threshold_pct": big_move_pct, "p": round(p_now, 3), "base_rate": round(float(big[tr].mean()), 3),
                "recent_rate": round(float(big[tr[-60:]].mean()), 3)}
        if len(risk_bt) >= 30:
            p, clim, o = map(np.array, zip(*risk_bt))
            b, bc = float(((p - o) ** 2).mean()), float(((clim - o) ** 2).mean())
            risk["backtest"] = {"days": len(o), "brier": round(b, 4), "brier_base": round(bc, 4),
                                "skill": round(1 - b / bc, 3) if bc > 0 else 0.0, "auc": None if auc(p, o) is None else round(auc(p, o), 3),
                                "big_day_rate": round(float(o.mean()), 3)}
    return {"forecast": out, "backtest": bt, "cal": cal, "rows": bt_rows, "rows_used": used, "exp_range": exp_range,
            "n_features": int(X.shape[1]), "half_widths": half_widths, "range_scale": round(scale, 3),
            "range_coverage_days": len(z), "risk": risk}
