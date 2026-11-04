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

Kite Connect (4 Nov 2026, kite.py): after the morning login, the update takes Kite's candles for the last 100 days and
replaces the Yahoo days among them (Yahoo's bars froze before the close on most days since Aug 2026), and fills the
days nobody had. "repair" does the same back to 19 May 2026 (the 19 May - 30 Jul gap included). <dir>/<name>/
sources.json says where each day came from (kaggle, yahoo, kite; days without an entry: kaggle up to 18 May 2026,
yahoo after); Kite days skip the frozen-feed check when read.
Usage: python scripts/intraday_data.py repair <dir> [YYYY-MM-DD]   (needs that day's Kite login)
"""
import json
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
# 2 Nov 2026: since Aug 2026 Yahoo's 5-minute bars stop moving before the close on most days (the 15:20 bar on 98% of
# days, the 15:15 on 75%; never in the Kaggle years): open = high = low = close = the previous close, then the 15:25
# bar jumps to NSE's official close. From FREEZE_FROM on, a bar with no range at the previous bar's close is a paused
# feed, not a price, and is left out when candles are read (the files keep what was downloaded).
FREEZE_FROM, FROZEN_PCT = time(15, 0), 0.01
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


def frozen(g):
    """Boolean mask of the paused-feed bars in one day's candles (Open, High, Low, Close; IST index): from FREEZE_FROM,
    a range and a move from the previous close both within FROZEN_PCT of the price. 0.01% (about 2 NIFTY points)
    caught 117 bars since Aug 2026 and none in the 11 Kaggle years (2 Nov 2026; 0.02% would have caught 6 real ones)."""
    tol = g["Close"] * FROZEN_PCT / 100
    flat = ((g["High"] - g["Low"]) <= tol) & ((g["Close"] - g["Close"].shift(1)).abs() <= tol)
    return flat & (g.index.time >= FREEZE_FROM)


def drop_frozen(g):
    return g if g is None or len(g) < 2 else g[~frozen(g)]


KAGGLE_LAST = "2026-05-18"
REPAIR_FROM = "2026-05-19"


def sources(d, name):
    """{date iso: "kaggle" / "yahoo" / "kite"} for every stored day."""
    p = os.path.join(d, name, "sources.json")
    known = json.load(open(p)) if os.path.exists(p) else {}
    return {x.isoformat(): known.get(x.isoformat(), "kaggle" if x.isoformat() <= KAGGLE_LAST else "yahoo")
            for x in stored_days(d, name)}


def _save_sources(d, name, src):
    os.makedirs(os.path.join(d, name), exist_ok=True)
    json.dump(dict(sorted(src.items())), open(os.path.join(d, name, "sources.json"), "w"), indent=0)


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


def replace(d, name, df, source="kite"):
    """Store df's days, replacing the same days already stored unless they came from Kaggle or Kite; returns
    (added, replaced, frozen bars gone) for the days written."""
    df = session(df)
    if df.empty:
        return 0, 0, 0
    src = sources(d, name)
    days = sorted(set(df["datetime"].dt.date))
    write = [x for x in days if src.get(x.isoformat()) not in ("kaggle", "kite")]
    if not write:
        return 0, 0, 0
    old = load(d, name, raw=True)
    gone = sum(int(frozen(old[x]).sum()) for x in write if x in old)
    added = sum(1 for x in write if x.isoformat() not in src)
    df = df[df["datetime"].dt.date.isin(write)]
    os.makedirs(os.path.join(d, name), exist_ok=True)
    for month, g in df.groupby(df["datetime"].dt.strftime("%Y-%m")):
        path = os.path.join(d, name, f"{month}.csv")
        kept = None
        if os.path.exists(path):
            kept = pd.read_csv(path, parse_dates=["datetime"])
            kept = kept[~kept["datetime"].dt.date.isin(write)]
        session(pd.concat([kept, g]) if kept is not None else g).to_csv(path, index=False, date_format="%Y-%m-%d %H:%M")
    src.update({x.isoformat(): source for x in write})
    _save_sources(d, name, src)
    return added, len(write) - added, gone


def kite_series(symbol, start, end):
    """Kite's 5-minute candles from start to end (dates) as datetime (IST, naive), open, high, low, close; or None."""
    import kite
    import prices
    s = kite.session()
    if not s:
        return None
    rows = kite.history(s[0], s[1], prices.KITE[symbol], "5minute", datetime.combine(start, time(0, 0)),
                        datetime.combine(end, time(23, 59, 59)), max_days=100)
    return pd.DataFrame([(t.replace(tzinfo=None), o, h, lo, c) for t, o, h, lo, c, _ in rows], columns=COLS)


def repair(d, since=REPAIR_FROM, now=None, get=kite_series):
    """Kite's candles for every day since `since` (finished days), replacing Yahoo's and filling the gaps."""
    from datetime import date as _date, timedelta
    now = now or datetime.now(IST)
    start = _date.fromisoformat(since)
    out = {}
    for name, (sym, _) in SERIES.items():
        df = get(sym, start, now.date())
        if df is None:
            out[name] = "no Kite login today"
            continue
        out[name] = dict(zip(("added", "replaced", "frozen_bars_gone"), replace(d, name, finished(df, now))))
    print("intraday repair", out, flush=True)
    return out


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


def update(d, now=None, get_yahoo=yahoo, get_kaggle=None, get_kite=kite_series):
    """Kaggle once; then Kite's last 100 days after the morning login (replacing Yahoo days, filling gaps), else
    Yahoo's 60 days (new days only)."""
    from datetime import timedelta
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
            k = get_kite(sym, now.date() - timedelta(days=99), now.date()) if get_kite else None
        except Exception as e:                      # Kite down: Yahoo below
            print(f"intraday data: Kite failed for {name} ({e})", flush=True)
            k = None
        try:
            if k is not None and len(k):
                out[name] = dict(zip(("kite_added", "kite_replaced", "frozen_bars_gone"), replace(d, name, finished(k, now))))
            else:
                before = stored_days(d, name)
                out[name] = add(d, name, finished(get_yahoo(sym), now))
                new = stored_days(d, name) - before
                if new:
                    src = sources(d, name)
                    src.update({x.isoformat(): "yahoo" for x in new})
                    _save_sources(d, name, src)
        except Exception as e:                      # one series failing must not stop the others
            out[name] = f"failed: {type(e).__name__}"
    for name in SERIES:
        days = sorted(stored_days(d, name))
        if days:
            out[f"{name}_days"] = f"{len(days)} ({days[0]} to {days[-1]})"
    print("intraday data", out, flush=True)
    return out


def load(d, name="nifty", raw=False):
    """{date: DataFrame of that day's candles (index = IST datetime; Open, High, Low, Close)}; Yahoo's paused-feed
    bars left out (not on Kite or Kaggle days; raw=True keeps everything)."""
    files = sorted(glob.glob(os.path.join(d, name, "*.csv")))
    if not files:
        return {}
    df = pd.concat(pd.read_csv(f, parse_dates=["datetime"]) for f in files).set_index("datetime")
    df = df.rename(columns=str.title)
    p = os.path.join(d, name, "sources.json")
    kite_days = {k for k, v in (json.load(open(p)) if os.path.exists(p) else {}).items() if v == "kite"}
    return {k: g if raw or k.isoformat() in kite_days else drop_frozen(g) for k, g in df.groupby(df.index.date)}


if __name__ == "__main__":
    if sys.argv[1:2] == ["update"]:
        update(sys.argv[2])
    if sys.argv[1:2] == ["repair"]:
        repair(sys.argv[2], *(sys.argv[3:4] or []))
