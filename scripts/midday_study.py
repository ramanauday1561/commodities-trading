"""Experiment mode "midday" (28 Oct 2026): the "midday recovery" CALL the user traded on 28 Oct, as a fixed rule.

On 28 Oct NIFTY fell 1.1% by 10:15 and was back near yesterday's close by 13:00. A quick look at 11 years of 5-minute
candles at 13:00 that day (so the idea came from looking at the data, not before it) found 121 such days on which
NIFTY rose from 13:00 to the close 61% of the time. The user bought the 22700 CE at 13:17; it fell to near the stop and
was sold at 14:06 for -Rs676. Fixed before this run, on the stored history (intraday_data.py, 2,855 days from 2015):
  recovery CALL   the day's low before 13:00 at least 0.6% below yesterday's close, and NIFTY at 13:00 (the 12:55
                  candle's close) no more than 0.25% below it: buy at 13:00, stop 0.3% below the entry (checked on each
                  candle's low), out at 15:15 (the 15:10 candle's close). This is the trade made on 28 Oct.
  variants        no stop; a 0.5% stop; "back within 0.25%" on both sides (not above +0.25%); the mirror PUT (high at
                  least 0.6% above yesterday's close, back to no more than +0.25%); both together.
Costs 0.03% a trade (futures; an option costs more and decays). Results are NIFTY's move.
Pass rule (the intraday rule studies' rule): at least 20 trades, at least half of them won, and earning after costs in
both halves of the days. Several variants are tried, so a narrow pass would be luck.
Result (28 Oct 2026, 2,854 days, 12 Jan 2015 - 27 Oct 2026): nothing passed.
  recovery CALL (the 28 Oct trade): 121 trades, 44% won, +0.059% a trade after futures costs (+0.019% / +0.085% by
    half), 7 of 12 years up. It fails the "half won" rule: the 0.3% stop is hit on about half the days, including on days
    that end higher (28 Oct came within 6 points of it). About 13 NIFTY points a trade, less than an option's costs.
  no stop 55% won but the first half lost (-0.074%); 0.5% stop also lost in the first half; "back within 0.25%" 87 trades,
  43% won, first half lost; the mirror PUT lost (38% won); both sides 40% won, +0.016%. Not used in the app.
"""
import json
import os
from datetime import time

import numpy as np
import pandas as pd

import intraday_data
from intraday_rules_study import score

COST = 0.03
DECIDE, EXIT = time(12, 55), time(15, 10)          # candle starts: 12:55 closes at 13:00, 15:10 closes at 15:15


def trade(g, side, stop):
    """% earned from the 13:00 price to 15:15, or the stop; after costs."""
    t = g.index.time
    entry = g["Close"].values[[x <= DECIDE for x in t]][-1]
    seg = g[[DECIDE < x <= EXIT for x in t]]
    for hi, lo in zip(seg["High"].values, seg["Low"].values):
        worst = ((lo if side > 0 else hi) / entry - 1) * 100 * side
        if stop is not None and worst <= -stop:
            return -stop - COST
    return (seg["Close"].values[-1] / entry - 1) * 100 * side - COST


def setups(days):
    """{day: (move to the low, move to the high, move at 13:00)} vs yesterday's close, in %, using candles up to 13:00."""
    ds = sorted(days)
    out = {}
    for a, b in zip(ds, ds[1:]):
        g = days[b]
        m = g[[x <= DECIDE for x in g.index.time]]
        if len(m) < 40 or len(g) < 70:
            continue
        pc = float(days[a]["Close"].iloc[-1])
        out[b] = ((m["Low"].min() / pc - 1) * 100, (m["High"].max() / pc - 1) * 100, (m["Close"].iloc[-1] / pc - 1) * 100)
    return out


def sides(st, kind):
    """{day: +1 CALL / -1 PUT} for the days a variant trades."""
    out = {}
    for d, (lo, hi, now) in st.items():
        call = lo <= -0.6 and now >= -0.25 and (kind != "within" or now <= 0.25)
        put = hi >= 0.6 and now <= 0.25
        if kind in ("call", "within", "both") and call:
            out[d] = 1
        elif kind in ("put", "both") and put:
            out[d] = -1
    return out


def main():
    try:
        days = {k: g for k, g in intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), "nifty").items()}
        st = setups(days)
        out = {"days": len(st), "from": str(min(st)), "to": str(max(st))}
        variants = {"recovery CALL (28 Oct trade, 0.3% stop)": ("call", 0.3), "recovery CALL, no stop": ("call", None),
                    "recovery CALL, 0.5% stop": ("call", 0.5), "recovery CALL, back within 0.25%": ("within", 0.3),
                    "mirror PUT (0.3% stop)": ("put", 0.3), "both sides (0.3% stop)": ("both", 0.3)}
        all_days = sorted(st)
        for name, (kind, stop) in variants.items():
            sd = sides(st, kind)
            out[name] = score({d: ([trade(days[d], sd[d], stop)] if d in sd else []) for d in all_days})
        out["passed"] = [k for k, v in out.items() if isinstance(v, dict) and v.get("passes")]
        print("STUDY midday " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY midday failed: {e!r}", flush=True)
