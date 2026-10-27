"""Experiment mode "intrarules" (27 Oct 2026): can a simple intraday rule trade NIFTY's swings profitably?

27 Oct 2026: following the AI's view every 10 minutes (buy a CALL when it said up, a PUT when it said down) made 12
trades and lost 11: it switched after each move, just before the move turned. The user asked for fewer, better trades
with at least half of them winning. Tested here on Yahoo's last ~60 days of 5-minute NIFTY candles (its limit), no AI:
  flip      the 27 Oct pattern: every 10 minutes take the side of the move since yesterday's close (the baseline)
  chase X   after NIFTY moved X% or more within 20 minutes, trade in that direction
  fade X    ... trade against it (expecting part of the swing to come back)
  + morning only trades in the direction of the morning call (the from-open signal's side, walk-forward)
  + range   chase only on trend days (first hour's range at least 0.6%), fade only on range days (below 0.6%);
            these enter only after 10:15, when the first hour is known (the first run let them enter from 09:45,
            looking ahead at the rest of the first hour)
  morning confirm  at 09:45, trade the morning call's side if the first 30 minutes moved the same way
Entries from 09:45 to 14:30 (no first 30 minutes, no last 45). One position at a time, held to a 0.5% target, a 0.3%
stop (checked on each candle's high / low, the stop first when both are touched) or 15:15. Costs 0.03% a trade.
Results are NIFTY's move (an at-the-money option moves about half as much, plus its own costs and decay).
Rule fixed before the run: a rule passes only with at least 20 trades, wins on at least half of them, and earns after
costs in both halves of the days. About 16 variants are tried, so a narrow pass is likely luck; 60 days is short.
Result (27 Oct 2026, 31 Jul - 27 Oct, run 40549383733): nothing passed. flip (the 27 Oct pattern) 122 trades, 48% won,
-0.00% each; chase 0.25 47 trades, 51%, +0.05% but -0.17% in the first half; fade 0.25 54 trades, 33%, -0.11%;
chase 0.25 on trend days 18 trades, 28%, -0.09% (the first run, with entries before the first hour was over, showed
+0.10% and 55%: that was look-ahead). Not used; the once-a-day from-open signal stays the only trade signal.
"""
import json
from datetime import time, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

import todaycall as tc
from accuracy_study import _wf_tiers

COST, TARGET, STOP = 0.03, 0.5, 0.3
START, LAST_ENTRY, EXIT = time(9, 45), time(14, 30), time(15, 15)


