"""Experiment mode "starrules" (12 Nov 2026, asked by the owner): three changes to the automatic * picks, tested before
any of them touches the order server.

The order server's rule today (orders_server.Auto): each new * lean buys the at-the-money option of the next expiry
after today, 1 lot, a stop 10% under the price, out after 30 minutes. On 12 Nov the 09:35 * lean's PUT was stopped
out (-Rs1,405); over 29 Oct - 12 Nov the * leans looked weak before 10:00 and from 12:00 to 14:00 and strong after
14:00 (63 leans, 9 days: too few to act on). The three questions:

  A. The stop. Is a wider stop (15%, 20%, 25%) or none better than 10%? An at-the-money option often moves 5-10% in
     10 minutes on an ordinary NIFTY move, so a 10% stop may close right leans as well as wrong ones.
  B. Skip the early * leans (the 09:25 to 09:55 candles).
  C. The time of day: skip the 12:05 to 13:55 * leans, or keep only the 14:05 to 15:05 ones.

Data, two layers:
  1. Kite's real 5-minute option candles (options-live branch, from 4 Nov 2026) with the * leans the page published
     (scoreboard branch, live/<day>.json). Each pick as the server makes it: the strike nearest NIFTY at the lean,
     the nearest expiry after the day, bought at the open of the 5-minute candle at the lean's time, sold at the close
     of the candle 25 minutes later, or at the stop when a candle's low reaches it (at the candle's open if it opened
     below the stop). Rs120 a lot a round trip for costs (the app's figure). Few trades: information, and part of A's
     rule only.
  2. Nine years (2017-2026) of * leans exactly as star_hold_study / leanfilter_study.walk_forward make them (walk-
     forward by year), held 30 minutes (H3). The option is priced as there: b x NIFTY's move on the lean's side +
     a x 10-minute steps - 1.85 points costs (b, a from Kite's quotes, leanfilter_study.calibrate). The premium is
     PREM_PCT of NIFTY (the median of the real picks above, about 0.8%; fixed here before the run). A stop is hit
     when the option's value at a 10-minute close is down the stop's share of the premium; it is then sold at the stop.
     Checking 10-minute closes only misses lows inside a candle, so this is kind to tight stops.

Rules, fixed before the run (the same strictness as leanfilter_study; every comparison on Rs a lot a trade, after
costs, with the server's 30-minute hold):
  A. A wider stop (or none) replaces 10% only if it beats the 10% stop both (1) in total on the real option candles
     and (2) in the nine-year layer: on average, in both halves of the years, since 2022 and in at least 7 of the 10
     years. If several pass, the one with the best nine-year average.
  B. Skipping the 09:25-09:55 * leans passes only if, in the nine-year layer with the 10% stop, those leans earn less a
     trade than the other * leans on average, in both halves, since 2022 and in at least 7 of the 10 years.
  C. Each window (skip 12:05-13:55; only 14:05-15:05) passes only if the * leans it keeps earn more a trade than all *
     leans on average, in both halves, since 2022 and in at least 7 of the 10 years (nine-year layer, 10% stop).
A passing change would make the automatic picks lose less (or win more) in the test; it is a trade signal only if the
kept leans also earn after costs (leanfilter_study.passes: 300+ trades, on average, both halves, since 2022, 7 of 10
years). Either way the change goes to the owner first; nothing changes on the server by this study.

Result (run 12 Nov 2026 on the intraday-data, options-live and scoreboard branches; * leans 2017-01-02 to
2026-11-12; pricing b 0.564, a -0.09 from 324 Kite quote pairs; the real picks' median premium was 0.801% of NIFTY,
so PREM_PCT 0.8% held). Rs a lot a trade after costs.
  Layer 1, Kite's real option candles (40 * picks, 4-11 Nov, 5 days): stop 10% +Rs13,334 in total (+Rs333 a trade,
    19 won), 15% +Rs20,113, 20% +Rs19,745, 25% +Rs20,791, no stop +Rs21,172 (22 won). With the 10% stop: 09:25-09:55
    -Rs1,210 (8 picks), 12:05-13:55 -Rs1,797 (11), 14:05-15:05 +Rs15,938 (11; most of it on 6 and 11 Nov).
  Layer 2, nine years, as fixed (a stop sells at exactly the stop): 10% +Rs112 (8 of 10 years up), 15% +59, 20% +24,
    25% +3, none -55 (1 of 10).
  A. FAILS: every wider stop is worse than 10% in the nine-year layer (0 of 10 years better), though better on the 40
     real picks. Keep 10%.
  B. FAILS: the early * leans earn Rs24 less a trade than the others, but in only 4 of 10 years (halves -11 / +46).
  C. Skip 12:05-13:55 FAILS (Rs8 worse a trade, 5 of 10 years). Only 14:05-15:05 PASSES as written: Rs138 a trade vs
     Rs112 for all * leans, better in 8 of 10 years, both halves (+25 / +33), since 2022 (+34).
  The check that undoes it (run after, not part of the fixed rule): layer 2's stop is sold at exactly the stop price,
  but the price is only seen at 10-minute closes, so a loser that falls past the stop is still booked at -10%. That
  is what turns -Rs55 (no stop) into +Rs112 (10% stop). Priced at the 10-minute close where the stop is first seen
  instead, every variant loses: 10% stop -Rs46 a trade (1 of 10 years up), 15% -51, 20% -51, 25% -52, no stop -55;
  09:25-09:55 -Rs77, 12:05-13:55 -30, 14:05-15:05 -35 (better than all * leans in only 6 of 10 years, up in 1 of 10).
  So C's pass rests on the kind stop pricing, and the "earns after costs" lines in the output are that artefact too.
  Real fills are between the two (a stop-limit order at the exchange, re-priced after 10 seconds): the true nine-year
  numbers lie somewhere from -Rs46 to +Rs112 a trade, and only 5 real days say which.
  Nothing changes on the order server. The real picks keep being recorded (the Next 10 report card and the Money page);
  re-run this when options-live has about 30 trading days of candles, when layer 1 alone can say more.
"""
import csv
import glob
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

