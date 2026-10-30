"""Our own history of NIFTY option prices, from NSE's free daily F&O bhavcopy (31 Oct 2026).

Usage: python scripts/option_data.py update <dir> [minutes] [part] [parts]   (dir = a copy of an options-data branch)
Why: every rupee figure in the studies so far assumed an at-the-money option moves half as much as NIFTY, minus a fixed
cost, with no time decay; the user trades options. The bhavcopy has each contract's open, high, low and close for the
day, so trades from the 09:15 open to the close can be priced on real premiums.
Two formats: up to 5 Jul 2024 fo<DDMONYYYY>bhav.csv.zip, from 8 Jul 2024 the UDiFF BhavCopy_NSE_FO_..._F_0000.csv.zip
(the put-call-ratio probe of 26 Oct 2026 read both from a GitHub runner).
Kept: NIFTY index options of the nearest 3 expiries, strikes within 6% of the near-month NIFTY future's close, that
traded that day; plus that future's close (fut). Files: <dir>/nifty/<YYYY-MM>.csv; <dir>/missing.txt lists sessions
NSE had no file for. With parts > 1, only every parts-th month (from part), so 4 runners can share the years, each
saving to its own branch (options-data-p0 ... p3).
"""
import glob
import io
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pandas as pd

from calendars import is_session

HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
FIRST = date(2015, 1, 1)
COLS = ["d", "expiry", "strike", "type", "open", "high", "low", "close", "settle", "oi", "volume", "fut"]
EXPIRIES, BAND = 3, 0.06


def url(d):
    if d >= date(2024, 7, 8):
        return f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    mon = f"{d:%b}".upper()
    return f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{d:%Y}/{mon}/fo{d:%d}{mon}{d:%Y}bhav.csv.zip"


