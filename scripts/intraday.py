"""Intraday nowcast: during the trading session, predict today's close from the candles so far.

Usage: python scripts/intraday.py <key> [out_dir]

Trained on the last ~60 days of 15-minute candles (Yahoo's limit): for every past day and every moment of the
session, features describe the day so far (gap, move so far, position in the day's range, last-hour momentum,
time elapsed) and the target is the remaining move to the close. A ridge regression is evaluated leave-one-day-out,
so the track record shown on the page is out-of-sample. If the session is closed, only the track record is written.
"""
import json
import math
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from evalutil import summarize

ALPHA = 30.0              # ridge strength: small, noisy sample, so keep the model tame
FIRST_BAR = 2             # earliest snapshot (bar index) used for training and prediction
FEATURES = ["z_sofar", "z_gap", "z_intra", "pos", "z_mom", "elapsed", "z_range"]


def _flat(df):
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df.dropna(subset=["Open", "High", "Low", "Close"])


def load(symbol, interval, tz):
    bars = _flat(yf.download(symbol, period="60d", interval=interval, progress=False, auto_adjust=False))
    idx = pd.DatetimeIndex(bars.index)
    bars.index = idx.tz_localize("UTC").tz_convert(tz) if idx.tz is None else idx.tz_convert(tz)
    daily = _flat(yf.download(symbol, period="1y", interval="1d", progress=False, auto_adjust=False))["Close"]
    daily.index = pd.to_datetime(daily.index).tz_localize(None).normalize()
    return bars, daily


def snapshot_features(day, j, prev_close, vol):
    """Features after bar j of the day (bars 0..j known)."""
    b = day.iloc[: j + 1]
    c, o = float(b["Close"].iloc[-1]), float(b["Open"].iloc[0])
    hi, lo = float(b["High"].max()), float(b["Low"].min())
    back = float(b["Close"].iloc[max(j - 4, 0)])
    return [(c / prev_close - 1) / vol, (o / prev_close - 1) / vol, (c / o - 1) / vol, (c - lo) / (hi - lo + 1e-9),
            (c / back - 1) / vol, (j + 1) / 25.0, ((hi - lo) / prev_close) / vol], c


def build(bars, daily, per_day):
    X, y, day_id, bar_idx, price, prevs, closes = [], [], [], [], [], [], []
    dates = sorted({d for d in bars.index.date})
    for n, d in enumerate(dates):
        day = bars[bars.index.date == d]
        key = pd.Timestamp(d)
        if len(day) < per_day - 1 or key not in daily.index:
            continue                                            # incomplete day (today) or no official close
        past = daily[daily.index < key]
        if len(past) < 21:
            continue
        prev_close, close = float(past.iloc[-1]), float(daily[key])
        vol = float(past.pct_change().abs().tail(20).mean())
        for j in range(FIRST_BAR, min(len(day), per_day) - 1):
            f, c = snapshot_features(day, j, prev_close, vol)
            X.append(f)
            y.append((close / c - 1) / vol)
            day_id.append(n)
            bar_idx.append(j)
            price.append(c)
            prevs.append(vol)
            closes.append(close)
    return (np.array(X), np.array(y), np.array(day_id), np.array(bar_idx), np.array(price), np.array(prevs), np.array(closes))


def ridge_fit(X, y):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    reg = np.eye(Z.shape[1]) * ALPHA
    reg[0, 0] = 0.0
    beta = np.linalg.solve(Z.T @ Z + reg, Z.T @ y)
    return {"mu": mu, "sd": sd, "beta": beta}


def ridge_predict(m, X):
    return np.column_stack([np.ones(len(X)), (X - m["mu"]) / m["sd"]]) @ m["beta"]


def cross_validate(X, y, day_id):
    pred = np.zeros(len(y))
    for d in np.unique(day_id):
        te = day_id == d
        pred[te] = ridge_predict(ridge_fit(X[~te], y[~te]), X[te])
    return pred


