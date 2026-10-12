"""Overnight / global context features (US indices, volatility, FX, oil, gold, dollar, Asia).

Alignment rule: the feature row for trading day i uses the latest value dated on or before day i. For a forecast of
day i+1 that is information already public before that day opens (the US session of day i closes after the Indian
and European sessions of day i but before day i+1 opens), so nothing from the future leaks into the backtest.
"""
import re

import numpy as np
import pandas as pd
import yfinance as yf


def _name(ticker):
    return re.sub(r"[^a-z0-9]+", "", ticker.lower())


def load_exo(tickers, index):
    """DataFrame aligned to `index` (the instrument's trading days). Missing tickers are skipped, never fatal."""
    if not tickers:
        return None
    try:
        raw = yf.download(list(tickers), period="max", interval="1d", auto_adjust=True, progress=False, group_by="column")
        close = raw["Close"] if "Close" in raw else raw
        if isinstance(close, pd.Series):
            close = close.to_frame(tickers[0])
    except Exception as e:
        print("exo download failed:", repr(e))
        return None
    close.index = pd.to_datetime(close.index).tz_localize(None)
    feats = {}
    for t in tickers:
        if t not in close or close[t].dropna().empty:
            print("exo: no data for", t)
            continue
        s = close[t].dropna()
        n = _name(t)
        if "vix" in t.lower():
            feats[f"x_{n}_lvl"] = s
            feats[f"x_{n}_d5"] = s.diff(5)
        else:
            feats[f"x_{n}_r1"] = s.pct_change(1)
            feats[f"x_{n}_r5"] = s.pct_change(5)
    if not feats:
        return None
    out = pd.DataFrame(index=index)
    for name, s in feats.items():
        merged = s.reindex(s.index.union(index)).sort_index().ffill(limit=5)    # value dated on/before each day
        out[name] = merged.reindex(index).values
    return out.replace([np.inf, -np.inf], np.nan)