STOPS = {"10%": 0.10, "15%": 0.15, "20%": 0.20, "25%": 0.25, "none": None}
HOLD = 3                                    # 10-minute steps: the server's 30 minutes
RS_COST = 120                               # a round trip, a lot (the app's figure)
LOT = 65
PREM_PCT = 0.008                            # the at-the-money premium as a share of NIFTY (median of the real picks)
EARLY = ("09:25", "09:55")
MIDDAY = ("12:05", "13:55")
LATE = ("14:05", "15:05")


# ---------------------------------------------------------------- layer 1: Kite's real option candles
def star_leans(store_dir, since="2026-11-04"):
    """[(day, 'HH:MM', 'up'|'down', NIFTY at the lean)] for every * lean the page published."""
    out = []
    for f in sorted(glob.glob(os.path.join(store_dir, "live", "*.json"))):
        day = os.path.basename(f)[:-5]
        if day < since:
            continue
        d = json.load(open(f))
        closes = {datetime.fromtimestamp(c["time"], timezone.utc).strftime("%H:%M"): c["close"] for c in d.get("candles") or []}
        for x in d.get("leans") or []:
            if not x.get("confident") or x["at"] > "15:05":
                continue
            before = [t for t in closes if t < x["at"]]
            if before:
                out.append((day, x["at"], x["lean"], closes[max(before)]))
    return out


def real_pick(rows, day, at, lean, spot, stop):
    """Rs a lot after costs for one pick on the day's 5-minute option candles, or None without the candles."""
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
    bars = {r["datetime"]: r for r in cand if float(r["strike"]) == strike and r["datetime"] in want}
    if want[0] not in bars or want[-1] not in bars:
        return None
    entry = float(bars[want[0]]["open"])
    level = entry * (1 - stop) if stop else None
    out = float(bars[want[-1]]["close"])
    for t in want:
        b = bars.get(t)
        if b and level is not None and float(b["low"]) <= level:
            out = min(level, float(b["open"]))
            break
    return {"rs": round((out - entry) * LOT - RS_COST), "entry": entry, "spot": spot}


