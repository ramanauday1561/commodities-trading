"""Combine the individual models into one honest "best estimate", and calibrate probabilities.

The blend is a non-negative least-squares regression of the real 1-day return on each model's predicted 1-day
return (fitted on the walk-forward backtest). Models that do not help get weight 0, and weights summing to less
than 1 shrink the forecast toward "no change" (the implicit "same as yesterday" member). Its own backtest is
cross-validated, so the reported track record is out-of-sample.
"""
import math

import numpy as np
from scipy.optimize import nnls

from evalutil import full_stats

MIN_COMMON = 40           # minimum backtest days shared by all models to fit a blend
FOLDS = 5


BAGS = 200


def _cap(w):
    return w / w.sum() if w.sum() > 1 else w          # weights never exceed 100% in total


def _nnls_capped(X, y):
    """Bagged NNLS: the average of NNLS fits on bootstrap resamples. A single fit on ~150 noisy days swings a lot
    between runs; averaging keeps the weights stable and shrinks marginal models toward zero."""
    rng = np.random.default_rng(0)
    n = len(y)
    ws = []
    for _ in range(BAGS):
        i = rng.integers(0, n, n)
        ws.append(nnls(X[i], y[i])[0])
    return _cap(np.mean(ws, axis=0))


def platt_fit(s, y):
    """P(up) = sigmoid(a + b * s / sd). Logistic fit with a small L2 penalty; slope is never negative."""
    s, y = np.asarray(s, float), np.asarray(y, float)
    sd = float(s.std()) or 1.0
    z = s / sd
    base = float(np.clip(y.mean(), 0.02, 0.98))
    a, b = math.log(base / (1 - base)), 0.0
    for _ in range(50):                               # Newton-Raphson
        p = 1 / (1 + np.exp(-(a + b * z)))
        w = p * (1 - p) + 1e-9
        g = np.array([np.sum(p - y), np.sum((p - y) * z) + 1.0 * b])
        H = np.array([[w.sum(), (w * z).sum()], [(w * z).sum(), (w * z * z).sum() + 1.0]])
        step = np.linalg.solve(H, g)
        a, b = a - step[0], b - step[1]
        if np.abs(step).max() < 1e-7:
            break
    if b < 0:                                         # anti-predictive: fall back to the base rate
        a, b = math.log(base / (1 - base)), 0.0
    return {"a": float(a), "b": float(b), "sd": sd}


def platt_prob(cal, s):
    return float(1 / (1 + math.exp(-(cal["a"] + cal["b"] * s / cal["sd"]))))


def fit_blend(rows_by_model, n, index):
    """rows_by_model: {model: rows of (day index, prev close, actual close, predicted close)}.
    Returns None, or a dict with weights, cross-validated backtest stats, calibration quantiles and Platt fits."""
    keys = list(rows_by_model)
    common = sorted(set.intersection(*[set(r[:, 0].astype(int)) for r in rows_by_model.values()]))
    if len(keys) < 2 or len(common) < MIN_COMMON:
        return None
    sel = {k: {int(t): row for t, row in zip(r[:, 0], r)} for k, r in rows_by_model.items()}
    prev = np.array([sel[keys[0]][t][1] for t in common])
    actual = np.array([sel[keys[0]][t][2] for t in common])
    X = np.column_stack([[sel[k][t][3] / sel[k][t][1] - 1 for t in common] for k in keys])
    y = actual / prev - 1

    oof = np.zeros(len(y))
    for fold in np.array_split(np.arange(len(y)), FOLDS):        # time-ordered blocks
        train = np.setdiff1d(np.arange(len(y)), fold)
        oof[fold] = X[fold] @ _nnls_capped(X[train], y[train])
    rows = np.column_stack([common, prev, actual, prev * (1 + oof)])
    stats, cal = full_stats(rows, n, index)

    w = _nnls_capped(X, y)
    platt = {k: platt_fit(X[:, i], y > 0) for i, k in enumerate(keys)}
    platt["blend"] = platt_fit(oof, y > 0)
    return {"weights": {k: round(float(w[i]), 4) for i, k in enumerate(keys)}, "naive_weight": round(float(1 - w.sum()), 4),
            "stats": stats, "cal": cal, "platt": platt, "rows": rows, "days": len(common)}


def blend_forecast(models, fit, future, last_close, exp_range):
    """Blended candles for each forecast day from the individual models' forecasts."""
    keys = list(fit["weights"])
    out, prev_close = [], last_close
    for k, day in enumerate(future, start=1):
        ret = sum(fit["weights"][m] * (models[m]["forecast"][k - 1]["close"] / last_close - 1) for m in keys)
        c = last_close * (1 + ret)
        o = prev_close
        rng = exp_range if exp_range else float(np.mean([(models[m]["forecast"][k - 1]["high"] - models[m]["forecast"][k - 1]["low"])
                                                          / models[m]["forecast"][k - 1]["close"] for m in keys]))
        wick = max(rng * c - abs(c - o), 0) / 2
        w = k ** 0.5
        lo, hi = c * (1 + fit["cal"][0] * w), c * (1 + fit["cal"][1] * w)
        out.append({"time": day.strftime("%Y-%m-%d"), "open": round(o, 2), "high": round(max(o, c) + wick, 2),
                    "low": round(min(o, c) - wick, 2), "close": round(c, 2),
                    "close_p10": round(lo, 2), "close_p90": round(hi, 2), "cal_p10": round(lo, 2), "cal_p90": round(hi, 2),
                    "prob_up": round(platt_prob(fit["platt"]["blend"], ret / w), 3)})
        prev_close = c
    return out
