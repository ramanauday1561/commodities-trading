"""Experiment mode "orb" (26 Nov 2026, asked by the owner after reading a US day-trading skill set): does an
opening-range breakout on NIFTY earn after costs, bought as a NIFTY option?

The rule tested (fixed before the run, as that skill's US-stock rule, moved to NSE hours):
  range    the high and low of NIFTY's first three 5-minute candles (09:15, 09:20, 09:25: the first 15 minutes)
  signal   the first 5-minute candle from 09:30 on that CLOSES above the range high (buy a CALL) or below the range
           low (buy a PUT); one trade a day at most; no signal from a candle that closes after 14:55
  entry    at the open of the next 5-minute candle
  stop     NIFTY back at the middle of the range
  exits    A "1R": target = entry + the distance to the stop (reward:risk 1.0), else the stop, else out at 15:15
           B "stop only": no target; the stop, else out at 15:15
  A stop and a target inside the same candle count as the stop (the cautious reading). 15:15 is the server's last
  exit (since 3 Aug 2026 NIFTY stands still from 15:15 for the closing auction); the same cut is used for every year.

Data, two layers (as studies starstop and startrend):
  1. Kite's real 5-minute option candles (options-live, 4 Nov 2026 on): the at-the-money option of the next expiry
     after the day, bought at the open of the entry candle, sold at the close of the candle where NIFTY hit the stop
     or target (or the 15:10 candle). Rs120 a lot a round trip.
  2. All of NIFTY's stored 5-minute history (2015 on): the option priced as b x (NIFTY's move on its side) + a per 10
     minutes held (b, a from Kite's quotes, leanfilter_study.calibrate); 1.85 option points of costs (Rs120); 65 a lot.
     Not modelled: the option's curvature (gamma), the spread at the stop.

Pass rule, fixed before the run. A variant passes only if, in Rs a lot a trade after costs on layer 2, it earns on
average, in both halves of the years, since 2022, and in at least 70% of the years, over 300 or more trades
(as leanfilter_study.passes, with 70% of the years); AND it made money in total on layer 1's real option candles.
If both pass, the one with the higher layer-2 average. A pass is information for the owner; nothing becomes an order.

RESULT (run 26 Nov 2026 locally on the intraday-data and options-live branches; 2,932 days, 2015-01-09 to
2026-11-26; b 0.549, a -0.16 from Kite's quotes): NEITHER VARIANT PASSES.
  Layer 2 (12 years, 2,889 trades: NIFTY breaks its first 15 minutes almost every day), Rs a lot a trade after costs:
    1R         -218 (halves -219 / -219, since 2022 -218, up in 0 of 12 years; right 49.2%; 1,404 stops, 1,339 targets)
    stop only  -158 (halves -179 / -136, since 2022 -147, up in 2 of 12 years: 2022 0, 2024 +165; right 34.0%)
  Layer 1 (Kite's real option candles, 13 trades, 5-26 Nov 2026): 1R +Rs8,692 (8 won), stop only +Rs37,851 (6 won;
    6 Nov +21,145, 19 Nov +11,157, 20 Nov +12,461). November 2026 was a run of trending days; over 12 years the same
    rule loses in nearly every year. Layer 2 prices the option as a straight line in NIFTY (no curvature), which
    undersells the biggest all-day winners of "stop only", but not by enough to turn -Rs158 a trade in 10 of 12
    years. The 13 real days are a warning about small samples, not evidence. Nothing changes in the app.
"""
import csv
import json
import math
import os
from datetime import timedelta

import pandas as pd

LOT, RS_COST, COST_PTS = 65, 120, 1.85
LAST_SIGNAL, LAST_EXIT = "14:55", "15:15"
VARIANTS = ("1R", "stop_only")


def orb_trade(g, variant):
    """One day's trade on 5-minute NIFTY candles g (Open/High/Low/Close, time index), or None.
    {'side', 'entry', 'exit', 'in_t', 'out_t', 'why'} in NIFTY points and candle times."""
    hm = g.index.strftime("%H:%M")
    first = g[hm < "09:30"]
    if len(first) < 3:
        return None
    hi, lo = float(first["High"].max()), float(first["Low"].min())
    mid = (hi + lo) / 2
    rest = g[(hm >= "09:30")]
    rhm = rest.index.strftime("%H:%M")
    for i in range(len(rest)):
        if rhm[i] > LAST_SIGNAL:
            return None
        c = float(rest["Close"].iloc[i])
        side = 1 if c > hi else -1 if c < lo else 0
        if not side:
            continue
        after = rest.iloc[i + 1:]
        after = after[after.index.strftime("%H:%M") < LAST_EXIT]
        if after.empty:
            return None
        entry = float(after["Open"].iloc[0])
        risk = side * (entry - mid)
        if risk <= 0:                                            # opened back past the middle: no trade
            return None
        target = entry + side * risk if variant == "1R" else None
        for t, r in after.iterrows():
            worst = r["Low"] if side > 0 else r["High"]
            best = r["High"] if side > 0 else r["Low"]
            if side * (worst - mid) <= 0:
                out = float(r["Open"]) if side * (r["Open"] - mid) <= 0 else mid
                return {"side": side, "entry": entry, "exit": out, "in_t": after.index[0], "out_t": t, "why": "stop"}
            if target is not None and side * (best - target) >= 0:
                out = float(r["Open"]) if side * (r["Open"] - target) >= 0 else target
                return {"side": side, "entry": entry, "exit": out, "in_t": after.index[0], "out_t": t, "why": "target"}
        return {"side": side, "entry": entry, "exit": float(after["Close"].iloc[-1]), "in_t": after.index[0],
                "out_t": after.index[-1], "why": "time"}
    return None


