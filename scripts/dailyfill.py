"""Build a missing daily candle from intraday bars.

Yahoo sometimes publishes the latest daily row hours after the session ends, while its 15-minute bars are already
complete. A session's candle is then rebuilt from the bars between the previous session's close and this session's
close (exchange time), which is right both for NIFTY (one day session) and for futures that trade from the evening
before. The row is only built when the bars reach the close, and the next run replaces it with Yahoo's own row.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from calendars import previous_session

BAR_MINUTES = 15


def daily_from_intraday(bars, day, tz, close_h, close_m, calendar=None):
    """One daily row (open, high, low, close, volume) for `day` from intraday `bars`, or None if they are incomplete.

    bars: DataFrame with lowercase open/high/low/close(/volume) columns and a DatetimeIndex of bar start times
          (tz-aware, or naive UTC).
    """
    if bars is None or not len(bars):
        return None
    zone = ZoneInfo(tz)
    idx = pd.DatetimeIndex(bars.index)
    idx = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert(zone)
    end = datetime.combine(day, time(close_h, close_m), zone)
    start = datetime.combine(previous_session(day, calendar), time(close_h, close_m), zone)
    sel = bars[(idx >= start) & (idx < end)].dropna(subset=["open", "high", "low", "close"])
    if not len(sel):
        return None
    last_start = idx[(idx >= start) & (idx < end)][-1]
    if last_start < end - timedelta(minutes=2 * BAR_MINUTES):   # the bars stop well before the close: not finished
        return None
    vol = float(sel["volume"].sum()) if "volume" in sel else 0.0
    return {"open": float(sel["open"].iloc[0]), "high": float(sel["high"].max()), "low": float(sel["low"].min()),
            "close": float(sel["close"].iloc[-1]), "volume": vol}


def append_day(full, day, row):
    """`full` (daily candles) with `row` added as the candle for `day`."""
    add = pd.DataFrame([row], index=pd.DatetimeIndex([pd.Timestamp(day)]))[full.columns]
    return pd.concat([full, add])
