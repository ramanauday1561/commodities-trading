"""Experiment mode "stargrace" (25 Nov 2026, asked by the owner after the 25 Nov day): give each automatic * pick a few
minutes before its 10% stop starts.

What happened: 5 real picks (two strikes out of the money, AUTO_STRIKE=otm2). The 09:35 pick made +Rs1,596 before
charges; three of the other four were sold by the 10% stop within 4-26 minutes (10:15, 10:55, 13:05: about -Rs1,100
each). On the day's real option candles, 8 of the 14 * leans would have been stopped out, some of them right on
direction (09:55: NIFTY -38.8 in the candle, the PUT stopped first). 20 Nov had the same shape (a right lean's CALL
dipped 12.5% inside the first 5 minutes). Study starstop (20 Nov) found no WIDER stop that passes: wider stops lose
much more on wild days. This tests something narrower: the noise right after the buy, while keeping 10% after that.

Rules tested (fixed before the run), each against the server's rule as it runs (10% stop from the start):
  G5      no stop during the first 5-minute candle, then 10%
  G5c25   a 25% stop during the first 5-minute candle (a guard for wild days), then 10%
  G10c25  a 25% stop during the first two 5-minute candles, then 10%
Everything else as the server: * leans of 25+ points expected (as studies starstop and startrend), entries until
14:55, the next expiry after today, 1 lot, out after 30 minutes or at 15:15, Rs120 (1.85 option points) of costs.
The stop level is always measured from the entry price.

Data, two layers (as study starstop, whose pricing this reuses):
  1. Kite's real 5-minute option candles (options-live, 4 Nov 2026 on) with the * leans the page published
     (scoreboard live/<day>.json), at the money AND two strikes out of the money (what the server buys since 24 Nov).
  2. Nine years: the * leans as leanfilter_study.walk_forward makes them, priced from NIFTY's 5-minute candles with the
     stop seen inside each candle (star_stop_study.path_pick, here with a stop level per candle), premium = the median
     entry premium of layer 1's at-the-money picks, b and a from Kite's quotes (leanfilter_study.calibrate).

Pass rule, fixed before the run. A rule passes only if it beats 10%-from-the-start
  (1) in total on layer 1's real option candles, both at the money and two strikes out, and
  (2) in layer 2 on Rs a lot a trade: on average, in both halves of the years, since 2022, and in at least 70% of the
      years that have trades.
If several pass, the one with the best layer-2 average. Whether the picks earn after costs is reported
(leanfilter_study.passes) and does not change the verdict. A pass goes to the owner before the server changes.

RESULT (run 25 Nov 2026 with that day's candles, locally on the data branches; walk-forward * leans 2017-01-02 to
2026-11-25; b 0.547, a -0.15; premium 0.941% of NIFTY, the median of layer 1's at-the-money picks): NONE PASSES.
  Layer 1, real option candles (48 published * leans of 25+ points, 4-25 Nov), Rs in total after costs:
    at the money:  10% -7,101 (18 won), G5 -7,228, G5c25 -7,228, G10c25 -6,223 (19 won)
    two strikes out: 10% -5,751 (17 won), G5 -5,990, G5c25 -5,990, G10c25 -5,521 (18 won)
    (25 Nov alone: the same for every rule, at the money -356, two out -84: its stops came after the first minutes)
  Layer 2, nine years (1,554 trades), Rs a lot a trade: 10% +39, G5 +50, G5c25 +52, G10c25 +82 (each up in 3 of 7
    years, none earns after costs). Against 10%: G5 better by 11.0 (halves -158 / +8, since 2022 +14, better in 2 of 7
    years), G5c25 +12.6 (-87 / +9, +15, 2 of 7), G10c25 +43.1 (-125 / +32, +54, 3 of 7; 2020 -561, 2022 +223).
  G5 and G5c25 also lose on the real candles; G10c25 wins there (+Rs1,000 / +230) but loses badly in wild years
  (2020) and is better in only 3 of 7 years. As in study starstop: a looser start helps calm years and costs wild ones.
  The 10% stop from the start stays; the server is unchanged.
"""
import csv
import json
import math
import os
from datetime import datetime, timedelta

