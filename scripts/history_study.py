"""Experiment mode "history" (28 Oct 2026): three tests that need the 5-minute candle history (intraday_data.py).

Asked by the user on 27 Oct 2026 after the history was loaded ("run all the backtests").
  exits   the from-open trade (the live signal, walk-forward, top-20% days, standing aside after heavyweight results)
          with exits checked on 5-minute candles instead of 1-hour ones: no stop; stops 0.3 / 0.75 / 1.0%; exit at
          10:15 ... 14:15 with the 0.5% stop; a trailing stop; the stop moved to the entry after +0.5%.
          Compared with the live rule (0.5% stop, else hold to the close). The signal needs two years of hourly
          overnight data, so this covers about Aug 2024 on, not 11 years.
  vix     India VIX at the 09:15 open against its previous close (11 years): how far NIFTY moves that day, and VIX's
          opening jump as a stand-aside filter for the from-open trade and for chasing.
  events  the session after a US CPI / jobs report or a Fed decision (released after India's close) and NIFTY's weekly
          expiry day (Thursday; Tuesday from Sep 2025; the day before when that is a holiday): how far NIFTY moves, and
          standing aside on those days.
Costs 0.03% a trade. Rules fixed before the run: an exit passes with more per trade than the live rule by at least
0.02% in both halves and a higher total; a stand-aside filter passes when the days it skips lost money in total and the
trades it keeps earn more per trade than all trades in both halves. Many variants are tried, so a narrow pass is luck.
Result (28 Oct 2026, run 40557402646; 2,855 days; 59 from-open trades with candles, Feb 2024 - Oct 2026):
  exits   live rule +0.178% a trade (+10.5% total, 52% won). Only "stop 0.75%" passed, narrowly: +0.209% (+12.3%),
          second half better by exactly 0.020%; no stop +0.237% but worse in the second half; exiting by a fixed time
          (10:15 ... 14:15), trailing stops and a 0.3% stop all earned less.
  vix     VIX opened more than 2% from its close on only 87 of 2,854 days; NIFTY moved most when it opened 2-5% lower
          (1.04% vs 0.58%). Skipping trades when VIX opens up "passed" on 1 skipped trade (meaningless); chasing on those
          days lost (38% won).
  events  NIFTY does not move more after US CPI / jobs / Fed or on expiry days (0.54-0.59% vs 0.61% normal). Standing
          aside after US events passed: the 10 skipped trades lost -2.18% in total, the 49 kept +0.259% a trade;
          skipping expiry days failed (the skipped 9 made +1.31%).
Two narrow passes on small samples; neither is switched on without the user's decision.
"""
import json
import os
from datetime import date, time, timedelta

import numpy as np
import pandas as pd

import intraday_data
import results_calendar as rc
import todaycall as tc
import us_events
from accuracy_study import _wf_tiers
from intraday_rules_study import run_day
from vix_study import stats

COST = tc.TRADE_COST_PCT
LIVE_STOP = 0.5
EXIT_TIMES = (time(10, 15), time(11, 15), time(12, 15), time(13, 15), time(14, 15))
TUESDAY_EXPIRY = date(2025, 9, 1)            # NSE moved NIFTY's weekly expiry from Thursday to Tuesday
WEEKLY_FROM = date(2019, 2, 11)


def signal():
    """{date: +1 / -1} on the days the live from-open rule would have traded (walk-forward)."""
    nd = tc.daily()
    series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
    df = tc.history(nd, series)
    o2c = (1 + df["day"].values) / (1 + df["gap"].values) - 1
    p, tiers = _wf_tiers(df[tc.OPEN_FEATS].values, o2c)
    try:
        cal = rc.fetch()
        res = rc.flags(nd.index, cal).reindex(df.index).fillna(False).values.astype(bool) if cal else None
    except Exception:
        res = None
    take = np.isin(tiers, tc.TRADE_TIERS) & (~res if res is not None else True) & np.isfinite(p)
    return {d.date(): float(np.sign(v)) for d, v, t in zip(df.index, p, take) if t and v}, str(df.index[0].date())


