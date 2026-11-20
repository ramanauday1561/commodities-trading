"""Experiment mode "starstop" (20 Nov 2026, asked by the owner after the 20 Nov 09:35 pick): the automatic * picks'
stop width, tested with what happens INSIDE each 5-minute candle.

What happened: the 09:35 * lean (up, expected move 27.6 points, so the server bought it under AUTO_MIN_SIZE 25) was
right: NIFTY rose ~70 points in 20 minutes. The 25,450 CALL was bought near Rs125.45, dipped to Rs109.8 (-12.5%)
inside the first 5-minute candle, the 10% stop sold it (about -Rs810 after charges), and the CALL then ran to Rs168;
held the planned 30 minutes it would have sold near Rs147 (about +Rs1,287 after Rs120 of costs).

Study starrules (12 Nov) tested 15 / 20 / 25% and no stop, but its nine-year layer saw only 10-minute closes, so it
could not see a stop being hit inside a candle (it booked such trades either at exactly the stop, kind to tight stops,
or at the next 10-minute close, unkind). The stored 5-minute history has each candle's high and low, so this study
prices the stop inside the candle.

The rule tested is the server's as it runs today (orders_server.Auto with AUTO_MIN_SIZE 25): a * lean with an expected
move of at least 25 NIFTY points, the at-the-money option of the next expiry, 1 lot, bought when the lean's candle
starts, sold 30 minutes later (no later than 15:15) or at the stop. Stops tried: 10% (today), 15%, 20%, 25%, none.

Layer 1, Kite's real 5-minute option candles (options-live, 4-20 Nov 2026) with the * leans the page published
(scoreboard live/<day>.json, with their expected move): bought at the open of the 5-minute candle at the lean's time,
sold at the close of the candle 25 minutes later, or at the stop when a candle's low reaches it (at that candle's open
if it opened below the stop). Rs120 a lot a round trip.

Layer 2, nine years (2017-2026): the * leans and expected moves exactly as leanfilter_study.walk_forward makes them
(walk-forward by year), the same 25-point filter. The option is priced from NIFTY's 5-minute candles as
premium + b x (NIFTY's move on the option's side) + a per 10 minutes (b, a from Kite's quotes,
leanfilter_study.calibrate). Inside each 5-minute candle the worst NIFTY price (the low for a CALL, the high for a PUT)
decides the stop; the stop sells at the stop price, or at the candle's open if it opened past the stop. The premium is
PREM of NIFTY: the median entry premium of layer 1's picks (measured in the run, not chosen). 1.85 option points of
costs (Rs120 a lot). Not modelled: the option's curvature (gamma), and the bid-ask spread at the stop.

Rule, fixed before the run (as starrules A): a wider stop (or none) replaces 10% only if it beats 10% both
  (1) in total on layer 1's real option candles, and
  (2) in layer 2 on Rs a lot a trade: on average, in both halves of the years, since 2022, and in at least 7 of the 10
      years.
If several pass, the one with the best layer-2 average. A passing stop is still a loss-reducing change, not a proven
edge: whether the picks earn after costs is reported (leanfilter_study.passes) and does not change the verdict.
"""
import csv
import glob
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

STOPS = {"10%": 0.10, "15%": 0.15, "20%": 0.20, "25%": 0.25, "none": None}
MIN_SIZE, HOLD_BARS, LOT, RS_COST, COST_PTS = 25.0, 6, 65, 120, 1.85
LAST_EXIT = "15:15"
CAS_FROM = pd.Timestamp("2026-08-03").date()


# ---------------------------------------------------------------- layer 1: Kite's real option candles
def star_leans(store_dir, since="2026-11-04"):
    """[(day, 'HH:MM', 'up'|'down', NIFTY at the lean, expected move)] for the published * leans of 25+ points."""
    out = []
    for f in sorted(glob.glob(os.path.join(store_dir, "live", "*.json"))):
        day = os.path.basename(f)[:-5]
        if day < since:
            continue
        with open(f) as fh:
            d = json.load(fh)
        closes = {datetime.fromtimestamp(c["time"], timezone.utc).strftime("%H:%M"): c["close"] for c in d.get("candles") or []}
        for x in d.get("leans") or []:
            size = float(x.get("size") or 0)
            if not x.get("confident") or x["at"] > "14:55" or size < MIN_SIZE:
                continue
            before = [t for t in closes if t < x["at"]]
            if before:
                out.append((day, x["at"], x["lean"], closes[max(before)], size))
    return out