import pandas as pd

import star_stop_study as ss

STOP, CAT = 0.10, 0.25
RULES = {"10%": (0, None), "G5": (1, None), "G5c25": (1, CAT), "G10c25": (2, CAT)}   # (grace candles, stop during grace)


def levels(n, rule):
    """The stop (fraction of the entry premium) for each of n candles under a rule; None = no stop in that candle."""
    grace, cat = RULES[rule]
    return [cat if i < grace else STOP for i in range(n)]


# ---------------------------------------------------------------- layer 1
def real_pick(rows, day, at, lean, spot, rule, otm=0):
    """Rs after costs for one pick on the day's 5-minute option candles (otm strikes out of the money), or None."""
    side = "CE" if lean == "up" else "PE"
    exps = sorted({r["expiry"] for r in rows if r["expiry"] > day})
    cand = [r for r in rows if exps and r["expiry"] == exps[0] and r["type"] == side]
    if not cand:
        return None
    k = round(spot / 50) * 50 + (50 * otm if side == "CE" else -50 * otm)
    strikes = {float(r["strike"]) for r in cand}
    if float(k) not in strikes:
        return None
    t0 = datetime.strptime(f"{day} {at}", "%Y-%m-%d %H:%M")
    want = [(t0 + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M") for i in range(ss.HOLD_BARS)]
    want = [w for w in want if w[11:] < ss.LAST_EXIT]
    bars = {r["datetime"]: r for r in cand if float(r["strike"]) == k and r["datetime"] in want}
    if not want or want[0] not in bars or want[-1] not in bars:
        return None
    entry = float(bars[want[0]]["open"])
    out = float(bars[want[-1]]["close"])
    for t, s in zip(want, levels(len(want), rule)):
        b = bars.get(t)
        if b and s is not None and float(b["low"]) <= entry * (1 - s):
            out = min(entry * (1 - s), float(b["open"]))
            break
    return {"rs": round((out - entry) * ss.LOT - ss.RS_COST), "entry": entry}


def layer1(store_dir, optlive_dir):
    res, cache, prem = {o: {r: [] for r in RULES} for o in (0, 2)}, {}, []
    for day, at, lean, spot, size in ss.star_leans(store_dir):
        path = os.path.join(optlive_dir, "candles", f"{day}.csv")
        if not os.path.exists(path):
            continue
        if day not in cache:
            with open(path) as fh:
                cache[day] = list(csv.DictReader(fh))
        for o in (0, 2):
            for r in RULES:
                x = real_pick(cache[day], day, at, lean, spot, r, o)
                if x:
                    res[o][r].append({"day": day, "at": at, "rs": x["rs"]})
                    if o == 0 and r == "10%":
                        prem.append(x["entry"] / spot)
    out = {}
    for o, name in ((0, "atm"), (2, "otm2")):
        out[name] = {r: {"trades": len(v), "total_rs": int(sum(x["rs"] for x in v)), "won": sum(x["rs"] > 0 for x in v)}
                     for r, v in res[o].items()}
        days = {}
        for r, v in res[o].items():
            for x in v:
                days.setdefault(x["day"], {}).setdefault(r, 0)
                days[x["day"]][r] += x["rs"]
        out[name]["by_day"] = days
    prem.sort()
    out["premium_pct_median"] = round(100 * prem[len(prem) // 2], 3) if prem else None
    return out


# ---------------------------------------------------------------- layer 2
def path_pick(entry, side, w, prem, b, a, stops):
    """Option points before costs, with a stop level per 5-minute candle (as star_stop_study.path_pick)."""
    for i, ((_, r), s) in enumerate(zip(w.iterrows(), stops)):
        steps = (i + 1) / 2
        worst = (r["Low"] - entry) if side > 0 else (entry - r["High"])
        opn = side * (r["Open"] - entry)
        if s is not None and b * worst + a * steps <= -s * prem:
            return min(-s * prem, b * opn + a * steps)
    last = w.iloc[-1]
    return b * side * (last["Close"] - entry) + a * len(w) / 2


def nine_year(t, nifty, b, a, prem_pct):
    t = t[t["star"] & (t["size_pts"] >= ss.MIN_SIZE) & (t["k"] <= 33)]
    t = t[~((t["d"] >= ss.CAS_FROM) & (t["k"] >= 35))]
    out = []
    for r in t.itertuples():
        g = nifty.get(r.d)
        w = ss.bars_after(g, r.k) if g is not None else None
        if w is None:
            continue
        side = 1 if r.pred > 0 else -1
        row = {"year": r.year}
        for name in RULES:
            row[name] = (path_pick(r.price, side, w, prem_pct * r.price, b, a, levels(len(w), name)) - ss.COST_PTS) * ss.LOT
        out.append(row)
    return pd.DataFrame(out)


def compare(x, base, years):
    xs, bs = x.groupby(years).mean(), base.groupby(years).mean()
    diff = (xs - bs).sort_index()
    half, need = len(diff) // 2, math.ceil(0.7 * len(diff))
    r = {"better_avg": round(float(x.mean() - base.mean()), 1),
         "halves": [round(float(diff.iloc[:half].mean()), 1), round(float(diff.iloc[half:].mean()), 1)] if half else None,
         "since_2022": round(float(x[years >= 2022].mean() - base[years >= 2022].mean()), 1),
         "years_better": f"{int((diff > 0).sum())}/{len(diff)} (need {need})",
         "by_year": {str(k): int(round(v)) for k, v in diff.items()}}
    r["passes"] = bool(r["better_avg"] > 0 and r["halves"] and all(h > 0 for h in r["halves"]) and r["since_2022"] > 0
                       and int((diff > 0).sum()) >= need)
    return r


def layer2(p):
    import leanfilter_study as lf
    yrs, out = p["year"], {}
    for name in RULES:
        v = p[name]
        by = v.groupby(yrs).mean()
        h = len(by) // 2
        earn = {"trades": int(len(v)), "pts": float(v.mean()), "halves": [float(by.iloc[:h].mean()), float(by.iloc[h:].mean())],
                "since_2022": float(v[yrs >= 2022].mean()), "years_up": f"{int((by > 0).sum())}/{len(by)}"}
        out[name] = {"trades": int(len(v)), "rs_per_trade": int(round(v.mean())), "years_up": earn["years_up"],
                     "earns_after_costs": lf.passes(earn), "vs_10%": compare(v, p["10%"], yrs) if name != "10%" else None}
    return out


def verdict(l1, l2):
    ok = [r for r in RULES if r != "10%" and l2[r]["vs_10%"]["passes"]
          and all(l1[o][r]["total_rs"] > l1[o]["10%"]["total_rs"] for o in ("atm", "otm2"))]
    return max(ok, key=lambda r: l2[r]["rs_per_trade"]) if ok else None


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        import nextcandle_study as ns
        optlive, store = os.environ.get("OPTLIVE_DIR", "optlive"), os.environ.get("STORE_DIR", "store")
        nifty, bank, vix = (intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), k) for k in ("nifty", "banknifty", "vix"))
        l1 = layer1(store, optlive)
        cal = lf.calibrate(optlive)
        b, a = (cal["b"], cal["a"]) if cal.get("pairs", 0) >= 100 else (0.5, 0.0)
        prem = l1["premium_pct_median"] or 0.8
        t = lf.walk_forward(ns.rows(nifty, bank, vix, h=1))
        l2 = layer2(nine_year(t, nifty, b, a, prem / 100))
        out = {"pricing": {"b": b, "a": a, "premium_pct": prem}, "from": str(t["d"].min()), "to": str(t["d"].max()),
               "layer1_real_options": l1, "layer2_nine_years": l2, "passes": verdict(l1, l2)}
        print("STUDY stargrace " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY stargrace failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
