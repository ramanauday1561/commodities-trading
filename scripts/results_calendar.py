"""Quarterly results of NIFTY's heaviest stocks (Yahoo's earnings dates, past and upcoming).

19 Oct 2026: HDFC Bank, ICICI Bank and Axis Bank reported on Saturday 17 Oct; Axis and HDFC Bank fell up to 5% and NIFTY
lost 1.11% from a flat open while the overnight markets pointed nowhere. Over ~3 years (preopen_study.results_study,
101 such sessions) NIFTY moved more than 1% on 27% of the sessions after heavyweight results vs 17% on other days,
and the from-open signal's trades on those sessions lost money (8 trades, -0.19% each), so it stands aside then.
25 Oct 2026 (results_size_study, 738 sessions, 49 of the 50 NIFTY stocks served by Yahoo): these 11 beat the 5, 20 or
all 50 heaviest. Kept trades +0.197% each (total +14.4%) vs +0.186% (5), +0.193% (20), +0.199% on fewer trades (50,
total +11.7%); the trades skipped lost -0.29% each with 11, -0.08% with 20, and earned +0.02% with 50 (skipping them
cost money). NIFTY moved more than 1% on 26% of the sessions flagged by the 11, 21% by the 20, 20% by the 50.

A result dated d counts for the first session after it: from the previous session's date up to the day before
(results come after the close or at weekends; one released during market hours is counted a day late).
"""
import json
import os
from datetime import date

import pandas as pd

HEAVY = {"HDFCBANK.NS": "HDFC Bank", "ICICIBANK.NS": "ICICI Bank", "RELIANCE.NS": "Reliance", "INFY.NS": "Infosys",
         "TCS.NS": "TCS", "AXISBANK.NS": "Axis Bank", "KOTAKBANK.NS": "Kotak Bank", "SBIN.NS": "SBI",
         "BHARTIARTL.NS": "Bharti Airtel", "LT.NS": "L&T", "ITC.NS": "ITC"}


def _day(x):
    t = pd.Timestamp(x)
    return (t.tz_localize(None) if t.tzinfo else t).normalize().date()


def fetch(cache_path=None):
    """{ticker: [dates]}; a ticker Yahoo cannot serve falls back to the cached copy."""
    cached = {}
    if cache_path and os.path.exists(cache_path):
        try:
            cached = {k: [date.fromisoformat(d) for d in v] for k, v in json.load(open(cache_path)).items()}
        except (OSError, ValueError):
            cached = {}
    out = {}
    try:
        import yfinance as yf
        for t in HEAVY:
            try:
                ed = yf.Ticker(t).get_earnings_dates(limit=40)
                if ed is not None and len(ed):
                    out[t] = sorted({_day(x) for x in ed.index})
            except Exception as e:                        # one ticker failing must not stop the rest
                print(f"results {t}: {e!r}", flush=True)
    except ImportError:
        pass
    for t in HEAVY:
        if not out.get(t) and cached.get(t):
            out[t] = cached[t]
    if cache_path and out:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        json.dump({k: [d.isoformat() for d in v] for k, v in out.items()}, open(cache_path, "w"))
    return out


def since(cal, prev_session, day):
    """Names that reported from `prev_session` up to the day before `day` (they move `day`)."""
    return [HEAVY[t] for t, ds in cal.items() if any(prev_session <= d < day for d in ds)]


def flags(index, cal):
    """For each session in `index` (all sessions, in order; the first gets False): did a heavyweight report since the
    session before?"""
    days = [_day(d) for d in index]
    out = [False]
    for i in range(1, len(days)):
        out.append(bool(since(cal, days[i - 1], days[i])))
    return pd.Series(out, index=index)


def upcoming(cal, after, n=6):
    rows = sorted((d, HEAVY[t]) for t, ds in cal.items() for d in ds if d >= after)
    return [{"date": d.isoformat(), "name": nm} for d, nm in rows[:n]]