def days5m():
    raw = yf.download("^NSEI", period="60d", interval="5m", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    idx = pd.DatetimeIndex(raw.index)
    raw.index = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert("Asia/Kolkata")
    return {d: g for d, g in raw.groupby(raw.index.date) if len(g) > 60}


def morning_sides(dates):
    """The from-open signal's side for each day (walk-forward, so it only uses earlier days): +1 / -1 / 0."""
    nd = tc.daily()
    series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
    df = tc.history(nd, series)
    o2c = (1 + df["day"].values) / (1 + df["gap"].values) - 1
    p, _ = _wf_tiers(df[tc.OPEN_FEATS].values, o2c)
    m = {d.date(): float(np.sign(v)) if np.isfinite(v) else 0.0 for d, v in zip(df.index, p)}
    return {d: m.get(d, 0.0) for d in dates}


def run_day(g, side_fn, prev_close):
    """Trades for one day. side_fn(i, bars, ctx) -> +1 / -1 / 0 at the close of bar i (5-minute bars)."""
    t = [x.time() for x in g.index]
    o, h, l, c = (g[k].values for k in ("Open", "High", "Low", "Close"))
    first_hour = [i for i, x in enumerate(t) if x < time(10, 15)]
    rng = (h[first_hour].max() / l[first_hour].min() - 1) * 100 if first_hour else 0.0
    ctx = {"prev_close": prev_close, "open": o[0], "range1h": rng}
    out, i, n = [], 0, len(g)
    while i < n:
        end_t = (pd.Timestamp(g.index[i]) + timedelta(minutes=5)).time()     # decisions at bar closes on the
        s = side_fn(i, c, ctx) if START <= end_t <= LAST_ENTRY and end_t.minute % 10 == 5 else 0   # 10-min grid
        if not s:
            i += 1
            continue
        entry, j, res = c[i], i + 1, None
        while j < n:
            up, dn = (h[j] / entry - 1) * 100 * s, (l[j] / entry - 1) * 100 * s
            worst, best = min(up, dn), max(up, dn)
            if worst <= -STOP:
                res = -STOP
            elif best >= TARGET:
                res = TARGET
            elif t[j] >= EXIT:
                res = (c[j] / entry - 1) * 100 * s
            if res is not None:
                break
            j += 1
        if res is None:
            res, j = (c[-1] / entry - 1) * 100 * s, n - 1
        out.append(res - COST)
        i = j + 1
    return out


def rules(sides):
    def flip(i, c, ctx):                                  # 27 Oct: the side of the move so far, every 10 minutes
        return 1 if c[i] > ctx["prev_close"] else -1

    def move(i, c, x):
        if i < 4:
            return 0
        m = (c[i] / c[i - 4] - 1) * 100
        return 1 if m >= x else -1 if m <= -x else 0

    out = {"flip (27 Oct pattern)": lambda d: flip}
    for x in (0.25, 0.4):
        out[f"chase {x}"] = lambda d, x=x: (lambda i, c, ctx: move(i, c, x))
        out[f"fade {x}"] = lambda d, x=x: (lambda i, c, ctx: -move(i, c, x))
        out[f"chase {x} + morning"] = lambda d, x=x: (lambda i, c, ctx: move(i, c, x) if move(i, c, x) == sides[d] else 0)
        out[f"fade {x} + morning"] = lambda d, x=x: (lambda i, c, ctx: -move(i, c, x) if -move(i, c, x) == sides[d] else 0)
        # the day type needs the whole first hour (to 10:15), so these trade only after it (bar 12 starts 10:15)
        out[f"chase {x} on trend days"] = lambda d, x=x: (lambda i, c, ctx: move(i, c, x) if i >= 12 and ctx["range1h"] >= 0.6 else 0)
        out[f"fade {x} on range days"] = lambda d, x=x: (lambda i, c, ctx: -move(i, c, x) if i >= 12 and ctx["range1h"] < 0.6 else 0)

    def confirm(d):
        done = {"x": False}

        def f(i, c, ctx):
            if done["x"] or i != 5:                       # the 09:40-09:45 bar closes at 09:45
                return 0
            done["x"] = True
            s = sides[d]
            return s if s and np.sign(c[i] - ctx["open"]) == s else 0
        return f
    out["morning confirm"] = confirm
    return out


def score(pnl_by_day):
    days = sorted(pnl_by_day)
    allp = [x for d in days for x in pnl_by_day[d]]
    if not allp:
        return {"trades": 0}
    h = len(days) // 2
    a = [x for d in days[:h] for x in pnl_by_day[d]]
    b = [x for d in days[h:] for x in pnl_by_day[d]]
    r = {"trades": len(allp), "per_day": round(len(allp) / len(days), 2), "win": round(float(np.mean([x > 0 for x in allp])), 3),
         "avg_pct": round(float(np.mean(allp)), 3), "total_pct": round(float(np.sum(allp)), 2),
         "halves_avg": [round(float(np.mean(a)), 3) if a else None, round(float(np.mean(b)), 3) if b else None]}
    r["passes"] = (r["trades"] >= 20 and r["win"] >= 0.5 and all(v is not None and v > 0 for v in r["halves_avg"]))
    return r


def main():
    try:
        days = days5m()
        dates = sorted(days)
        nd = tc.daily()
        prev = {d: float(nd["close"][nd.index.date < d].iloc[-1]) for d in dates}
        sides = morning_sides(dates)
        out = {"days": len(dates), "from": str(dates[0]), "to": str(dates[-1]),
               "morning_side_days": int(sum(1 for d in dates if sides[d]))}
        for name, make in rules(sides).items():
            out[name] = score({d: run_day(days[d], make(d), prev[d]) for d in dates})
        out["passed"] = [k for k, v in out.items() if isinstance(v, dict) and v.get("passes")]
        print("STUDY intrarules " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY intrarules failed: {e!r}", flush=True)
