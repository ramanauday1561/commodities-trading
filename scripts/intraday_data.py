"""Our own history of 5-minute candles: NIFTY 50, Bank NIFTY and India VIX, kept on the intraday-data branch.

Usage: python scripts/intraday_data.py update <dir>   (dir = a copy of the intraday-data branch; run after the close)
Asked by the user on 27 Oct 2026. Yahoo serves only the last ~60 days of 5-minute candles, too few to test intraday
rules (the first intraday study had 60 days). Two sources:
  - Kaggle "debashis74017/nifty-50-minute-data" (CC0, public domain; downloads without a key): 5-minute candles from
    9 Jan 2015 to 18 May 2026. Checked on 27 Oct 2026: 2,800 days, 75 candles a day, the last candle's close within
    0.05% of Yahoo's daily close on a typical day (NSE's official close is a 30-minute average, so they differ a little).
    Loaded once (kaggle-loaded.txt marks it done).
  - Yahoo, every run: the days it has that we do not (finished days only), so the history keeps growing. Days already
    stored are never changed. 19 May - ~30 Jul 2026 is missing in both (Kaggle ends, Yahoo's 60 days start later).
Files: <dir>/<name>/<YYYY-MM>.csv with datetime (IST, the candle's start), open, high, low, close; one file a month so
a day's update changes one small file. Session candles only (09:15 ... 15:25).
"""
import glob
import io
import os
import sys
import zipfile
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
KAGGLE = "https://www.kaggle.com/api/v1/datasets/download/debashis74017/nifty-50-minute-data"
SERIES = {"nifty": ("^NSEI", "NIFTY 50_5minute.csv"), "banknifty": ("^NSEBANK", "NIFTY BANK_5minute.csv"),
          "vix": ("^INDIAVIX", "INDIA VIX_5minute.csv")}
FIRST, LAST = time(9, 15), time(15, 25)
DONE_AFTER = time(15, 35)                     # today's candles count as finished after this
COLS = ["datetime", "open", "high", "low", "close"]


def session(df):
    """Only the 09:15 ... 15:25 candles, sorted, one per time, prices rounded to 2 decimals."""
    df = df[COLS].copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    t = df["datetime"].dt.time
    df = df[(t >= FIRST) & (t <= LAST)].dropna()
    df = df.drop_duplicates("datetime", keep="last").sort_values("datetime")
    df[COLS[1:]] = df[COLS[1:]].astype(float).round(2)
    return df.reset_index(drop=True)


def stored_days(d, name):
    days = set()
    for f in glob.glob(os.path.join(d, name, "*.csv")):
        days |= set(pd.to_datetime(pd.read_csv(f, usecols=["datetime"])["datetime"]).dt.date)
    return days


def add(d, name, df):
    """Add the days of df that are not stored yet; returns how many days were added."""
    df = session(df)
    if df.empty:
        return 0
    have = stored_days(d, name)
    df = df[~df["datetime"].dt.date.isin(have)]
    if df.empty:
        return 0
    os.makedirs(os.path.join(d, name), exist_ok=True)
    for month, g in df.groupby(df["datetime"].dt.strftime("%Y-%m")):
        path = os.path.join(d, name, f"{month}.csv")
        old = pd.read_csv(path, parse_dates=["datetime"]) if os.path.exists(path) else None
        out = session(pd.concat([old, g]) if old is not None else g)
        out.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M")
    return int(df["datetime"].dt.date.nunique())


def from_kaggle(d, get=None):
    """Load the Kaggle files once (the zip is ~850 MB; only three files are read from it)."""
    if get is None:
        import requests
        get = lambda: requests.get(KAGGLE, headers={"User-Agent": "Mozilla/5.0 (compatible; commodities-trading/1.0)"},
                                   timeout=900).content
    z = zipfile.ZipFile(io.BytesIO(get()))
    names = {os.path.basename(n): n for n in z.namelist()}
    out = {}
    for name, (_, fname) in SERIES.items():
        if fname in names:
            df = pd.read_csv(z.open(names[fname])).rename(columns={"date": "datetime"})
            out[name] = add(d, name, df)
    return out


def yahoo(symbol):
    import yfinance as yf
    raw = yf.download(symbol, period="60d", interval="5m", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    idx = pd.DatetimeIndex(raw.index)
    idx = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert(IST).tz_localize(None)
    return pd.DataFrame({"datetime": idx, "open": raw["Open"].values, "high": raw["High"].values,
                         "low": raw["Low"].values, "close": raw["Close"].values})


def finished(df, now):
    """Drop today's candles until the session is over."""
    if now.time() >= DONE_AFTER:
        return df
    return df[pd.to_datetime(df["datetime"]).dt.date < now.date()]


def update(d, now=None, get_yahoo=yahoo, get_kaggle=None):
    now = now or datetime.now(IST)
    out = {}
    mark = os.path.join(d, "kaggle-loaded.txt")
    if not os.path.exists(mark):                    # once; a failed download is tried again on the next run
        try:
            out["kaggle"] = from_kaggle(d, get_kaggle)
            os.makedirs(d, exist_ok=True)
            open(mark, "w").write(f"{KAGGLE}\nloaded {now:%Y-%m-%d %H:%M} IST: {out['kaggle']}\n")
        except Exception as e:
            out["kaggle"] = f"failed: {type(e).__name__}"
    for name, (sym, _) in SERIES.items():
        try:
            out[name] = add(d, name, finished(get_yahoo(sym), now))
        except Exception as e:                      # one series failing must not stop the others
            out[name] = f"failed: {type(e).__name__}"
    for name in SERIES:
        days = sorted(stored_days(d, name))
        if days:
            out[f"{name}_days"] = f"{len(days)} ({days[0]} to {days[-1]})"
    print("intraday data", out, flush=True)
    return out


def load(d, name="nifty"):
    """{date: DataFrame of that day's candles (index = IST datetime; Open, High, Low, Close)}."""
    files = sorted(glob.glob(os.path.join(d, name, "*.csv")))
    if not files:
        return {}
    df = pd.concat(pd.read_csv(f, parse_dates=["datetime"]) for f in files).set_index("datetime")
    df = df.rename(columns=str.title)
    return {k: g for k, g in df.groupby(df.index.date)}


if __name__ == "__main__":
    if sys.argv[1:2] == ["update"]:
        update(sys.argv[2])
