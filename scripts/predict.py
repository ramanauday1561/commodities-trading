"""Usage: python scripts/predict.py <key>   (keys in scripts/instruments.json)

Fetch the complete daily history (Yahoo Finance) and, with two Kronos models, forecast the next 4 candles:
  * base: Kronos-base, reads the latest 512 candles
  * mini: Kronos-mini, reads the latest 2048 candles (~8 years of daily data)
Each model is walk-forward backtested across the *whole* history; the backtest errors are then used to
calibrate the forecast ranges.
"""
import json
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import torch
import yfinance as yf

sys.path.append("Kronos")  # cloned by the workflow
from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

MODELS = {
    "base": {"label": "Kronos-base", "model": "NeoQuasar/Kronos-base",
             "tokenizer": "NeoQuasar/Kronos-Tokenizer-base", "context": 512},
    "mini": {"label": "Kronos-mini", "model": "NeoQuasar/Kronos-mini",
             "tokenizer": "NeoQuasar/Kronos-Tokenizer-2k", "context": 2048},
}
HORIZON = 4               # working days to forecast
SAMPLES = 30              # Monte-Carlo paths for the forecast band
BT_SPREAD = 100           # backtest days spread evenly across the whole history
BT_RECENT = 50            # plus the most recent days
BT_SAMPLES = 3            # samples averaged per backtest prediction
BT_BATCH = 8
COLS = ["open", "high", "low", "close"]


def load_history(symbol):
    raw = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return raw.rename(columns=str.lower)[COLS + ["volume"]].fillna(0.0)


def forecast(predictor, full, context, future):
    ctx = full.tail(context)
    df, x_ts, y_ts = ctx.reset_index(drop=True), pd.Series(ctx.index), pd.Series(future)
    paths = []
    for i in range(SAMPLES):
        torch.manual_seed(i)
        p = predictor.predict(df=df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=len(future),
                              T=1.0, top_p=0.9, sample_count=1, verbose=False)
        paths.append(p[COLS].values)
    return np.array(paths), len(df)                       # (samples, horizon, 4)


def backtest(predictor, full, context, indices):
    """Walk-forward 1-day-ahead predictions. Returns rows of (day index, previous close, actual close, predicted close)."""
    rows = []
    for s in range(0, len(indices), BT_BATCH):
        chunk = indices[s:s + BT_BATCH]
        dfs, xs, ys = [], [], []
        for t in chunk:
            w = full.iloc[t - context:t]
            dfs.append(w.reset_index(drop=True))
            xs.append(pd.Series(w.index))
            ys.append(pd.Series([full.index[t]]))
        torch.manual_seed(s)
        outs = predictor.predict_batch(dfs, xs, ys, pred_len=1, T=1.0, top_p=0.9,
                                       sample_count=BT_SAMPLES, verbose=False)
        for t, o in zip(chunk, outs):
            rows.append((t, float(full["close"].iloc[t - 1]), float(full["close"].iloc[t]), float(o["close"].iloc[0])))
    return np.array(rows)


def summarize(r):
    prev, actual, pred = r[:, 1], r[:, 2], r[:, 3]
    return {
        "days": int(len(r)),
        "direction_accuracy": round(float(((pred > prev) == (actual > prev)).mean()), 3),
        "up_rate": round(float((actual > prev).mean()), 3),                       # baseline: always guess "up"
        "mape_pct": round(float((np.abs(pred - actual) / actual).mean() * 100), 3),
        "naive_mape_pct": round(float((np.abs(prev - actual) / actual).mean() * 100), 3),  # "same as yesterday"
    }


def run_backtest(predictor, full, context):
    n = len(full)
    if n - BT_RECENT - 1 <= context:
        return {"days": 0}, None
    recent = list(range(n - BT_RECENT, n))
    spread = np.linspace(context, n - BT_RECENT - 1, BT_SPREAD).astype(int).tolist()
    idx = sorted(set(spread + recent))
    r = backtest(predictor, full, context, idx)
    err = r[:, 2] / r[:, 3] - 1                                                 # actual vs predicted close
    stats = {"all": summarize(r), "recent": summarize(r[r[:, 0] >= n - BT_RECENT]),
             "span": [full.index[idx[0]].strftime("%Y-%m-%d"), full.index[idx[-1]].strftime("%Y-%m-%d")]}
    stats["days"] = stats["all"]["days"]
    return stats, (float(np.percentile(err, 10)), float(np.percentile(err, 90)))


