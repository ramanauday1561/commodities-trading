"""Indian index prices for every script: Kite Connect first, Yahoo as the backup, with checks (4 Nov 2026).

Usage: import prices; prices.download("^NSEI", period="5d", interval="15m")   (in place of yf.download)
Kite (kite.py) needs the morning login (docs/kite.html); without one, or when Kite fails or looks stale, the same call
goes to Yahoo. NIFTY 50, NIFTY BANK and India VIX come from Kite; every other symbol (US futures, Nikkei, gold...) is
Yahoo's as before. The frame looks like yf.download's: columns Open, High, Low, Close, Adj Close, Volume; intraday
indexed by IST time (aware), daily by date (naive). df.attrs["source"] says "kite", "yahoo" or "kite+yahoo" (a long
daily history from Yahoo with Kite's official recent sessions on top).

Checks, written to $DATA_HEALTH (docs/data/data-health.json) for the Status page:
- stale: during the session, intraday candles more than 15 minutes behind (3 Nov 2026: Yahoo's 5-minute bars froze
  from 15:10) -> the other source is tried and the fresher one kept;
- a missing last session in daily candles (3 Nov 2026: at 02:09 Yahoo's daily series still ended on Friday);
- Kite failures (a lapsed login, the API down): Yahoo is used and the reason recorded.
"""
import atexit
import json
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
KITE = {"^NSEI": 256265, "^NSEBANK": 260105, "^INDIAVIX": 264969}
NAMES = {"^NSEI": "NIFTY 50", "^NSEBANK": "NIFTY BANK", "^INDIAVIX": "India VIX"}
# yfinance interval -> (Kite interval, days per request, minutes per candle)
INTERVALS = {"1m": ("minute", 60, 1), "5m": ("5minute", 100, 5), "15m": ("15minute", 200, 15), "30m": ("30minute", 200, 30),
             "1h": ("60minute", 400, 60), "60m": ("60minute", 400, 60), "1d": ("day", 2000, None)}
OPEN, CLOSE = time(9, 15), time(15, 30)
STALE_MIN = 15
HEALTH = []


def _days(period):
    """Trading days in a yfinance period ('5d', '60d', '1mo', '1y', 'max' -> None)."""
    p = str(period)
    if p == "max":
        return None
    n = int("".join(ch for ch in p if ch.isdigit()) or 1)
    return n * 21 if p.endswith("mo") else n * 252 if p.endswith("y") else n


def _frame(rows, daily):
    df = pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"])
    idx = pd.DatetimeIndex(df.pop("t"))
    df.index = idx.tz_convert(IST).tz_localize(None).normalize() if daily else idx.tz_convert(IST)
    df.insert(4, "Adj Close", df["Close"])
    return df[~df.index.duplicated(keep="last")].sort_index()


def _keep_last_sessions(df, n):
    if n is None or df.empty:
        return df
    days = sorted(set(df.index.date))[-n:]
    return df[pd.Index(df.index.date).isin(days)]


def _kite(symbol, n, interval, now, get=None):
    """Kite's candles as a frame, or None (no login or no Kite symbol); raises on Kite errors."""
    import kite
    s = kite.session()
    if not s or symbol not in KITE or interval not in INTERVALS:
        return None
    kint, per, _ = INTERVALS[interval]
    daily = kint == "day"
    span = 2000 if n is None else int(n * 1.6) + 6             # calendar days to cover n sessions
    start = datetime.combine(now.date() - timedelta(days=span), time(0, 0))
    end = datetime.combine(now.date(), time(23, 59, 59))
    rows = kite.history(s[0], s[1], KITE[symbol], kint, start, end, max_days=per, **({"get": get} if get else {}))
    return _keep_last_sessions(_frame(rows, daily), n) if rows else None


def _yahoo(symbol, period, interval, **kw):
    import yfinance as yf
    kw.pop("progress", None)
    kw.setdefault("auto_adjust", False)
    raw = yf.download(symbol, period=period, interval=interval, progress=False, **kw)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"])
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    return raw


def in_session(now):
    from calendars import is_session
    return is_session(now.date(), "XBOM") and OPEN <= now.time() <= CLOSE


def stale(df, interval, now):
    """'HH:MM' of the last candle when intraday candles are more than STALE_MIN minutes behind during the session."""
    mins = INTERVALS.get(interval, (None, None, None))[2]
    if not mins or df is None or df.empty or not in_session(now):
        return None
    last = pd.Timestamp(df.index[-1])
    last = last.tz_localize(IST) if last.tz is None else last.tz_convert(IST)
    if last.date() != now.date() or now - last.to_pydatetime() > timedelta(minutes=mins + STALE_MIN):
        return last.strftime("%d %b %H:%M")
    return None


