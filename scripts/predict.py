"""Fetch NIFTY 50 daily candles (Yahoo Finance) and predict the next one with Kronos."""
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import torch
import yfinance as yf

sys.path.append("Kronos")  # cloned by the workflow
from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

SYMBOL = "^NSEI"          # change to any Yahoo Finance ticker, e.g. "GC=F", "CL=F", "^NSEBANK"
NAME = "NIFTY 50"
CONTEXT = 400             # past candles fed to the model (max 512 for Kronos-small)
SHOW = 120                # candles shown on the chart
SAMPLES = 30              # Monte-Carlo samples used for the prediction band
OUT = "docs/data.json"

raw = yf.download(SYMBOL, period="3y", interval="1d", auto_adjust=False, progress=False)
raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
raw = raw.dropna(subset=["Open", "High", "Low", "Close"]).tail(CONTEXT)
raw.index = pd.to_datetime(raw.index).tz_localize(None)

df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].reset_index(drop=True)
x_ts = pd.Series(raw.index)
next_day = pd.bdate_range(raw.index[-1] + pd.Timedelta(days=1), periods=1)[0]  # ignores NSE holidays
y_ts = pd.Series([next_day])

tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)

runs = []
for i in range(SAMPLES):
    torch.manual_seed(i)
    p = predictor.predict(df=df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=1,
                          T=1.0, top_p=0.9, sample_count=1, verbose=False)
    runs.append(p[["open", "high", "low", "close"]].iloc[0].values)
runs = np.array(runs)
mean = runs.mean(axis=0)
lo, hi = np.percentile(runs[:, 3], [10, 90])
last_close = float(df["close"].iloc[-1])
prob_up = float((runs[:, 3] > last_close).mean())

candles = [
    {"time": d.strftime("%Y-%m-%d"), "open": round(float(r.open), 2), "high": round(float(r.high), 2),
     "low": round(float(r.low), 2), "close": round(float(r.close), 2)}
    for d, r in zip(raw.index[-SHOW:], df.tail(SHOW).itertuples())
]
out = {
    "symbol": NAME,
    "ticker": SYMBOL,
    "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "last_close": round(last_close, 2),
    "candles": candles,
    "prediction": {
        "time": next_day.strftime("%Y-%m-%d"),
        "open": round(float(mean[0]), 2), "high": round(float(mean[1]), 2),
        "low": round(float(mean[2]), 2), "close": round(float(mean[3]), 2),
        "close_p10": round(float(lo), 2), "close_p90": round(float(hi), 2),
        "prob_up": round(prob_up, 3),
        "samples": SAMPLES,
    },
}
with open(OUT, "w") as f:
    json.dump(out, f)
print(json.dumps(out["prediction"], indent=2))