def option_rs(tr, b, a):
    """Rs a lot after costs: b x NIFTY's move on the trade's side + a per 10 minutes held."""
    steps = ((tr["out_t"] - tr["in_t"]).total_seconds() / 60 + 5) / 10
    return (b * tr["side"] * (tr["exit"] - tr["entry"]) + a * steps - COST_PTS) * LOT


# ---------------------------------------------------------------- layer 1
def real_option(rows, day, tr):
    """Rs after costs on Kite's real option candles for one trade, or None without them."""
    typ = "CE" if tr["side"] > 0 else "PE"
    exps = sorted({r["expiry"] for r in rows if r["expiry"] > day})
    cand = [r for r in rows if exps and r["expiry"] == exps[0] and r["type"] == typ]
    if not cand:
        return None
    k = float(round(tr["entry"] / 50) * 50)
    bars = {r["datetime"]: r for r in cand if float(r["strike"]) == k}
    t_in, t_out = tr["in_t"].strftime("%Y-%m-%d %H:%M"), tr["out_t"].strftime("%Y-%m-%d %H:%M")
    if t_in not in bars or t_out not in bars:
        return None
    return round((float(bars[t_out]["close"]) - float(bars[t_in]["open"])) * LOT - RS_COST)


def layer1(nifty, optlive_dir):
    out = {v: [] for v in VARIANTS}
    for path in sorted(os.listdir(os.path.join(optlive_dir, "candles"))):
        day = path[:10]
        g = nifty.get(pd.Timestamp(day).date())
        if g is None:
            continue
        with open(os.path.join(optlive_dir, "candles", path)) as fh:
            rows = list(csv.DictReader(fh))
        for v in VARIANTS:
            tr = orb_trade(g, v)
            if tr:
                rs = real_option(rows, day, tr)
                if rs is not None:
                    out[v].append({"day": day, "side": "up" if tr["side"] > 0 else "down",
                                   "at": tr["in_t"].strftime("%H:%M"), "why": tr["why"], "rs": rs})
    return {v: {"trades": len(x), "total_rs": int(sum(y["rs"] for y in x)), "won": sum(y["rs"] > 0 for y in x),
                "picks": [f"{y['day']} {y['at']} {y['side']} {y['why']} {y['rs']:+d}" for y in x]} for v, x in out.items()}


# ---------------------------------------------------------------- layer 2
def layer2(nifty, b, a):
    res = {}
    for v in VARIANTS:
        rows = []
        for d in sorted(nifty):
            tr = orb_trade(nifty[d], v)
            if tr:
                rows.append({"year": d.year, "rs": option_rs(tr, b, a), "right": tr["side"] * (tr["exit"] - tr["entry"]) > 0,
                             "why": tr["why"]})
        p = pd.DataFrame(rows)
        by = p.groupby("year")["rs"].mean()
        half, need = len(by) // 2, math.ceil(0.7 * len(by))
        r = {"trades": int(len(p)), "rs_per_trade": round(float(p["rs"].mean()), 1),
             "halves": [round(float(by.iloc[:half].mean()), 1), round(float(by.iloc[half:].mean()), 1)],
             "since_2022": round(float(p.loc[p["year"] >= 2022, "rs"].mean()), 1),
             "years_up": f"{int((by > 0).sum())}/{len(by)} (need {need})",
             "won_pct": round(100 * float(p["right"].mean()), 1),
             "exits": {k: int(n) for k, n in p["why"].value_counts().items()},
             "by_year": {str(k): int(round(x)) for k, x in by.items()}}
        r["passes"] = bool(r["trades"] >= 300 and r["rs_per_trade"] > 0 and all(h > 0 for h in r["halves"])
                           and r["since_2022"] > 0 and int((by > 0).sum()) >= need)
        res[v] = r
    return res


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        optlive = os.environ.get("OPTLIVE_DIR", "optlive")
        nifty = intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), "nifty")
        cal = lf.calibrate(optlive)
        b, a = (cal["b"], cal["a"]) if cal.get("pairs", 0) >= 100 else (0.5, 0.0)
        l1, l2 = layer1(nifty, optlive), layer2(nifty, b, a)
        ok = [v for v in VARIANTS if l2[v]["passes"] and l1[v]["total_rs"] > 0]
        out = {"pricing": {"b": b, "a": a}, "from": str(min(nifty)), "to": str(max(nifty)),
               "layer1_real_options": l1, "layer2_history": l2,
               "passes": max(ok, key=lambda v: l2[v]["rs_per_trade"]) if ok else None}
        print("STUDY orb " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY orb failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