def path(g, side, stop=LIVE_STOP, exit_at=None, trail=None, breakeven=None):
    """% earned by a trade from the 09:15 open, after costs, walking the 5-minute candles."""
    o, h, l, c = (g[k].values for k in ("Open", "High", "Low", "Close"))
    t = [x.time() for x in g.index]
    entry, best, floor = o[0], 0.0, (-stop if stop is not None else None)
    res = None
    for i in range(len(c)):
        if exit_at and t[i] >= exit_at:
            res = (o[i] / entry - 1) * 100 * side
            break
        worst = ((l[i] if side > 0 else h[i]) / entry - 1) * 100 * side
        if floor is not None and worst <= floor:
            res = floor
            break
        best = max(best, ((h[i] if side > 0 else l[i]) / entry - 1) * 100 * side)
        if trail is not None and best - trail > (floor if floor is not None else -1e9):
            floor = best - trail
        if breakeven is not None and best >= breakeven and (floor is None or floor < 0):
            floor = 0.0
    if res is None:
        res = (c[-1] / entry - 1) * 100 * side
    return res - COST


def exits(days, sig):
    ds = [d for d in sorted(sig) if d in days]
    run = lambda **kw: stats(np.array([path(days[d], sig[d], **kw) for d in ds]))
    live = run()
    out = {"trades_from": str(ds[0]) if ds else None, "live (0.5% stop, else close)": live}
    v = {"no stop": run(stop=None)}
    for s in (0.3, 0.75, 1.0):
        v[f"stop {s}%"] = run(stop=s)
    for e in EXIT_TIMES:
        v[f"exit {e:%H:%M} (0.5% stop)"] = run(exit_at=e)
    for tr in (0.5, 0.75):
        v[f"trailing {tr}%"] = run(stop=LIVE_STOP, trail=tr)
    v["stop to entry after +0.5%"] = run(breakeven=0.5)
    for k, r in v.items():
        r["passes"] = (r.get("trades", 0) >= 20 and r["total_pct"] > live["total_pct"] and
                       all(a is not None and b is not None and a >= b + 0.02 for a, b in zip(r["avg_halves"], live["avg_halves"])))
    out.update(v)
    out["passed"] = [k for k, r in v.items() if r["passes"]]
    return out


def day_stats(days, ds):
    """How far NIFTY moved on these days: open-to-close (absolute) and high-to-low, in %."""
    if not ds:
        return {"days": 0}
    o2c = [abs(days[d]["Close"].iloc[-1] / days[d]["Open"].iloc[0] - 1) * 100 for d in ds]
    rng = [(days[d]["High"].max() / days[d]["Low"].min() - 1) * 100 for d in ds]
    return {"days": len(ds), "avg_move_pct": round(float(np.mean(o2c)), 3), "avg_range_pct": round(float(np.mean(rng)), 3),
            "big_days_share": round(float(np.mean([x >= 1.0 for x in o2c])), 3)}


def stand_aside(days, sig, skip):
    """The live trade with and without the days in `skip`."""
    ds = [d for d in sorted(sig) if d in days]
    pnl = {d: path(days[d], sig[d]) for d in ds}
    allr = stats(np.array([pnl[d] for d in ds]))
    keep = stats(np.array([pnl[d] for d in ds if d not in skip]))
    skipped = [pnl[d] for d in ds if d in skip]
    r = {"all": allr, "kept": keep, "skipped": len(skipped), "skipped_total_pct": round(float(np.sum(skipped)), 2)}
    r["passes"] = bool(skipped and np.sum(skipped) < 0 and keep.get("trades", 0) >= 20 and
                       all(a is not None and b is not None and a > b for a, b in zip(keep["avg_halves"], allr["avg_halves"])))
    return r


def chase_on(days, prev, ds):
    """The 'chase 0.25' intraday rule (intraday_rules_study) on a subset of days."""
    def move(i, c, ctx):
        if i < 4:
            return 0
        m = (c[i] / c[i - 4] - 1) * 100
        return 1 if m >= 0.25 else -1 if m <= -0.25 else 0
    pnl = [x for d in ds for x in run_day(days[d], move, prev[d])]
    return stats(np.array(pnl))


