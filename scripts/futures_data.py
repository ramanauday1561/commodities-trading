"""NIFTY futures from Kite Connect (5 Nov 2026, asked by the user).

Usage: python scripts/futures_data.py update <dir>   (dir = a copy of the futures-data branch; needs that day's Kite login)
Why: Kite's historical data drops each option contract when it expires, so past intraday option prices cannot be
fetched; but it keeps NIFTY futures as one continuous series (the near-month contract, rolled at each expiry). Futures
cost far less to trade than options (no time decay; about 0.04% a round trip), so ideas that lost in options can be
retested on real futures prices (futures_study.py).
Kite gives the continuous series only as DAILY candles (5 Nov 2026: "invalid interval for continuous data" for 5-minute),
which is what a trade from the 09:15 open to the close with a stop on the day's high or low needs. 5-minute candles
exist only for contracts still trading, so the near-month contract's are recorded every day from now on.
Files: <dir>/nifty/daily.csv (date, open, high, low, close, volume, oi; the whole series, rewritten each run) and
<dir>/nifty-5m/<YYYY-MM>.csv (datetime, contract, open, high, low, close, volume, oi; session candles, finished days).
"""
import glob
import os
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
FIRST = date(2011, 1, 1)
DAILY = ["date", "open", "high", "low", "close", "volume", "oi"]
INTRA = ["datetime", "contract", "open", "high", "low", "close", "volume", "oi"]


def near_future(rows, today):
    """(instrument token, trading symbol) of the NIFTY futures contract nearest to expiry."""
    fut = [r for r in rows if r.get("name") == "NIFTY" and r.get("segment") == "NFO-FUT" and r.get("expiry", "") >= today.isoformat()]
    if not fut:
        return None
    r = min(fut, key=lambda r: r["expiry"])
    return int(r["instrument_token"]), r["tradingsymbol"]


def save_intraday(d, rows, contract):
    if not rows:
        return 0
    df = pd.DataFrame([(t.replace(tzinfo=None), contract, *x) for t, *x in rows], columns=INTRA)
    t = df["datetime"].dt.time
    df = df[(t >= time(9, 15)) & (t <= time(15, 25))]
    os.makedirs(os.path.join(d, "nifty-5m"), exist_ok=True)
    for month, g in df.groupby(df["datetime"].dt.strftime("%Y-%m")):
        path = os.path.join(d, "nifty-5m", f"{month}.csv")
        old = pd.read_csv(path, parse_dates=["datetime"]) if os.path.exists(path) else None
        out = (pd.concat([old, g]) if old is not None else g).drop_duplicates(["datetime", "contract"], keep="last").sort_values("datetime")
        out.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M")
    return int(df["datetime"].dt.date.nunique())


def update(d, now=None, history=None, instruments=None):
    """history(token, interval, start, end, continuous) -> Kite rows with oi."""
    import kite
    now = now or datetime.now(IST)
    s = kite.session()
    if not s:
        print("futures data: no Kite login today", flush=True)
        return None
    nf = near_future((instruments or (lambda: kite.instruments("NFO")))(), now.date())
    if not nf:
        print("futures data: no NIFTY futures contract found", flush=True)
        return None
    tok, sym = nf
    get = history or (lambda token, interval, a, b, cont: kite.history(s[0], s[1], token, interval, a, b,
                                                                        max_days=2000 if interval == "day" else 100,
                                                                        continuous=cont, oi=True))
    end_day = now.date() if now.time() >= time(15, 35) else now.date() - timedelta(days=1)    # finished days only
    out = {}
    daily = get(tok, "day", datetime.combine(FIRST, time(0, 0)), datetime.combine(end_day, time(23, 59, 59)), True)
    if daily:
        df = pd.DataFrame([(t.date().isoformat(), *x) for t, *x in daily], columns=DAILY).drop_duplicates("date", keep="last")
        os.makedirs(os.path.join(d, "nifty"), exist_ok=True)
        df.to_csv(os.path.join(d, "nifty", "daily.csv"), index=False)
        out["daily"] = f"{len(df)} days, {df['date'].iloc[0]} to {df['date'].iloc[-1]}"
    intra = get(tok, "5minute", datetime.combine(end_day - timedelta(days=99), time(0, 0)),
                datetime.combine(end_day, time(23, 59, 59)), False)
    out["5m"] = f"{save_intraday(d, intra, sym)} days of {sym}"
    print("futures data:", out, flush=True)
    return out


def load_daily(d):
    p = os.path.join(d, "nifty", "daily.csv")
    if not os.path.exists(p):
        return pd.DataFrame(columns=DAILY[1:])
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
    return df


if __name__ == "__main__":
    if sys.argv[1:2] == ["update"]:
        update(sys.argv[2])