def missing_session(df, now):
    """The last finished session missing from daily candles (its date), else None."""
    from calendars import is_session
    if df is None or df.empty:
        return None
    d = now.date() if now.time() >= time(15, 45) else now.date() - timedelta(days=1)
    while not is_session(d, "XBOM"):
        d -= timedelta(days=1)
    last = pd.Timestamp(df.index[-1]).date()
    return d.isoformat() if last < d else None


def note(symbol, interval, source, df, issue=None):
    last = None if df is None or df.empty else str(pd.Timestamp(df.index[-1]))[:16]
    HEALTH.append({"symbol": NAMES.get(symbol, symbol), "interval": interval, "source": source,
                   "rows": 0 if df is None else int(len(df)), "last": last, "issue": issue,
                   "at": datetime.now(IST).isoformat(timespec="minutes")})
    if issue:
        print(f"prices: {NAMES.get(symbol, symbol)} {interval}: {issue}", flush=True)


def download(symbol, period="5d", interval="1d", now=None, get=None, yahoo=None, **kw):
    """yf.download(symbol, period, interval) with Kite first for NIFTY 50 / NIFTY BANK / India VIX."""
    now = now or datetime.now(IST)
    yahoo = yahoo or _yahoo
    if symbol not in KITE:
        return yahoo(symbol, period, interval, **kw)
    n, daily = _days(period), interval == "1d"
    k, why = None, None
    try:
        k = _kite(symbol, n, interval, now, get)
        if k is None:
            import kite
            why = "no Kite login today" if not kite.session() else "Kite has no candles"
    except Exception as e:                                       # never stops a run: Yahoo below
        why = f"Kite failed ({e})"
    if k is not None and not k.empty:
        if daily and (n is None or n > INTERVALS["1d"][1]):     # long history: Yahoo's, with Kite's recent sessions on top
            y = yahoo(symbol, period, interval, **kw)
            y.index = pd.to_datetime(y.index).tz_localize(None).normalize() if len(y) else y.index
            out = pd.concat([y[~y.index.isin(k.index)], k]).sort_index()
            out.attrs["source"] = "kite+yahoo"
            note(symbol, interval, "kite+yahoo", out, missing_session(out, now) and f"missing session {missing_session(out, now)}")
            return out
        late = stale(k, interval, now)
        if not late:
            k.attrs["source"] = "kite"
            note(symbol, interval, "kite", k, missing_session(k, now) and daily and f"missing session {missing_session(k, now)}")
            return k
        why = f"Kite candles stale (last {late})"
    y = yahoo(symbol, period, interval, **kw)
    y.attrs["source"] = "yahoo"
    late = None if daily else stale(y, interval, now)
    if late and k is not None and not k.empty and pd.Timestamp(k.index[-1]) >= pd.Timestamp(y.index[-1]):
        k.attrs["source"] = "kite"                               # both behind: keep the fresher
        note(symbol, interval, "kite", k, f"{why}; Yahoo no fresher")
        return k
    issue = "; ".join(x for x in (why if why != "no Kite login today" else None,
                                  late and f"Yahoo candles stale (last {late})",
                                  daily and missing_session(y, now) and f"missing session {missing_session(y, now)}") if x)
    note(symbol, interval, "yahoo", y, issue or None)
    return y


def source_of(df):
    return (getattr(df, "attrs", None) or {}).get("source", "yahoo")


def save_health(path=None):
    """Merge this run's checks into the day's health file (latest per series)."""
    path = path or os.environ.get("DATA_HEALTH")
    if not path or not HEALTH:
        return None
    today = datetime.now(IST).date().isoformat()
    try:
        old = json.load(open(path))
    except (OSError, ValueError):
        old = {}
    rows = old.get("series", {}) if old.get("date") == today else {}
    for h in HEALTH:
        rows[f"{h['symbol']} {h['interval']}"] = h
    import kite
    out = {"date": today, "updated": datetime.now(IST).isoformat(timespec="minutes"), "kite": bool(kite.session()),
           "series": rows, "issues": [f"{k}: {v['issue']}" for k, v in rows.items() if v.get("issue")]}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    json.dump(out, open(path, "w"), separators=(",", ":"))
    HEALTH.clear()
    return out


atexit.register(save_health)
