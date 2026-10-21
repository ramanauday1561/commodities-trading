"""Hourly candles for the chart's "1H" view (display only: the forecasts stay daily).

Usage: python scripts/hourly.py <data_dir> [key ...]   (all instruments when no key is given)
Writes <data_dir>/hourly-<key>.json with the last ~3 months of Yahoo's 1-hour bars. Bar times are the bar START in
Indian time (shifted so the chart's axis reads IST). Futures bars are Yahoo's continuous contract, unadjusted, so a jump
can appear when it switches contracts. A market Yahoo cannot serve keeps its previous file.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

IST_OFFSET = 19800          # seconds; the chart shows times as UTC, so shift them to read as IST
PERIOD = "3mo"


def bars(ticker, period=PERIOD):
    raw = yf.download(ticker, period=period, interval="1h", auto_adjust=False, progress=False)
    if raw is None or not len(raw):
        return []
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    idx = pd.to_datetime(raw.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return to_rows(idx, raw)


def to_rows(idx, raw):
    out = []
    for t, (_, r) in zip(idx, raw.iterrows()):
        o, h, l, c = (round(float(r[k]), 2) for k in ("Open", "High", "Low", "Close"))
        out.append({"time": int(t.timestamp()) + IST_OFFSET, "open": o, "high": max(h, o, c), "low": min(l, o, c), "close": c})
    return out


def main(data_dir, keys=None):
    for inst in json.load(open("scripts/instruments.json")):
        if keys and inst["key"] not in keys:
            continue
        try:
            rows = bars(inst["ticker"])
        except Exception as e:                          # never block the rest of the run
            print(f"{inst['key']}: hourly bars failed ({e!r})")
            continue
        if not rows:
            print(f"{inst['key']}: no hourly bars")
            continue
        out = {"key": inst["key"], "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "interval": "1h", "tz": "IST", "bars": rows}
        json.dump(out, open(os.path.join(data_dir, f"hourly-{inst['key']}.json"), "w"), separators=(",", ":"))
        print(f"{inst['key']}: {len(rows)} hourly bars")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or None)