def layer1(store_dir, optlive_dir):
    leans = star_leans(store_dir)
    by_day = {}
    res = {k: [] for k in STOPS}
    prem = []
    for day, at, lean, spot in leans:
        path = os.path.join(optlive_dir, "candles", f"{day}.csv")
        if not os.path.exists(path):
            continue
        rows = by_day.setdefault(day, list(csv.DictReader(open(path))))
        for name, s in STOPS.items():
            r = real_pick(rows, day, at, lean, spot, s)
            if r:
                res[name].append({"day": day, "at": at, "rs": r["rs"]})
                if name == "10%":
                    prem.append(r["entry"] / spot)
    out = {k: {"trades": len(v), "total_rs": int(sum(x["rs"] for x in v)),
               "rs_per_trade": int(round(np.mean([x["rs"] for x in v]))) if v else None,
               "won": sum(x["rs"] > 0 for x in v)} for k, v in res.items()}
    for name, (lo, hi) in {"early 09:25-09:55": EARLY, "midday 12:05-13:55": MIDDAY, "late 14:05-15:05": LATE}.items():
        v = [x["rs"] for x in res["10%"] if lo <= x["at"] <= hi]
        out["10% " + name] = {"trades": len(v), "total_rs": int(sum(v)), "rs_per_trade": int(round(np.mean(v))) if v else None}
    out["premium_pct_median"] = round(float(np.median(prem)) * 100, 3) if prem else None
    out["days"] = sorted({x["day"] for x in res["10%"]})
    return out


# ---------------------------------------------------------------- layer 2: nine years
def hhmm(k):
    """The candle a row's lean is for: row k makes the lean for 09:25 + 10 k minutes."""
    m = 9 * 60 + 25 + 10 * k
    return f"{m // 60:02d}:{m % 60:02d}"


def nine_year(t, b, a):
    """Per * lean: Rs a lot after costs for each stop, with the lean's candle time and year."""
    import star_hold_study as sh
    t = t[~((t["d"] >= sh.CAS_FROM) & (t["k"] >= sh.CAS_K))].sort_values(["d", "k"])
    steps = [sh.forward(t, j)[0] for j in range(1, HOLD + 1)]
    s = t["star"].values & steps[-1].notna().values
    side = np.sign(t["pred"].values[s])
    price = t["price"].values[s]
    prem = PREM_PCT * price
    opt = np.column_stack([b * side * steps[j].values[s] * price + a * (j + 1) for j in range(HOLD)])
    out = pd.DataFrame({"year": t["year"].values[s], "at": [hhmm(int(k)) for k in t["k"].values[s]]})
    for name, st in STOPS.items():
        val = opt[:, -1].copy()
        if st is not None:
            hit = opt <= -st * prem[:, None]
            first = np.where(hit.any(axis=1), hit.argmax(axis=1), -1)
            val = np.where(first >= 0, -st * prem, val)
        out[name] = (val - 1.85) * LOT
    return out


def compare(x, base, years):
    """x vs base (two Series of Rs a trade, indexed by year): better on average, both halves, since 2022, years."""
    xs, bs = x.groupby(years).mean(), base.groupby(years).mean()
    common = xs.index.intersection(bs.index)
    diff = (xs[common] - bs[common]).sort_index()
    half = len(diff) // 2
    rec = (x[years >= 2022].mean() - base[years >= 2022].mean())
    r = {"better_avg": round(float(x.mean() - base.mean()), 1), "halves": [round(float(diff.iloc[:half].mean()), 1), round(float(diff.iloc[half:].mean()), 1)],
         "since_2022": round(float(rec), 1), "years_better": f"{int((diff > 0).sum())}/{len(diff)}"}
    r["passes"] = bool(r["better_avg"] > 0 and all(h > 0 for h in r["halves"]) and r["since_2022"] > 0 and int((diff > 0).sum()) >= 7)
    return r


def earns(v, years):
    """leanfilter_study.passes on a set of trades in Rs."""
    import leanfilter_study as lf
    yrs = v.groupby(years).mean()
    half = len(yrs) // 2
    r = {"trades": int(len(v)), "pts": float(v.mean()), "halves": [float(yrs.iloc[:half].mean()), float(yrs.iloc[half:].mean())],
         "since_2022": float(v[years >= 2022].mean()) if (years >= 2022).any() else None, "years_up": f"{int((yrs > 0).sum())}/{len(yrs)}"}
    return {"trades": r["trades"], "rs_per_trade": int(round(r["pts"])), "years_up": r["years_up"], "earns_after_costs": lf.passes(r)}