def real_pick(rows, day, at, lean, spot, stop):
    """{'rs', 'entry'} for one pick on the day's 5-minute option candles, or None without the candles."""
    side = "CE" if lean == "up" else "PE"
    exps = sorted({r["expiry"] for r in rows if r["expiry"] > day})
    cand = [r for r in rows if exps and r["expiry"] == exps[0] and r["type"] == side]
    if not cand:
        return None
    strike = min({float(r["strike"]) for r in cand}, key=lambda k: abs(k - spot))
    t0 = datetime.strptime(f"{day} {at}", "%Y-%m-%d %H:%M")
    want = [(t0 + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M") for i in range(HOLD_BARS)]
    want = [w for w in want if w[11:] < LAST_EXIT]                     # out by 15:15
    bars = {r["datetime"]: r for r in cand if float(r["strike"]) == strike and r["datetime"] in want}
    if not want or want[0] not in bars or want[-1] not in bars:
        return None
    entry = float(bars[want[0]]["open"])
    level = entry * (1 - stop) if stop else None
    out = float(bars[want[-1]]["close"])
    for t in want:
        b = bars.get(t)
        if b and level is not None and float(b["low"]) <= level:
            out = min(level, float(b["open"]))
            break
    return {"rs": round((out - entry) * LOT - RS_COST), "entry": entry}


def layer1(store_dir, optlive_dir):
    res, prem, rows_by_day = {k: [] for k in STOPS}, [], {}
    for day, at, lean, spot, size in star_leans(store_dir):
        path = os.path.join(optlive_dir, "candles", f"{day}.csv")
        if not os.path.exists(path):
            continue
        if day not in rows_by_day:
            with open(path) as fh:
                rows_by_day[day] = list(csv.DictReader(fh))
        for name, s in STOPS.items():
            r = real_pick(rows_by_day[day], day, at, lean, spot, s)
            if r:
                res[name].append({"day": day, "at": at, "lean": lean, "rs": r["rs"]})
                if name == "10%":
                    prem.append(r["entry"] / spot)
    out = {k: {"trades": len(v), "total_rs": int(sum(x["rs"] for x in v)), "won": sum(x["rs"] > 0 for x in v),
               "rs_per_trade": int(round(np.mean([x["rs"] for x in v]))) if v else None} for k, v in res.items()}
    out["picks_10%"] = res["10%"]
    out["premium_pct_median"] = round(float(np.median(prem)) * 100, 3) if prem else None
    return out


# ---------------------------------------------------------------- layer 2: nine years, inside each 5-minute candle
def bars_after(day_bars, k):
    """The six 5-minute candles after row k's close (the 30 minutes held), cut at 15:15, or None."""
    t = day_bars.index
    start = pd.Timestamp(t[0].date()) + pd.Timedelta(hours=9, minutes=25 + 10 * int(k))
    w = day_bars[(t >= start) & (t < start + pd.Timedelta(minutes=5 * HOLD_BARS))]
    w = w[w.index.strftime("%H:%M") < LAST_EXIT]
    return w if len(w) else None


def path_pick(entry, side, w, prem, b, a, stop):
    """Option points (before costs) for one pick: stop inside a 5-minute candle, else the last candle's close."""
    level = -stop * prem if stop is not None else None
    for i, (_, r) in enumerate(w.iterrows()):
        steps = (i + 1) / 2                                         # 10-minute steps of time decay
        worst = (r["Low"] - entry) if side > 0 else (entry - r["High"])
        opn = side * (r["Open"] - entry)
        if level is not None and b * worst + a * steps <= level:
            return min(level, b * opn + a * steps)                 # through the stop: at the open if it gapped past
    last = w.iloc[-1]
    return b * side * (last["Close"] - entry) + a * len(w) / 2


def nine_year(t, nifty, b, a, prem_pct):
    """Per * lean of 25+ points: year and Rs a lot after costs for each stop."""
    t = t[t["star"] & (t["size_pts"] >= MIN_SIZE) & (t["k"] <= 33)]          # 33: the 14:55 lean (no entry after 15:00)
    t = t[~((t["d"] >= CAS_FROM) & (t["k"] >= 35))]
    out = []
    for r in t.itertuples():
        g = nifty.get(r.d)
        if g is None:
            continue
        w = bars_after(g, r.k)
        if w is None:
            continue
        side = 1 if r.pred > 0 else -1
        prem = prem_pct * r.price
        row = {"year": r.year, "d": r.d}
        for name, s in STOPS.items():
            row[name] = (path_pick(r.price, side, w, prem, b, a, s) - COST_PTS) * LOT
        out.append(row)
    return pd.DataFrame(out)


def compare(x, base, years):
    """x vs base (Rs a trade): better on average, in both halves of the years, since 2022, in 7+ of the years."""
    xs, bs = x.groupby(years).mean(), base.groupby(years).mean()
    diff = (xs - bs).sort_index()
    half = len(diff) // 2
    rec = x[years >= 2022].mean() - base[years >= 2022].mean()
    r = {"better_avg": round(float(x.mean() - base.mean()), 1),
         "halves": [round(float(diff.iloc[:half].mean()), 1), round(float(diff.iloc[half:].mean()), 1)] if half else None,
         "since_2022": round(float(rec), 1), "years_better": f"{int((diff > 0).sum())}/{len(diff)}"}
    r["passes"] = bool(r["better_avg"] > 0 and r["halves"] and all(h > 0 for h in r["halves"]) and r["since_2022"] > 0
                       and int((diff > 0).sum()) >= 7)
    return r


def layer2(p):
    import leanfilter_study as lf
    yrs = p["year"]
    out = {}
    for name in STOPS:
        v = p[name]
        by = v.groupby(yrs).mean()
        half = len(by) // 2
        earn = {"trades": int(len(v)), "pts": float(v.mean()), "halves": [float(by.iloc[:half].mean()), float(by.iloc[half:].mean())],
                "since_2022": float(v[yrs >= 2022].mean()), "years_up": f"{int((by > 0).sum())}/{len(by)}"}
        out[name] = {"trades": int(len(v)), "rs_per_trade": int(round(v.mean())), "years_up": earn["years_up"],
                     "by_year": {str(k): int(round(x)) for k, x in by.items()}, "earns_after_costs": lf.passes(earn),
                     "vs_10%": compare(v, p["10%"], yrs) if name != "10%" else None}
    return out


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        import nextcandle_study as ns
        optlive, store = os.environ.get("OPTLIVE_DIR", "optlive"), os.environ.get("STORE_DIR", "store")
        intra = os.environ.get("INTRADAY_DIR", "intra")
        l1 = layer1(store, optlive)
        cal = lf.calibrate(optlive)
        b, a = (cal["b"], cal["a"]) if cal.get("pairs", 0) >= 100 else (0.5, 0.0)
        prem_pct = (l1["premium_pct_median"] or 0.8) / 100
        nifty, bank, vix = (intraday_data.load(intra, k) for k in ("nifty", "banknifty", "vix"))
        t = lf.walk_forward(ns.rows(nifty, bank, vix, h=1))
        p = nine_year(t, nifty, b, a, prem_pct)
        l2 = layer2(p)
        out = {"pricing": {"b": b, "a": a, "pairs": cal.get("pairs", 0), "premium_pct": round(prem_pct * 100, 3)},
               "from": str(t["d"].min()), "to": str(t["d"].max()),
               "layer1_real_options": {k: v for k, v in l1.items() if k != "picks_10%"}, "layer2_nine_years": l2}
        passing = [k for k in STOPS if k != "10%" and l2[k]["vs_10%"]["passes"]
                   and l1[k]["trades"] and l1[k]["total_rs"] > l1["10%"]["total_rs"]]
        out["passes"] = passing
        out["choice"] = max(passing, key=lambda k: l2[k]["rs_per_trade"]) if passing else "10% (no change)"
        print("STUDY starstop " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY starstop failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