def build_forecast(paths, future, last_close, cal):
    mean, closes = paths.mean(axis=0), paths[:, :, 3]
    out = []
    for k, day in enumerate(future):
        o, h, l, c = (round(float(v), 2) for v in mean[k])
        row = {"time": day.strftime("%Y-%m-%d"), "open": o, "high": max(h, o, c), "low": min(l, o, c), "close": c,
               "close_p10": round(float(np.percentile(closes[:, k], 10)), 2),
               "close_p90": round(float(np.percentile(closes[:, k], 90)), 2),
               "prob_up": round(float((closes[:, k] > last_close).mean()), 3)}
        if cal:   # historical error quantiles of this model, widened with sqrt(days ahead)
            w = (k + 1) ** 0.5
            row["cal_p10"], row["cal_p90"] = round(c * (1 + cal[0] * w), 2), round(c * (1 + cal[1] * w), 2)
        out.append(row)
    return out


def main(key):
    inst = next(i for i in json.load(open("scripts/instruments.json")) if i["key"] == key)
    full = load_history(inst["ticker"])

    # Forecast starts from *today* (exchange time): while the session is open, today's candle is incomplete,
    # so keep it out of the model input and predict it instead.
    now_ex = datetime.now(ZoneInfo(inst["tz"]))
    close_h, close_m = map(int, inst["close"].split(":"))
    today_live, last_d = None, full.index[-1].date()
    if last_d > now_ex.date() or (last_d == now_ex.date() and (now_ex.hour, now_ex.minute) < (close_h, close_m)):
        row = full.iloc[-1]
        today_live = {"time": full.index[-1].strftime("%Y-%m-%d"), **{c: round(float(row[c]), 2) for c in COLS}}
        full = full.iloc[:-1]
    print(f"history: {len(full)} candles, {full.index[0].date()} -> {full.index[-1].date()}")

    future = pd.bdate_range(full.index[-1] + pd.Timedelta(days=1), periods=HORIZON)  # weekends skipped, holidays not
    last_close = float(full["close"].iloc[-1])
    models, backtests = {}, {}
    for mkey, m in MODELS.items():
        if len(full) < 300:
            continue
        ctx_len = min(m["context"], len(full))
        predictor = KronosPredictor(Kronos.from_pretrained(m["model"]), KronosTokenizer.from_pretrained(m["tokenizer"]),
                                    device="cpu", max_context=m["context"])
        try:
            bt, cal = run_backtest(predictor, full, m["context"])
        except Exception as e:  # backtest is a bonus; never block the forecast
            print(f"{mkey} backtest failed:", repr(e))
            bt, cal = {"days": 0}, None
        paths, used = forecast(predictor, full, ctx_len, future)
        models[mkey] = {"label": m["label"], "context": used, "forecast": build_forecast(paths, future, last_close, cal)}
        backtests[mkey] = bt
        print(mkey, json.dumps(bt))

    candles = [{"time": d.strftime("%Y-%m-%d"), **{c: round(float(r[c]), 2) for c in COLS}}
               for d, (_, r) in zip(full.index, full.iterrows())]
    out = {
        "key": key, "symbol": inst["name"], "ticker": inst["ticker"], "unit": inst["unit"], "group": inst["group"],
        "starts_today": bool(future[0].date() == now_ex.date()),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_close": round(last_close, 2), "last_date": full.index[-1].strftime("%Y-%m-%d"),
        "history_start": full.index[0].strftime("%Y-%m-%d"), "samples": SAMPLES,
        "candles": candles, "models": models, "backtest": backtests, "today_live": today_live,
    }
    with open(f"docs/data/{key}.json", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(json.dumps({k: v["forecast"][0] for k, v in models.items()}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