def stat(mask, price, vol, closes, yhat):
    if mask.sum() < 20:
        return {"days": 0}
    rows = np.column_stack([np.zeros(mask.sum()), price[mask], closes[mask], price[mask] * (1 + yhat[mask] * vol[mask])])
    s = summarize(rows)
    s["snapshots"] = s.pop("days")
    return s


def run(inst, out_dir):
    cfg = inst["intraday"]
    tz = inst["tz"]
    now = datetime.now(ZoneInfo(tz))
    minutes = (int(inst["close"][:2]) * 60 + int(inst["close"][3:])) - (int(cfg["open"][:2]) * 60 + int(cfg["open"][3:]))
    per_day = minutes // int(cfg["interval"].rstrip("m"))
    bars, daily = load(inst["ticker"], cfg["interval"], tz)
    X, y, day_id, bar_idx, price, vol, closes = build(bars, daily, per_day)
    out = {"key": inst["key"], "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "no_data"}
    if len(y) < 200:
        print("not enough intraday history:", len(y))
        return out
    yhat = cross_validate(X, y, day_id)
    # Shrink toward "the day ends where it is now" by however much the out-of-sample forecasts actually helped
    # (least-squares slope of the real remaining move on the forecast, kept within 0..1).
    shrink = float(np.clip((y * yhat).sum() / max((yhat * yhat).sum(), 1e-12), 0.0, 1.0))
    yhat = yhat * shrink
    out["backtest"] = {"days": int(len(np.unique(day_id))), "shrink": round(shrink, 3), "all": stat(np.ones(len(y), bool), price, vol, closes, yhat),
                       "morning": stat(bar_idx < 8, price, vol, closes, yhat),
                       "midday": stat((bar_idx >= 8) & (bar_idx < 16), price, vol, closes, yhat),
                       "late": stat(bar_idx >= 16, price, vol, closes, yhat)}
    resid = (y - yhat)
    # today's session so far
    today = bars[bars.index.date == now.date()]
    if len(today) == 0:
        out["status"] = "closed"
        return out
    prev_series = daily[daily.index < pd.Timestamp(now.date())]
    prev_close = float(prev_series.iloc[-1])
    v = float(prev_series.pct_change().abs().tail(20).mean())
    j = min(len(today), per_day) - 1
    out.update({"date": now.strftime("%Y-%m-%d"), "asof": today.index[-1].strftime("%H:%M"), "prev_close": round(prev_close, 2),
                "open": round(float(today["Open"].iloc[0]), 2), "high": round(float(today["High"].max()), 2),
                "low": round(float(today["Low"].min()), 2)})
    if j >= per_day - 1:
        out.update({"status": "closed", "price_now": round(float(today["Close"].iloc[-1]), 2)})
        return out
    f, c = snapshot_features(today, max(j, FIRST_BAR), prev_close, v)
    model = ridge_fit(X, y)
    yh = float(ridge_predict(model, np.array([f]))[0]) * shrink
    pred = c * (1 + yh * v)
    q10, q90 = np.percentile(resid, [10, 90])
    sigma = float(resid.std()) or 1.0
    out.update({"status": "open", "price_now": round(c, 2), "pred_close": round(pred, 2),
                "p10": round(c * (1 + (yh + q10) * v), 2), "p90": round(c * (1 + (yh + q90) * v), 2),
                "prob_up_vs_now": round(0.5 * (1 + math.erf(yh / sigma / math.sqrt(2))), 3),
                "pred_vs_prev_pct": round((pred / prev_close - 1) * 100, 3)})
    return out


def main(key, out_dir="docs/data"):
    inst = next(i for i in json.load(open("scripts/instruments.json")) if i["key"] == key)
    if "intraday" not in inst:
        raise SystemExit(f"{key} has no intraday config")
    out = run(inst, out_dir)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"intraday-{key}.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
