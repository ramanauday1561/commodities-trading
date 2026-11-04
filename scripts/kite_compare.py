"""Kite vs Yahoo, side by side (experiment mode "kitecompare", 4 Nov 2026): the check behind prices.py.

Usage: python scripts/kite_compare.py   (needs today's Kite login: KITE_API_KEY, KITE_API_SECRET, KITE_DIR)
For NIFTY 50, NIFTY BANK and India VIX at each interval the app uses: rows and last candle from each source, and on
the candles both have, how far apart the closes are (mean and largest, %), plus Yahoo's frozen 5-minute bars
(intraday_data.frozen) that Kite has as real candles.
"""
import sys
from datetime import datetime

import pandas as pd

import kite
import prices

CASES = [("5m", "5d"), ("5m", "60d"), ("15m", "60d"), ("1h", "730d"), ("1d", "5y"), ("1d", "max")]


def compare(symbol, interval, period, now):
    k = prices._kite(symbol, prices._days(period), interval, now)
    y = prices._yahoo(symbol, period, interval)
    if interval != "1d" and len(y):
        idx = pd.DatetimeIndex(y.index)
        y.index = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert(prices.IST)
    elif len(y):
        y.index = pd.to_datetime(y.index).tz_localize(None).normalize()
    line = f"{prices.NAMES[symbol]:10} {interval:>3} {period:>4}: kite {0 if k is None else len(k):6} rows"
    line += f" (last {str(k.index[-1])[:16]})" if k is not None and len(k) else ""
    line += f" | yahoo {len(y):6} rows" + (f" (last {str(y.index[-1])[:16]})" if len(y) else "")
    if k is not None and len(k) and len(y):
        both = k.index.intersection(y.index)
        if len(both):
            d = (k.loc[both, "Close"] / y.loc[both, "Close"] - 1).abs() * 100
            line += f" | {len(both)} shared: close diff mean {d.mean():.3f}% max {d.max():.3f}% ({str(d.idxmax())[:16]})"
        if interval == "5m":
            from intraday_data import frozen
            g = y.copy()
            g.index = g.index.tz_localize(None)
            fz = frozen(g[["Open", "High", "Low", "Close"]])
            line += f" | yahoo frozen bars {int(fz.sum())}"
    print(line, flush=True)


def main():
    now = datetime.now(prices.IST)
    if not kite.session():
        print("no Kite login today: log in on the Kite page first", flush=True)
        return 1
    for symbol in prices.KITE:
        for interval, period in CASES:
            try:
                compare(symbol, interval, period, now)
            except Exception as e:
                print(f"{prices.NAMES[symbol]} {interval} {period}: failed ({e!r})", flush=True)
    print("\nprices.download as the app calls it:", flush=True)
    for symbol, period, interval in [("^NSEI", "1d", "5m"), ("^NSEI", "5d", "15m"), ("^NSEI", "730d", "1h"),
                                     ("^NSEI", "5y", "1d"), ("^NSEI", "max", "1d"), ("^INDIAVIX", "5d", "5m"), ("ES=F", "5d", "1h")]:
        df = prices.download(symbol, period=period, interval=interval)
        print(f"  {symbol} {period} {interval}: {prices.source_of(df)}, {len(df)} rows, last {str(df.index[-1])[:16] if len(df) else '-'}",
              flush=True)
    print(prices.save_health("health-check.json"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
