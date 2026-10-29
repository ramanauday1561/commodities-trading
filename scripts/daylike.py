"""'Days like today': what NIFTY did from this time to the close on past days that looked like today so far.

Asked for on 28 Oct 2026, after a day of "should I buy a CALL or a PUT now?". The answers were worked out by hand from the
5-minute history; this puts the same lookup in the app (Live page, the hourly Telegram update). It is information, not a
signal: the "midday recovery" CALL it suggested on 28 Oct (61% of similar days rose into the close) was then tested as
a rule (midday_study.py) and failed, and no intraday rule has passed on 11 years (intraday_rules_study.py).

Usage: python scripts/daylike.py <intraday_dir> <out_dir>   (nightly, after intraday_data.py update)
Writes <out_dir>/daylike-nifty.json: for each checkpoint, every past day's move vs yesterday's close at that time, the
day's low and high so far, and the move from then to the last candle's close (all in %, 2 decimals).
"""
import json
import os
import sys
from datetime import time

import numpy as np
import pandas as pd

CHECKPOINTS = ["10:15", "10:45", "11:15", "11:45", "12:15", "12:45", "13:15", "13:45", "14:15", "14:45", "15:00"]  # candles closed by
NEAR = (0.15, 0.25, 0.25)                      # how close a past day must be: move now, low so far, high so far (%)
MIN_DAYS = 30


def build(days):
    """{checkpoint: {"now": [...], "low": [...], "high": [...], "rest": [...]}, "dates": [...]} from {date: candles}."""
    ds = sorted(days)
    out = {"dates": [], **{c: {"now": [], "low": [], "high": [], "rest": []} for c in CHECKPOINTS}}
    for a, b in zip(ds, ds[1:]):
        g = days[b]
        if len(g) < 70:
            continue
        pc, close = float(days[a]["Close"].iloc[-1]), float(g["Close"].iloc[-1])
        ends = [(pd.Timestamp(x) + pd.Timedelta(minutes=5)).time() for x in g.index]
        out["dates"].append(str(b))
        for c in CHECKPOINTS:
            h, m = map(int, c.split(":"))
            done = [i for i, e in enumerate(ends) if e <= time(h, m)]
            px = float(g["Close"].iloc[done[-1]])
            pct = lambda x: round((x / pc - 1) * 100, 2)
            row = out[c]
            row["now"].append(pct(px))
            row["low"].append(pct(g["Low"].iloc[done].min()))
            row["high"].append(pct(g["High"].iloc[done].max()))
            row["rest"].append(round((close / px - 1) * 100, 2))
    return out


def lookup(table, hm, now, low, high):
    """Past days like today at the latest checkpoint at or before hm ("HH:MM"), or None."""
    if not table:
        return None
    cps = [c for c in CHECKPOINTS if c <= hm]
    if not cps:
        return None
    c = cps[-1]
    t = {k: np.array(v, dtype=float) for k, v in table[c].items()}
    for widen in (1, 1.5, 2, 3):
        m = ((np.abs(t["now"] - now) <= NEAR[0] * widen) & (np.abs(t["low"] - low) <= NEAR[1] * widen)
             & (np.abs(t["high"] - high) <= NEAR[2] * widen))
        if m.sum() >= MIN_DAYS:
            break
    n = int(m.sum())
    if n < 10:
        return None
    rest = t["rest"][m]
    idx = np.where(m)[0]
    half = len(table["dates"]) // 2
    first, second = rest[idx < half], rest[idx >= half]
    up = float((rest > 0).mean())
    out = {"at": c, "days": n, "up": round(up, 2), "avg_pct": round(float(rest.mean()), 3),
           "close_above": round(float(((1 + t["now"][m] / 100) * (1 + rest / 100) > 1).mean()), 2),
           "range_pct": [round(float(np.percentile(rest, 10)), 2), round(float(np.percentile(rest, 90)), 2)],
           "halves_up": [round(float((x > 0).mean()), 2) if len(x) else None for x in (first, second)]}
    steady = all(h is not None and (h > 0.5) == (up > 0.5) for h in out["halves_up"])
    out["read"] = ("coin flip" if 0.42 <= up <= 0.58 or not steady else "leans up, untested" if up > 0.5
                   else "leans down, untested")
    return out


def for_today(table, today, now):
    """The lookup for the live session, from today-nifty.json's intraday block (None outside the session)."""
    i = (today or {}).get("intraday") or {}
    pc = ((today or {}).get("preopen") or {}).get("prev_close")
    if (today or {}).get("status") != "open" or not pc or not all(i.get(k) for k in ("price", "low", "high")):
        return None
    pct = lambda x: (x / pc - 1) * 100
    return lookup(table, now.strftime("%H:%M"), pct(i["price"]), pct(i["low"]), pct(i["high"]))


def line(d):
    """One line for the phone and the page."""
    if not d:
        return ""
    return (f"Days like today ({d['days']} since 2015, at {d['at']}): NIFTY rose into the close {round(d['up'] * 100)}% "
            f"of the time, {d['avg_pct']:+.2f}% on average ({d['read']}). Not a trade signal: no intraday rule has "
            f"passed on 11 years.")


if __name__ == "__main__":
    import intraday_data
    days = intraday_data.load(sys.argv[1], "nifty")
    if days:
        os.makedirs(sys.argv[2], exist_ok=True)
        tab = build(days)
        json.dump(tab, open(os.path.join(sys.argv[2], "daylike-nifty.json"), "w"), separators=(",", ":"))
        print(f"daylike: {len(tab['dates'])} days, {tab['dates'][0]} to {tab['dates'][-1]}", flush=True)
