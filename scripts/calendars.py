"""Exchange trading days, so forecasts skip market holidays and not just weekends.

NIFTY uses the BSE calendar (same holidays as NSE). The COMEX/NYMEX futures use the NYSE calendar: on US holidays
CME trades only a shortened session and Yahoo publishes no daily candle, so the NYSE calendar matches the data.
Beyond the years a calendar knows (exchange_calendars ships holiday lists a year or so ahead) or if the package
is missing, plain weekdays are used.
"""
from datetime import date, timedelta
from functools import lru_cache

try:
    import exchange_calendars as xc
except ImportError:  # pragma: no cover - the workflow installs it
    xc = None


@lru_cache(maxsize=None)
def _calendar(name):
    if xc is None or not name:
        return None
    for years in (3, 2, 1, 0):            # the furthest end date the calendar accepts
        try:
            return xc.get_calendar(name, start="2000-01-03", end=f"{date.today().year + years}-12-31")
        except Exception:
            continue
    return None


def is_session(day, name):
    if day.weekday() >= 5:
        return False
    cal = _calendar(name)
    if cal is None:
        return True
    try:
        return bool(cal.is_session(day.isoformat()))
    except Exception:      # outside the calendar's range: weekdays
        return True


def next_sessions(after, n, name):
    """The first n trading days strictly after `after` (a date)."""
    out, d = [], after
    while len(out) < n:
        d += timedelta(days=1)
        if is_session(d, name):
            out.append(d)
    return out


def previous_session(day, name):
    """The last trading day strictly before `day`."""
    d = day - timedelta(days=1)
    while not is_session(d, name):
        d -= timedelta(days=1)
    return d


def last_finished_session(today, after_close, name):
    """The newest session whose close has passed: today if it is a session and its close has passed."""
    if after_close and is_session(today, name):
        return today
    return previous_session(today, name)
