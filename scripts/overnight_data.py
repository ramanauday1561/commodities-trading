"""Years of hourly prices for the 09:15 signal's overnight inputs, from Dukascopy's free datafeed (28 Oct 2026).

Yahoo keeps only 2 years of hourly candles, so the from-open signal could be tested on ~65 trades. Dukascopy publishes
hourly candles for index CFDs, one LZMA file per month, back to 2015 (checked with experiment mode "dukaprobe"):
S&P 500 (ES), Nasdaq 100 (NQ), Nikkei 225 and Hang Seng. KOSPI and USD/INR are not there. Its server throttles hard
(HTTP 503), so files are fetched slowly with retries, within a time budget, and the run is repeated until all months
are in. Months already saved are not fetched again (the current month always is).
Usage: python scripts/overnight_data.py <key> <dir> [minutes]   key: es | nq | nikkei | hangseng | india
Files: <dir>/<key>/<YYYY-MM>.csv with end (UTC, the hour candle's end) and close.
"""
import lzma
import os
import struct
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

SYMBOLS = {"es": "USA500IDXUSD", "nq": "USATECHIDXUSD", "nikkei": "JPNIDXJPY", "hangseng": "HKGIDXHKD",
           "india": "INDIDXUSD"}     # India 50 CFD: follows SGX / GIFT Nifty, so it trades while NSE is closed
URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/BID_candles_hour_1.bi5"   # month counted from 0
FIRST = date(2015, 1, 1)
SCALE = 1000.0                     # index CFD prices are stored in thousandths
HEAD = {"User-Agent": "Mozilla/5.0 (compatible; commodities-trading/1.0)"}


def parse(raw, y, m):
    """[(end UTC, close)] from a decompressed month of hourly candles; flat closed-market hours are dropped."""
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    out, last = [], None
    for i in range(0, len(raw) - 23, 24):
        t, o, c, lo, hi, vol = struct.unpack(">5if", raw[i:i + 24])
        if vol <= 0 and o == c == lo == hi and c == last:
            continue
        out.append((start + timedelta(seconds=t + 3600), c / SCALE))
        last = c
    return out


def fetch(sym, y, m, tries=6):
    for k in range(tries):
        try:
            r = requests.get(URL.format(sym=sym, y=y, m=m - 1), headers=HEAD, timeout=60)
            if r.status_code == 200:
                return parse(lzma.decompress(r.content), y, m) if r.content else []
            if r.status_code == 404:
                return None
        except (requests.RequestException, lzma.LZMAError):
            pass
        time.sleep(10 * (k + 1))
    raise TimeoutError("throttled")


def months(today=None):
    today = today or datetime.now(timezone.utc).date()
    y, m = FIRST.year, FIRST.month
    while (y, m) <= (today.year, today.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def update(key, d, minutes=50, get=fetch, today=None, part=0, parts=1):
    """Fetch the missing months within the time budget; returns (saved, missing, skipped as not published). With
    parts > 1 only every parts-th month (from `part`), so several runners can share one market."""
    folder = os.path.join(d, key)
    os.makedirs(folder, exist_ok=True)
    stop = time.time() + minutes * 60
    today = today or datetime.now(timezone.utc).date()
    saved = missing = absent = 0
    for n, (y, m) in enumerate(months(today)):
        if n % parts != part:
            continue
        path = os.path.join(folder, f"{y}-{m:02d}.csv")
        current = (y, m) == (today.year, today.month)
        if os.path.exists(path) and not current:
            continue
        if time.time() > stop:
            missing += 1
            continue
        try:
            rows = get(SYMBOLS[key], y, m)
        except TimeoutError:
            missing += 1
            continue
        if rows is None:
            absent += 1
            continue
        with open(path, "w") as f:
            f.write("end,close\n" + "".join(f"{t:%Y-%m-%d %H:%M},{c:.2f}\n" for t, c in rows))
        saved += 1
        time.sleep(1.5)
    print(f"overnight {key}: saved {saved} months, {missing} still missing, {absent} not published", flush=True)
    return saved, missing, absent


def load(d, key):
    """The hourly closes as a Series indexed by candle end (UTC), like todaycall.hourly()."""
    import glob
    import pandas as pd
    files = sorted(glob.glob(os.path.join(d, key, "*.csv")))
    if not files:
        return pd.Series(dtype=float)
    df = pd.concat(pd.read_csv(f) for f in files)
    return pd.Series(df["close"].values, index=pd.to_datetime(df["end"]).dt.tz_localize("UTC")).sort_index()


if __name__ == "__main__":
    update(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 50,
           part=int(sys.argv[4]) if len(sys.argv) > 4 else 0, parts=int(sys.argv[5]) if len(sys.argv) > 5 else 1)
