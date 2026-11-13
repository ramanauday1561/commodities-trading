"""Experiment mode "startarget" (13 Nov 2026, asked by the owner: "when a pick is held for 30 minutes, why not sell it
when it has made some profit?"): ways to take profit on the automatic * picks, tested before the order server changes.

The rule today (orders_server.Auto): the at-the-money option of the next expiry on the lean's side, 1 lot, a stop 10%
under the buy price, sold after 30 minutes, no profit target. The variants, each with the same 30-minute limit:
  T10 / T15 / T20 / T30  a target: sold as soon as the option is up 10 / 15 / 20 / 30% (the 10% stop stays)
  TRAIL10                a trailing stop: always 10% under the highest price since the buy (starts as today's stop)
  BE10                   breakeven: the stop moves up to the buy price once the option has been 10% up

Data, two layers (as star_rules_study, whose functions this reuses):
  1. Kite's real 5-minute option candles (options-live, from 4 Nov 2026) with the * leans the page published
     (scoreboard live/<day>.json): bought at the open of the 5-minute candle at the lean, out at the close of the
     candle 25 minutes later at the latest. Inside a candle the order of its high and low is unknown, so a candle that
     reaches both the stop and the target counts as the stop (the worse one). A target sells at the target (or the
     candle's open if it opened above it); a stop at the stop (or the open if it opened below). A trailing or
     breakeven stop only uses highs of earlier candles. Rs120 a lot a round trip for costs.
  2. Nine years (2017-2026) of walk-forward * leans, priced as star_hold_study (b x NIFTY's move on the lean's side +
     a x 10-minute steps - 1.85 points), premium 0.8% of NIFTY, checked at the three 10-minute closes. Learned from
     star_rules_study: a stop seen at a close is booked at that close's value (it can be below the stop), never at
     exactly the stop; a target seen at a close is booked at exactly the target (a limit order would sell there).
     Touches inside a 10-minute candle are missed both ways.

Rule, fixed before the run: a variant replaces today's rule only if (1) on the real option candles it makes more in
total than today's rule and does at least as well on at least 4 of the 5+ trading days with * picks, and (2) in the
nine-year layer it makes more a trade than today's rule on average, in both halves of the years, since 2022 and in at
least 7 of the 10 years. Passing would make the automatic picks lose less (or win more) in the test; it is not proof
they earn (that also needs leanfilter_study.passes on the variant's nine-year trades, reported). Nothing changes on the
order server by this study; the owner decides.

Result (run 13 Nov 2026; real candles: 40 * picks on 4, 5, 6, 9 and 11 Nov; nine years: * leans 2017-01-02 to
2026-11-12, pricing b 0.564, a -0.29 from 468 Kite quote pairs). Rs a lot after costs.
                      real candles (40 picks)            nine years
  today (10% stop)    +13,334 (+333 a pick, 19 won)      -81 a trade, 1 of 10 years up
  T10                 +10,108 (24 won), 3 of 5 days      -258, worse in 10 of 10 years       FAILS
  T15                 +11,484, 3 of 5 days               -203, worse in 10 of 10              FAILS
  T20                 +12,591, 3 of 5 days               -170, worse in 10 of 10              FAILS
  T30                 +12,854, 3 of 5 days               -132, worse in 9 of 10               FAILS
  TRAIL10             +11,654, 3 of 5 days               -79 (+1.4 vs today, 7 of 10 years)   FAILS (real candles worse)
  BE10                +15,464 (16 won), 4 of 5 days      -79 (+1.1, 5 of 10 years)            FAILS (nine years)
  NONE PASSES. A target wins more often but cuts the big moves the * picks need: over nine years every target loses more
  than today's rule, in nearly every year. The trailing stop and the breakeven stop change almost nothing over nine
  years (about Rs1 a trade) and disagree with the 5 real days. Today's rule stays; every rule loses over nine years.
"""
import csv
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import star_rules_study as sr

STOP = 0.10
RULES = {"today (10% stop)": {}, "T10": {"target": 0.10}, "T15": {"target": 0.15}, "T20": {"target": 0.20},
         "T30": {"target": 0.30}, "TRAIL10": {"trail": 0.10}, "BE10": {"breakeven": 0.10}}
LOT, RS_COST, PREM_PCT = 65, 120, 0.008


