"""NIFTY futures, 5-minute candles joined across expiries, from Kite Connect (5 Nov 2026, asked by the user).

Usage: python scripts/futures_data.py update <dir>   (dir = a copy of the futures-data branch; needs that day's Kite login)
Why: Kite's historical data drops each option contract when it expires, so past intraday option prices cannot be
fetched; but it keeps NIFTY futures as one continuous series (the near-month contract, rolled at each expiry). Futures
cost far less to trade than options (no time decay; about 0.04% a round trip), so ideas that lost in options can be
retested on real futures prices (futures_study.py).
Files: <dir>/nifty/<YYYY-MM>.csv with datetime (IST, the candle's start), open, high, low, close, volume, oi; session
candles only (09:15 ... 15:25), finished days only. The first run goes back to 2015 (or as far as Kite has), later
runs add the days since the last stored one.
"""
import glob
import os
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
FIRST = date(2015, 1, 1)
COLS = ["datetime", "open", "high", "low", "close", "volume", "oi"]


def near_future(rows, today):
    """The NIFTY futures contract nearest to expiry (its token reaches the continuous series)."""
    fut = [r for r in rows if r.get("name") == "NIFTY" and r.get("segment") == "NFO-FUT" and r.get("expiry", "") >= today.isoformat()]
    if not fut:
        return None
    return int(min(fut, key=lambda r: r["expiry"])["instrument_token"])


def last_day(d, name="nifty"):
    files = sorted(glob.glob(os.path.join(d, name, "*.csv")))
    if not files:
        return None
    return pd.to_datetime(pd.read_csv(files[-1], usecols=["datetime"])["datetime"]).dt.date.max()


def save(d, rows, name="nifty"):
    """Add candles (session only), month files, one row per time."""
    if not rows:
        return 0
    df = pd.DataFrame(rows, columns=COLS)
    df["datetime"] = pd.to_datetime(df["datetime"])
    t = df["datetime"].dt.time
    df = df[(t >= time(9, 15)) & (t <= time(15, 25))]
    os.makedirs(os.path.join(d, name), exist_ok=True)
    for month, g in df.groupby(df["datetime"].dt.strftime("%Y-%m")):
        path = os.path.join(d, name, f"{month}.csv")
        old = pd.read_csv(path, parse_dates=["datetime"]) if os.path.exists(path) else None
        out = (pd.concat([old, g]) if old is not None else g).drop_duplicates("datetime", keep="last").sort_values("datetime")
        out.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M")
    return int(df["datetime"].dt.date.nunique())


def update(d, now=None, history=None, instruments=None):
    import kite
    now = now or datetime.now(IST)
    s = kite.session()
    if not s:
        print("futures data: no Kite login today", flush=True)
        return None
    tok = near_future((instruments or (lambda: kite.instruments("NFO")))(), now.date())
    if not tok:
        print("futures data: no NIFTY futures contract found", flush=True)
        return None
    have = last_day(d)
    start = (have + timedelta(days=1)) if have else FIRST
    end = now.date() if now.time() >= time(15, 35) else now.date() - timedelta(days=1)    # finished days only
    if start > end:
        print(f"futures data: up to date ({have})", flush=True)
        return 0
    get = history or (lambda a, b: kite.history(s[0], s[1], tok, "5minute", a, b, max_days=100, continuous=True, oi=True))
    rows = []
    a = datetime.combine(start, time(0, 0))
    while a.date() <= end:                         # one year at a time, so a failure keeps what came before
        b = min(datetime.combine(date(a.year, 12, 31), time(23, 59, 59)), datetime.combine(end, time(23, 59, 59)))
        try:
            got = get(a, b)
        except Exception as e:
            print(f"futures data: {a:%Y} failed ({e})", flush=True)
            got = []
        rows += [(r[0].replace(tzinfo=None), r[1], r[2], r[3], r[4], r[5], r[6] if len(r) > 6 else 0.0) for r in got]
        a = b + timedelta(seconds=1)
    n = save(d, rows)
    files = sorted(glob.glob(os.path.join(d, "nifty", "*.csv")))
    print(f"futures data: {n} days added; stored {os.path.basename(files[0])[:7] if files else '-'} to {last_day(d)}", flush=True)
    return n


if __name__ == "__main__":
    if sys.argv[1:2] == ["update"]:
        update(sys.argv[2])
