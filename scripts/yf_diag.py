"""TEMPORARY diagnostic: what does Yahoo return for the latest daily candles right now?"""
import datetime as dt

import pandas as pd
import yfinance as yf

print("now UTC:", dt.datetime.utcnow(), "yfinance", yf.__version__)
for sym in ("^NSEI", "GC=F"):
    print("=" * 20, sym)
    def show(label, df):
        df = df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        print(f"--- {label}: rows={len(df)} index.tz={getattr(df.index, 'tz', None)}")
        print(df[["Open", "High", "Low", "Close", "Volume"]].tail(4).to_string())
    for label, fn in [
        ("download max 1d", lambda: yf.download(sym, period="max", interval="1d", auto_adjust=False, progress=False)),
        ("download 1mo 1d", lambda: yf.download(sym, period="1mo", interval="1d", auto_adjust=False, progress=False)),
        ("download start/end", lambda: yf.download(sym, start="2026-10-01", end="2026-10-16", interval="1d", auto_adjust=False, progress=False)),
        ("Ticker.history max", lambda: yf.Ticker(sym).history(period="max", interval="1d", auto_adjust=False)),
        ("Ticker.history 5d", lambda: yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=False)),
    ]:
        try:
            show(label, fn())
        except Exception as e:
            print("---", label, "FAILED", repr(e))