def vix(days, vdays, sig, prev):
    dates = [d for d in sorted(days) if d in vdays]
    gap = {}
    for p, d in zip(dates, dates[1:]):
        gap[d] = (vdays[d]["Open"].iloc[0] / vdays[p]["Close"].iloc[-1] - 1) * 100
    groups = {"VIX opens up 5%+": [d for d, g in gap.items() if g >= 5], "up 2-5%": [d for d, g in gap.items() if 2 <= g < 5],
              "within 2%": [d for d, g in gap.items() if -2 < g < 2], "down 2-5%": [d for d, g in gap.items() if -5 < g <= -2],
              "down 5%+": [d for d, g in gap.items() if g <= -5]}
    out = {"days": len(gap), "from": str(min(gap)), "move_by_vix_open": {k: day_stats(days, v) for k, v in groups.items()}}
    up = set(groups["VIX opens up 5%+"]) | set(groups["up 2-5%"])
    out["from_open: skip when VIX opens up 2%+"] = stand_aside(days, sig, up)
    out["from_open: skip when VIX opens down 2%+"] = stand_aside(days, sig, set(groups["down 2-5%"]) | set(groups["down 5%+"]))
    out["chase 0.25 when VIX opens up 2%+"] = chase_on(days, prev, sorted(up & set(prev)))
    out["chase 0.25 other days"] = chase_on(days, prev, sorted((set(gap) - up) & set(prev)))
    return out


def expiries(dates):
    """NIFTY's weekly expiry sessions among `dates` (trading days): the last session on or before the expiry weekday."""
    s = set(dates)
    out = set()
    d, end = WEEKLY_FROM - timedelta(days=WEEKLY_FROM.weekday()), max(dates)      # Mondays
    while d <= end:
        e = d + timedelta(days=1 if d >= TUESDAY_EXPIRY else 3)
        for k in range(e.weekday() + 1):                 # back to Monday when the expiry day is a holiday
            x = e - timedelta(days=k)
            if x in s:
                out.add(x)
                break
        d += timedelta(days=7)
    return out


def events(days, sig):
    dates = sorted(days)
    ev = us_events.fetch_all()
    out = {}
    marked = {}
    for kind in ("fomc", "cpi", "jobs"):
        nxt = set()
        for e in ev.get(kind, []):
            i = np.searchsorted(np.array(dates, dtype="datetime64[D]"), np.datetime64(e), side="right")
            if i < len(dates):
                nxt.add(dates[i])
        marked[kind] = nxt
    marked["expiry"] = expiries(dates)
    us = marked["fomc"] | marked["cpi"] | marked["jobs"]
    normal = [d for d in dates if d not in us and d not in marked["expiry"] and d >= WEEKLY_FROM]
    out["move"] = {"normal days (from Feb 2019)": day_stats(days, normal),
                   **{f"after US {k}" if k != "expiry" else "expiry day": day_stats(days, sorted(v)) for k, v in marked.items()}}
    out["from_open: skip after US events"] = stand_aside(days, sig, us)
    out["from_open: skip expiry days"] = stand_aside(days, sig, marked["expiry"])
    out["from_open: skip both"] = stand_aside(days, sig, us | marked["expiry"])
    return out


def main():
    d = os.environ.get("INTRADAY_DIR", "intra")
    days = {k: g for k, g in intraday_data.load(d, "nifty").items() if len(g) > 60}
    vdays = {k: g for k, g in intraday_data.load(d, "vix").items() if len(g) > 60}
    dates = sorted(days)
    prev = {b: float(days[a]["Close"].iloc[-1]) for a, b in zip(dates, dates[1:])}
    print(f"STUDY history: {len(days)} NIFTY days ({dates[0]} to {dates[-1]}), {len(vdays)} VIX days", flush=True)
    sig, since = signal()
    print(f"STUDY history: {len(sig)} from-open trade days (signal history from {since})", flush=True)
    for name, fn in (("exits", lambda: exits(days, sig)), ("vix", lambda: vix(days, vdays, sig, prev)),
                     ("events", lambda: events(days, sig))):
        try:
            print(f"STUDY history {name} " + json.dumps(fn()), flush=True)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"STUDY history {name} failed: {e!r}", flush=True)