# ---------------------------------------------------------------- layer 1: Kite's real option candles
def bars_for(rows, day, at, lean, spot):
    """The six 5-minute candles of the pick's option (the lean's 30 minutes), or None."""
    side = "CE" if lean == "up" else "PE"
    exps = sorted({r["expiry"] for r in rows if r["expiry"] > day})
    if not exps:
        return None
    cand = [r for r in rows if r["expiry"] == exps[0] and r["type"] == side]
    if not cand:
        return None
    strike = min({float(r["strike"]) for r in cand}, key=lambda k: abs(k - spot))
    t0 = datetime.strptime(f"{day} {at}", "%Y-%m-%d %H:%M")
    want = [(t0 + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M") for i in range(6)]
    got = {r["datetime"]: r for r in cand if float(r["strike"]) == strike and r["datetime"] in want}
    if want[0] not in got or want[-1] not in got:
        return None
    return [{k: float(got[t][k]) for k in ("open", "high", "low", "close")} for t in want if t in got]


def run_rule(bars, rule):
    """Rs a lot after costs for one pick under one rule (see the docstring for the order inside a candle)."""
    entry = bars[0]["open"]
    stop = entry * (1 - STOP)
    target = entry * (1 + rule["target"]) if rule.get("target") else None
    peak = entry
    out = bars[-1]["close"]
    for b in bars:
        if b["low"] <= stop:                                   # the stop first: the worse case
            out = min(stop, b["open"])
            break
        if target and b["high"] >= target:
            out = max(target, b["open"])
            break
        peak = max(peak, b["high"])                            # moves the stop for the next candle only
        if rule.get("trail"):
            stop = max(stop, peak * (1 - rule["trail"]))
        if rule.get("breakeven") and peak >= entry * (1 + rule["breakeven"]):
            stop = max(stop, entry)
    return round((out - entry) * LOT - RS_COST)


def layer1(store_dir, optlive_dir):
    trades = {k: [] for k in RULES}
    cache = {}
    for day, at, lean, spot in sr.star_leans(store_dir):
        path = os.path.join(optlive_dir, "candles", f"{day}.csv")
        if not os.path.exists(path):
            continue
        rows = cache.setdefault(day, list(csv.DictReader(open(path))))
        bars = bars_for(rows, day, at, lean, spot)
        if not bars:
            continue
        for name, rule in RULES.items():
            trades[name].append({"day": day, "at": at, "rs": run_rule(bars, rule)})
    days = sorted({t["day"] for t in trades["today (10% stop)"]})
    base = {d: sum(t["rs"] for t in trades["today (10% stop)"] if t["day"] == d) for d in days}
    out = {"days": days, "picks": len(trades["today (10% stop)"]), "rules": {}}
    for name, v in trades.items():
        per = {d: sum(t["rs"] for t in v if t["day"] == d) for d in days}
        out["rules"][name] = {"total_rs": int(sum(t["rs"] for t in v)), "rs_per_pick": int(round(np.mean([t["rs"] for t in v]))) if v else None,
                              "won": sum(t["rs"] > 0 for t in v), "by_day": per,
                              "days_at_least_today": sum(per[d] >= base[d] for d in days)}
    return out


# ---------------------------------------------------------------- layer 2: nine years
def nine_year(t, b, a):
    import star_hold_study as sh
    t = t[~((t["d"] >= sh.CAS_FROM) & (t["k"] >= sh.CAS_K))].sort_values(["d", "k"])
    steps = [sh.forward(t, j)[0] for j in range(1, 4)]
    s = t["star"].values & steps[-1].notna().values
    side = np.sign(t["pred"].values[s])
    price = t["price"].values[s]
    prem = PREM_PCT * price
    opt = np.column_stack([b * side * steps[j].values[s] * price + a * (j + 1) for j in range(3)])   # option points vs the buy
    out = pd.DataFrame({"year": t["year"].values[s]})
    for name, rule in RULES.items():
        val = opt[:, -1].copy()
        done = np.zeros(len(opt), bool)
        stop = -STOP * prem
        peak = np.zeros(len(opt))
        for j in range(3):
            v = opt[:, j]
            hit_stop = ~done & (v <= stop)
            val = np.where(hit_stop, v, val)                       # booked at the close it is seen at
            done |= hit_stop
            if rule.get("target"):
                hit_t = ~done & (v >= rule["target"] * prem)
                val = np.where(hit_t, rule["target"] * prem, val)  # a limit order sells at the target
                done |= hit_t
            peak = np.maximum(peak, v)
            if rule.get("trail"):
                stop = np.maximum(stop, (prem + peak) * (1 - rule["trail"]) - prem)
            if rule.get("breakeven"):
                stop = np.where(peak >= rule["breakeven"] * prem, np.maximum(stop, 0.0), stop)
        out[name] = (val - 1.85) * LOT
    return out


def layer2(p):
    yrs = p["year"]
    base = p["today (10% stop)"]
    out = {}
    for name in RULES:
        v = p[name]
        r = {"rs_per_trade": int(round(v.mean())), "years_up": f"{int((v.groupby(yrs).mean() > 0).sum())}/{yrs.nunique()}",
             "earns": sr.earns(v, yrs)["earns_after_costs"]}
        if name != "today (10% stop)":
            r["vs_today"] = sr.compare(v, base, yrs)
        out[name] = r
    return out


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        import nextcandle_study as ns
        optlive = os.environ.get("OPTLIVE_DIR", "optlive")
        out = {"layer1_real_options": layer1(os.environ.get("STORE_DIR", "store"), optlive)}
        cal = lf.calibrate(optlive)
        b, a = (cal["b"], cal["a"]) if cal.get("pairs", 0) >= 100 else (0.5, 0.0)
        df = ns.rows(*(intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), k) for k in ("nifty", "banknifty", "vix")), h=1)
        t = lf.walk_forward(df)
        out["pricing"] = {"b": b, "a": a, "pairs": cal.get("pairs", 0)}
        out["from"], out["to"] = str(t["d"].min()), str(t["d"].max())
        out["layer2_nine_years"] = layer2(nine_year(t, b, a))
        l1, l2 = out["layer1_real_options"]["rules"], out["layer2_nine_years"]
        need = min(4, len(out["layer1_real_options"]["days"]))
        out["passes"] = [k for k in RULES if k != "today (10% stop)" and l1[k]["total_rs"] > l1["today (10% stop)"]["total_rs"]
                         and l1[k]["days_at_least_today"] >= need and l2[k]["vs_today"]["passes"]]
        print("STUDY startarget " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY startarget failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