def layer2(p):
    yrs = p["year"]
    out = {"stops": {}}
    for name in STOPS:
        out["stops"][name] = {"rs_per_trade": int(round(p[name].mean())), "years_up": f"{int((p[name].groupby(yrs).mean() > 0).sum())}/{yrs.nunique()}",
                              "vs_10%": compare(p[name], p["10%"], yrs) if name != "10%" else None}
    base = p["10%"]
    early = p["at"].between(*EARLY)
    rest = ~early
    out["B_skip_early"] = {"early": {"trades": int(early.sum()), "rs_per_trade": int(round(base[early].mean()))},
                           "others": {"trades": int(rest.sum()), "rs_per_trade": int(round(base[rest].mean()))}}
    # B's test: the early leans earn less than the others, year by year
    ey, oy = base[early].groupby(yrs[early]).mean(), base[rest].groupby(yrs[rest]).mean()
    common = ey.index.intersection(oy.index)
    diff = (oy[common] - ey[common]).sort_index()
    half = len(diff) // 2
    rec = base[rest & (yrs >= 2022)].mean() - base[early & (yrs >= 2022)].mean()
    b = {"others_minus_early": round(float(base[rest].mean() - base[early].mean()), 1),
         "halves": [round(float(diff.iloc[:half].mean()), 1), round(float(diff.iloc[half:].mean()), 1)],
         "since_2022": round(float(rec), 1), "years_worse": f"{int((diff > 0).sum())}/{len(diff)}"}
    b["passes"] = bool(b["others_minus_early"] > 0 and all(h > 0 for h in b["halves"]) and b["since_2022"] > 0 and int((diff > 0).sum()) >= 7)
    out["B_skip_early"]["test"] = b
    out["B_skip_early"]["kept_earns"] = earns(base[rest], yrs[rest])
    out["C"] = {}
    for name, keep in {"skip 12:05-13:55": ~p["at"].between(*MIDDAY), "only 14:05-15:05": p["at"].between(*LATE)}.items():
        ky = base[keep].groupby(yrs[keep]).mean()
        ay = base.groupby(yrs).mean()
        common = ky.index.intersection(ay.index)
        diff = (ky[common] - ay[common]).sort_index()
        half = len(diff) // 2
        c = {"trades": int(keep.sum()), "rs_per_trade": int(round(base[keep].mean())), "all_rs_per_trade": int(round(base.mean())),
             "better_avg": round(float(base[keep].mean() - base.mean()), 1),
             "halves": [round(float(diff.iloc[:half].mean()), 1), round(float(diff.iloc[half:].mean()), 1)],
             "since_2022": round(float(base[keep & (yrs >= 2022)].mean() - base[yrs >= 2022].mean()), 1),
             "years_better": f"{int((diff > 0).sum())}/{len(diff)}"}
        c["passes"] = bool(c["better_avg"] > 0 and all(h > 0 for h in c["halves"]) and c["since_2022"] > 0 and int((diff > 0).sum()) >= 7)
        c["kept_earns"] = earns(base[keep], yrs[keep])
        out["C"][name] = c
    return out


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        import nextcandle_study as ns
        optlive = os.environ.get("OPTLIVE_DIR", "optlive")
        store = os.environ.get("STORE_DIR", "store")
        out = {"layer1_real_options": layer1(store, optlive)}
        cal = lf.calibrate(optlive)
        b, a = (cal["b"], cal["a"]) if cal.get("pairs", 0) >= 100 else (0.5, 0.0)
        df = ns.rows(*(intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), k) for k in ("nifty", "banknifty", "vix")), h=1)
        t = lf.walk_forward(df)
        out["pricing"] = {"b": b, "a": a, "pairs": cal.get("pairs", 0), "premium_pct": PREM_PCT * 100}
        out["from"], out["to"] = str(t["d"].min()), str(t["d"].max())
        out["layer2_nine_years"] = layer2(nine_year(t, b, a))
        l1, l2 = out["layer1_real_options"], out["layer2_nine_years"]
        out["A_passes"] = [k for k, v in l2["stops"].items() if v["vs_10%"] and v["vs_10%"]["passes"]
                           and l1[k]["trades"] and l1[k]["total_rs"] > l1["10%"]["total_rs"]]
        out["B_passes"] = l2["B_skip_early"]["test"]["passes"]
        out["C_passes"] = [k for k, v in l2["C"].items() if v["passes"]]
        print("STUDY starrules " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY starrules failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