def parse(raw, d):
    """NIFTY options near the money from one day's bhavcopy (either format), as COLS."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(z.open(z.namelist()[0]), low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    if "TckrSymb" in df.columns:                                       # UDiFF, from 8 Jul 2024
        nifty = df[df["TckrSymb"].astype(str).str.strip() == "NIFTY"]
        fut = nifty[nifty["FinInstrmTp"].astype(str).str.strip() == "IDF"]
        o = nifty[nifty["FinInstrmTp"].astype(str).str.strip() == "IDO"]
        o = pd.DataFrame({"expiry": pd.to_datetime(o["XpryDt"]).dt.date, "strike": o["StrkPric"].astype(float),
                          "type": o["OptnTp"].astype(str).str.strip(), "open": o["OpnPric"], "high": o["HghPric"],
                          "low": o["LwPric"], "close": o["ClsPric"], "settle": o["SttlmPric"], "oi": o["OpnIntrst"],
                          "volume": o["TtlTradgVol"]})
        fx = pd.DataFrame({"expiry": pd.to_datetime(fut["XpryDt"]).dt.date, "close": fut["ClsPric"].astype(float)})
    else:                                                              # the old format
        sym, ins = df["SYMBOL"].astype(str).str.strip(), df["INSTRUMENT"].astype(str).str.strip()
        fut, o = df[(sym == "NIFTY") & (ins == "FUTIDX")], df[(sym == "NIFTY") & (ins == "OPTIDX")]
        o = pd.DataFrame({"expiry": pd.to_datetime(o["EXPIRY_DT"].astype(str).str.strip(), format="%d-%b-%Y").dt.date,
                          "strike": o["STRIKE_PR"].astype(float), "type": o["OPTION_TYP"].astype(str).str.strip(),
                          "open": o["OPEN"], "high": o["HIGH"], "low": o["LOW"], "close": o["CLOSE"],
                          "settle": o["SETTLE_PR"], "oi": o["OPEN_INT"], "volume": o["CONTRACTS"]})
        fx = pd.DataFrame({"expiry": pd.to_datetime(fut["EXPIRY_DT"].astype(str).str.strip(), format="%d-%b-%Y").dt.date,
                           "close": fut["CLOSE"].astype(float)})
    if fx.empty or o.empty:
        return pd.DataFrame(columns=COLS)
    ref = float(fx.sort_values("expiry")["close"].iloc[0])
    keep = sorted(e for e in o["expiry"].unique() if e >= d)[:EXPIRIES]
    o = o[o["expiry"].isin(keep) & ((o["strike"] / ref - 1).abs() <= BAND) & (o["volume"].astype(float) > 0)
          & (o["open"].astype(float) > 0)].copy()
    o["d"], o["fut"] = d, ref
    return o[COLS].sort_values(["expiry", "type", "strike"]).reset_index(drop=True)


def months(first, last):
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def stored(d):
    """Sessions already done: in a month file, or listed as missing."""
    done = set()
    for f in glob.glob(os.path.join(d, "nifty", "*.csv")):
        done |= set(pd.read_csv(f, usecols=["d"])["d"].astype(str))
    p = os.path.join(d, "missing.txt")
    if os.path.exists(p):
        done |= set(open(p).read().split())
    return done


def fetch(day, session):
    """(day, DataFrame) or (day, None) when NSE has no file, or (day, "error")."""
    for k in range(3):
        try:
            r = session.get(url(day), headers=HEAD, timeout=40)
            if r.status_code == 404:
                return day, None
            if r.status_code == 200:
                return day, parse(r.content, day)
        except Exception:
            pass
        time.sleep(2 * (k + 1))
    return day, "error"


def update(d, minutes=50, part=0, parts=1, today=None, get=None):
    import requests
    today = today or (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    stop = time.time() + minutes * 60
    os.makedirs(os.path.join(d, "nifty"), exist_ok=True)
    done, counts = stored(d), {"saved": 0, "missing": 0, "errors": 0}
    s = requests.Session()
    try:
        s.get("https://www.nseindia.com/", headers=HEAD, timeout=20)
    except Exception:
        pass
    get = get or (lambda day: fetch(day, s))
    for n, (y, m) in enumerate(months(FIRST, today)):
        if n % parts != part or time.time() > stop:
            continue
        days = [date(y, m, k) for k in range(1, 32) if _valid(y, m, k)]
        days = [x for x in days if x < today and is_session(x, "XBOM") and x.isoformat() not in done]
        if not days:
            continue
        with ThreadPoolExecutor(4) as ex:
            got = list(ex.map(get, days))
        frames = [g for _, g in got if isinstance(g, pd.DataFrame) and len(g)]
        gone = [x.isoformat() for x, g in got if g is None or (isinstance(g, pd.DataFrame) and g.empty)]
        counts["errors"] += sum(1 for _, g in got if isinstance(g, str))
        if frames:
            path = os.path.join(d, "nifty", f"{y}-{m:02d}.csv")
            old = [pd.read_csv(path)] if os.path.exists(path) else []
            pd.concat(old + frames).drop_duplicates(["d", "expiry", "strike", "type"]).to_csv(path, index=False)
            counts["saved"] += len(frames)
        if gone:
            open(os.path.join(d, "missing.txt"), "a").write("\n".join(gone) + "\n")
            counts["missing"] += len(gone)
    have = sorted(stored(d))
    print(f"options part {part}/{parts}: {counts}, {len(have)} sessions done "
          f"({have[0] if have else '-'} to {have[-1] if have else '-'})", flush=True)
    return counts


def _valid(y, m, k):
    try:
        date(y, m, k)
        return True
    except ValueError:
        return False


def load(dirs):
    """Every stored row from these copies (the four part branches), with dates parsed."""
    files = [f for d in dirs for f in glob.glob(os.path.join(d, "nifty", "*.csv"))]
    if not files:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(pd.read_csv(f) for f in files)
    df["d"], df["expiry"] = pd.to_datetime(df["d"]).dt.date, pd.to_datetime(df["expiry"]).dt.date
    return df.drop_duplicates(["d", "expiry", "strike", "type"]).reset_index(drop=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["update"]:
        a = sys.argv[2:]
        update(a[0], float(a[1]) if len(a) > 1 else 50, int(a[2]) if len(a) > 2 else 0, int(a[3]) if len(a) > 3 else 1)
