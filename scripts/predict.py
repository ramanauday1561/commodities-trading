"""Fetch NIFTY 50 daily candles (Yahoo Finance), forecast the next 4 candles with Kronos and
walk-forward backtest the model on recent history."""
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import torch
import yfinance as yf

sys.path.append("Kronos")  # cloned by the workflow
from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

SYMBOL = "^NSEI"          # any Yahoo Finance ticker, e.g. "^NSEBANK", "GC=F", "CL=F"
NAME = "NIFTY 50"
MODEL = "NeoQuasar/Kronos-base"
CONTEXT = 512             # Kronos' maximum context window (candles fed to the model)
HORIZON = 4               # working days to forecast
SAMPLES = 30              # Monte-Carlo paths for the forecast band
BACKTEST_DAYS = 40        # walk-forward 1-day-ahead backtest length
BACKTEST_SAMPLES = 5
OUT = "docs/data.json"

raw = yf.download(SYMBOL, period="max", interval="1d", auto_adjust=False, progress=False)
raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
raw.index = pd.to_datetime(raw.index).tz_localize(None)
full = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].fillna(0.0)
print(f"history: {len(full)} candles, {full.index[0].date()} -> {full.index[-1].date()}")

tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
model = Kronos.from_pretrained(MODEL)
predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)

# ---------------- forecast: next HORIZON working days ----------------
ctx = full.tail(CONTEXT)
df = ctx.reset_index(drop=True)
x_ts = pd.Series(ctx.index)
future = pd.bdate_range(ctx.index[-1] + pd.Timedelta(days=1), periods=HORIZON)  # ignores NSE holidays
y_ts = pd.Series(future)

paths = []
for i in range(SAMPLES):
    torch.manual_seed(i)
    p = predictor.predict(df=df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=HORIZON,
                          T=1.0, top_p=0.9, sample_count=1, verbose=False)
    paths.append(p[["open", "high", "low", "close"]].values)
paths = np.array(paths)                     # (samples, horizon, 4)
mean = paths.mean(axis=0)
closes = paths[:, :, 3]
last_close = float(df["close"].iloc[-1])

forecast = []
for k, day in enumerate(future):
    o, h, l, c = (round(float(v), 2) for v in mean[k])
    h, l = max(h, o, c), min(l, o, c)
    forecast.append({
        "time": day.strftime("%Y-%m-%d"), "open": o, "high": h, "low": l, "close": c,
        "close_p10": round(float(np.percentile(closes[:, k], 10)), 2),
        "close_p90": round(float(np.percentile(closes[:, k], 90)), 2),
        "prob_up": round(float((closes[:, k] > last_close).mean()), 3),
    })

# ---------------- walk-forward backtest (1 day ahead) ----------------
bt = {"days": 0}
try:
    n = len(full)
    idx = list(range(n - BACKTEST_DAYS, n))
    rows = []
    for s in range(0, len(idx), 8):
        chunk = idx[s:s + 8]
        dfs, xs, ys = [], [], []
        for t in chunk:
            w = full.iloc[t - CONTEXT:t]
            dfs.append(w.reset_index(drop=True))
            xs.append(pd.Series(w.index))
            ys.append(pd.Series([full.index[t]]))
        torch.manual_seed(s)
        outs = predictor.predict_batch(dfs, xs, ys, pred_len=1, T=1.0, top_p=0.9,
                                       sample_count=BACKTEST_SAMPLES, verbose=False)
        for t, o in zip(chunk, outs):
            prev, actual = float(full["close"].iloc[t - 1]), float(full["close"].iloc[t])
            pred = float(o["close"].iloc[0])
            rows.append((prev, actual, pred))
    r = np.array(rows)
    hit = ((r[:, 2] > r[:, 0]) == (r[:, 1] > r[:, 0])).mean()
    mape = (np.abs(r[:, 2] - r[:, 1]) / r[:, 1]).mean() * 100
    naive = (np.abs(r[:, 0] - r[:, 1]) / r[:, 1]).mean() * 100   # "tomorrow = today" baseline
    bt = {"days": len(r), "direction_accuracy": round(float(hit), 3),
          "mape_pct": round(float(mape), 3), "naive_mape_pct": round(float(naive), 3)}
except Exception as e:  # backtest is a bonus; never block the forecast
    print("backtest failed:", repr(e))
print("backtest:", bt)

candles = [
    {"time": d.strftime("%Y-%m-%d"), "open": round(float(r.open), 2), "high": round(float(r.high), 2),
     "low": round(float(r.low), 2), "close": round(float(r.close), 2)}
    for d, r in zip(full.index, full.itertuples())
]
out = {
    "symbol": NAME, "ticker": SYMBOL, "model": MODEL.split("/")[-1],
    "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "last_close": round(last_close, 2), "last_date": full.index[-1].strftime("%Y-%m-%d"),
    "history_start": full.index[0].strftime("%Y-%m-%d"), "context": len(df), "samples": SAMPLES,
    "candles": candles, "forecast": forecast, "backtest": bt,
}
with open(OUT, "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(json.dumps(forecast, indent=1))
