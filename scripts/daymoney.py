"""What a day's trades made, for the Live page's "₹2 lakh today" box, and the intraday rule engine they share with
intraday_rules_study.py.

Asked by the user on 27 Oct 2026: "if I invested 2 lakhs, how much would I have made". ₹2 lakh is about the margin for
one NIFTY futures lot (65 units), so every row is per lot, in futures terms: an at-the-money option moves about half
as much, with its own costs and time decay. Rows: our app (the 09:15 from-open signal with its 0.5% stop), following the
AI's every switch (replay days only), and the intraday rules tested on 11 years, each beside its 11-year result.
"""
from datetime import time, timedelta

import numpy as np
import pandas as pd

COST, TARGET, STOP = 0.03, 0.5, 0.3
START, LAST_ENTRY, EXIT = time(9, 45), time(14, 30), time(15, 15)
LOT, CAPITAL = 65, 200000
APP_STOP = 0.5                         # status.STOP_PCT
# intraday_rules_study.py, 27 Oct 2026, 2,855 days from Jan 2015 (the morning call exists from Aug 2024)
HISTORY = {"app": "3-year backtest: +0.13% a trade, about +₹1.8 lakh a lot over 3 years",
           "ai": "can't be backtested (the AI has read past news); it switches like 'follow the move'",
           "flip (27 Oct pattern)": "lost in all 12 years since 2015; 42% of trades won",
           "chase 0.25": "about break-even after costs since 2015 (+0.004% a trade); 44% won",
           "fade 0.25": "lost in 11 of 12 years; 37% won",
           "chase 0.25 + morning": "since Aug 2024: 48% won, +0.017% a trade, less than option costs"}
NAMES = {"flip (27 Oct pattern)": "Follow the move every 10 min", "chase 0.25": "Chase a 0.25% move",
         "fade 0.25": "Buy dips / sell rises (0.25%)", "chase 0.25 + morning": "Chase, only the morning call's side"}


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


def frame(bars):
    """[(aware start, o, h, l, c)] -> DataFrame (index: IST clock time, naive; Open High Low Close)."""
    idx = pd.DatetimeIndex([pd.Timestamp(b[0]).tz_convert("Asia/Kolkata").tz_localize(None) for b in bars])
    return pd.DataFrame([b[1:] for b in bars], index=idx, columns=["Open", "High", "Low", "Close"]).sort_index()


def app_trade(g, side, stop=APP_STOP):
    """The from-open trade: entry at the 09:15 open, out at the stop or the last candle's close; % after costs."""
    entry = g["Open"].iloc[0]
    for hi, lo in zip(g["High"].values, g["Low"].values):
        if ((lo if side > 0 else hi) / entry - 1) * 100 * side <= -stop:
            return -stop - COST
    return (g["Close"].iloc[-1] / entry - 1) * 100 * side - COST


def follow_ai(steps, prev_close, close):
    """Hold the side the AI's predicted close was on (vs yesterday's close), switching whenever it changes; the
    trades in % after costs."""
    out, side, entry = [], 0, None
    for s in steps:
        if not s.get("ai_close"):
            continue
        new = 1 if s["ai_close"] > prev_close else -1
        if new != side:
            if side:
                out.append((s["price"] / entry - 1) * 100 * side - COST)
            side, entry = new, s["price"]
    if side:
        out.append((close / entry - 1) * 100 * side - COST)
    return out


def row(key, pnl, price, note=None):
    rs = sum(pnl) / 100 * price * LOT
    return {"key": key, "name": NAMES.get(key, key), "rs": int(round(rs)), "trades": len(pnl),
            "won": int(sum(x > 0 for x in pnl)), "pct_of_capital": round(rs / CAPITAL * 100, 2),
            "history": HISTORY.get(key, ""), **({"note": note} if note else {})}


def money(bars, prev_close, morning_side=0, app_side=0, steps=None):
    """The ₹2 lakh box: one row per way of trading the day, per NIFTY lot."""
    if not bars or not prev_close:
        return None
    g = frame(bars)
    if len(g) < 60:
        return None
    price = float(g["Open"].iloc[0])
    rows = [row("app", [app_trade(g, app_side)] if app_side else [], price,
                None if app_side else "no trade today: the signal was not confident enough")]
    rows[0]["name"] = "Our app (09:15 signal)"
    if steps:
        rows.append(row("ai", follow_ai(steps, prev_close, float(g["Close"].iloc[-1])), price))
        rows[-1]["name"] = "Follow the AI's every switch"
    day = g.index[0].date()
    make = rules({day: morning_side})
    for key in NAMES:
        rows.append(row(key, run_day(g, make[key](day), prev_close), price))
    return {"capital": CAPITAL, "lot": LOT, "price": round(price, 2), "rows": rows,
            "basis": "per NIFTY futures lot (65); an at-the-money option moves about half as much"}


def add_to_replay(data_dir, intra_dir, store_dir, day):
    """Add the box to a replay already made (replay-nifty-<day>.json), from the stored 5-minute candles."""
    import json
    import os
    from zoneinfo import ZoneInfo
    import intraday_data
    path = os.path.join(data_dir, f"replay-nifty-{day}.json")
    rp = json.load(open(path))
    g = intraday_data.load(intra_dir, "nifty").get(pd.Timestamp(day).date())
    if g is None:
        print(f"money: no stored candles for {day}", flush=True)
        return None
    ist = ZoneInfo("Asia/Kolkata")
    bars = [(t.tz_localize(ist), *r) for t, r in zip(g.index, g[["Open", "High", "Low", "Close"]].itertuples(index=False))]
    calls = os.path.join(store_dir, "calls", "nifty.json")
    rec = next((r for r in json.load(open(calls)) if r["d"] == day), {}) if os.path.exists(calls) else {}
    rp["money"] = money(bars, rp["prev_close"], *sides(rec), steps=rp.get("steps"))
    json.dump(rp, open(path, "w"), separators=(",", ":"))
    print("money", day, [(r["name"], r["rs"]) for r in (rp["money"] or {}).get("rows", [])], flush=True)
    return rp["money"]


def sides(rec):
    """(morning side, app side) from a day's recorded call: the from-open direction, and it again if it traded."""
    fo = (rec or {}).get("from_open") or {}
    s = {"up": 1, "down": -1}.get(fo.get("direction"), 0)
    return s, (s if fo.get("trade") else 0)


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["replay"]:
        add_to_replay(*sys.argv[2:6])
