"""US macro event calendar: scheduled FOMC decisions, CPI releases and the jobs report (Employment Situation).

These are the US releases that move NIFTY, gold, silver and crude most (15 Oct 2026: hot CPI, KOSPI -7.6%). All of
them are scheduled weeks ahead, so a "there is an event before the next close" input never looks into the future.

Sources (official only; nothing is guessed):
  * FOMC: federalreserve.gov meeting calendars (current page + one historical page per year). Scheduled meetings
    only: unscheduled meetings and conference calls were not known in advance, so using them would leak hindsight.
  * CPI and jobs report: the FRED API's release dates (release 10 = CPI, 50 = Employment Situation), past and
    upcoming. Needs the free FRED_API_KEY secret; without it these two are simply left out.

Event timing differs by market:
  * NIFTY ("after_close"): US data (08:30 ET) and Fed decisions (14:00 ET) on US date d arrive after NIFTY's close
    on d, so they hit the next session: an event dated d counts for the move from session D to the next session
    when D <= d < next.
  * US futures ("us_session"): CPI/jobs at 08:30 ET land before that day's settlement (D < d <= next); the Fed at
    14:00 ET lands after it (D <= d < next).
"""
import json
import os
import re
import urllib.request
from datetime import date

import numpy as np
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
FOMC_CURRENT = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FOMC_HISTORICAL = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
FRED = ("https://api.stlouisfed.org/fred/release/dates?release_id={rid}&api_key={key}&file_type=json"
        "&include_release_dates_with_no_data=true&sort_order=asc&limit=10000")
FRED_RELEASES = {"cpi": 10, "jobs": 50}
KINDS = ("fomc", "cpi", "jobs")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
_M = "|".join(MONTHS)
_ABBR = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}
# "January 27-28", "March 17-18*", "Apr/May 30-1", "October 28-29" (a meeting's days; the decision is on the last day)
_MEETING = re.compile(rf"\b({_M}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))"
                      rf"\s+(\d{{1,2}})(?!\d)(?:\s*-\s*(\d{{1,2}})(?!\d))?(?!\s*-)\*?(?!\s*,\s*\d{{4}})")


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&nbsp;", " ")


def _decision_day(year, month_txt, d1, d2):
    """The last day of a meeting written as 'April 28-29' or 'Apr/May 30-1'."""
    if "/" in month_txt:
        m = _ABBR[month_txt.split("/")[1][:3]] if d2 else _ABBR[month_txt.split("/")[0][:3]]
    else:
        m = MONTHS.index(month_txt) + 1
    day = int(d2 or d1)
    y = year + 1 if (m == 1 and "/" in month_txt and month_txt.startswith("Dec")) else year
    return date(y, m, day)


def parse_fomc_current(html):
    """{year: [decision dates]} from the current calendars page (sections headed 'YYYY FOMC Meetings')."""
    text = _text(html)
    parts = re.split(r"(\d{4}) FOMC Meetings", text)
    out = {}
    for i in range(1, len(parts) - 1, 2):
        year, block = int(parts[i]), parts[i + 1].split("Note:")[0]   # the note names next year's first meeting
        days = []
        for m in _MEETING.finditer(block):
            tail = re.split(rf"\b(?:{_M}|[A-Z][a-z]{{2}}/)", block[m.end():m.end() + 40])[0].lower()   # up to the next meeting
            if "unscheduled" in tail or "notation vote" in tail or "conference call" in tail:
                continue
            days.append(_decision_day(year, m.group(1), m.group(2), m.group(3)))
        out[year] = sorted(set(days))
    return out


def parse_fomc_historical(html, year):
    """Decision dates from a historical year page: its meetings are titled 'January 29-30 Meeting - 2019'."""
    text = _text(html)
    days = []
    for m in re.finditer(rf"\b({_M}|(?:[A-Z][a-z]{{2}})/(?:[A-Z][a-z]{{2}}))\s+(\d{{1,2}})(?:\s*-\s*(\d{{1,2}}))?"
                         rf"\s+(?:\(unscheduled\)\s+)?Meeting\s*-\s*{year}", text):
        if "unscheduled" in text[m.start():m.end()].lower():
            continue
        days.append(_decision_day(year, m.group(1), m.group(2), m.group(3)))
    return sorted(set(days))


def fetch_fomc(first_year=2005):
    current = parse_fomc_current(_get(FOMC_CURRENT))
    years = dict(current)
    oldest = min(current) if current else date.today().year
    for y in range(first_year, oldest):
        try:
            years[y] = parse_fomc_historical(_get(FOMC_HISTORICAL.format(year=y)), y)
        except Exception as e:
            print(f"events: FOMC {y} unavailable ({e!r})")
    return sorted(d for ds in years.values() for d in ds)


def fetch_fred(kind, key):
    data = json.loads(_get(FRED.format(rid=FRED_RELEASES[kind], key=key)))
    return sorted({date.fromisoformat(r["date"]) for r in data.get("release_dates", [])})


def fetch_all(cache_path=None):
    """{kind: [dates]}; each source falls back to the cached copy when it cannot be reached."""
    cached = {}
    if cache_path and os.path.exists(cache_path):
        cached = {k: [date.fromisoformat(d) for d in v] for k, v in json.load(open(cache_path)).items() if k in KINDS}
    out = {}
    try:
        out["fomc"] = fetch_fomc()
    except Exception as e:
        print(f"events: FOMC calendar unavailable ({e!r}); using cache")
    key = os.environ.get("FRED_API_KEY")
    for kind in ("cpi", "jobs"):
        if not key:
            continue
        try:
            out[kind] = fetch_fred(kind, key)
        except Exception as e:
            print(f"events: FRED {kind} unavailable ({e!r}); using cache")
    for kind in KINDS:
        if not out.get(kind) and cached.get(kind):
            out[kind] = cached[kind]
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        json.dump({k: [d.isoformat() for d in v] for k, v in out.items()}, open(cache_path, "w"))
    print("events: " + ", ".join(f"{k} {len(v)} ({v[0]} .. {v[-1]})" for k, v in out.items() if v))
    return out


def features(index, next_session, events, timing="after_close"):
    """One row per session in `index`: 1 if an event of each kind lands between that session's close and the next
    session's close (the move the models predict from that row). next_session: the session after index[-1]."""
    idx = pd.DatetimeIndex(index).normalize()
    nxt = list(idx[1:]) + [pd.Timestamp(next_session).normalize()]
    out = pd.DataFrame(index=index)
    for kind in KINDS:
        days = np.array(sorted(pd.Timestamp(d) for d in events.get(kind, [])), dtype="datetime64[ns]")
        if not len(days):
            continue
        lo, hi = idx.values, np.array(nxt, dtype="datetime64[ns]")
        if timing == "us_session" and kind in ("cpi", "jobs"):        # 08:30 ET, before that day's settlement
            hit = np.searchsorted(days, hi, side="right") - np.searchsorted(days, lo, side="right")
        else:                                                         # after the close on the event's date
            hit = np.searchsorted(days, hi, side="left") - np.searchsorted(days, lo, side="left")
        out[f"ev_{kind}"] = (hit > 0).astype(float)
    if len(out.columns):
        out["ev_any"] = out.max(axis=1)
    return out


def upcoming(events, after, n=6):
    """The next few events after a date, for the page."""
    rows = [(d, k) for k in KINDS for d in events.get(k, []) if d > after]
    return [{"date": d.isoformat(), "kind": k} for d, k in sorted(rows)[:n]]
