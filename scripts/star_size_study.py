"""Experiment mode "starsize" (17 Nov 2026, asked by the owner): trade a * lean only when a big move is expected, and
with a cheaper strike.

Why: a * lean expects NIFTY to move about 2 points its way; an at-the-money option moves about half of that, while a
round trip costs about Rs120 a lot, so even a right lean rarely pays (every test: about -Rs50 to -80 a pick). The
app's expected-move size (movesize_study) is the one model that passed its test. If the size of the coming move is
big, a right lean can be worth more than the cost. The owner also chose cheaper strikes (one step, 50 points, out of
the money), so that two picks fit in the app's Rs17,062.60.

Variants (each with the server's rule: 1 lot, a stop 10% under the price, out after 30 minutes):
  strike  ATM (today) or OTM1 (the next strike out of the money: CALL 50 points above, PUT 50 below)
  size    all * leans, or only when the expected 10-minute move (size_pts) is >= 20, 25 or 30 NIFTY points
Pricing, as star_target_study's nine-year layer (stops booked at the 10-minute close they are seen at), with each
strike's own numbers from Kite's saved quotes (options-live snapshots): b (the option's share of NIFTY's move on its
side), a (points per 10 minutes besides that) and the premium as a share of NIFTY. Costs 1.85 option points a round
trip for both strikes (charges are mostly per order). A check on Kite's real 5-minute option candles (the published *
leans since 4 Nov, their own size) is reported as information.

Rule, fixed before the run: a variant is worth trading only if its nine-year trades earn after costs
(leanfilter_study.passes: 300+ trades, on average, in both halves of the years, since 2022 and in 7 of 10 years).
Nine combinations are tried, so that strict rule is the bar. If none passes, the honest answer is that no size or
strike makes the * leans pay; the owner decides what the server does either way (the cheaper strike is a separate
switch on the server, AUTO_STRIKE).

Result (run 17 Nov 2026; nine years: * leans 2017-01-02 to 2026-11-12; strike numbers from 612 Kite quote pairs each:
ATM b 0.554, a -0.21, premium 0.695% of NIFTY; OTM1 b 0.497, a -0.16, premium 0.598%). Rs a lot a trade after costs.
                    nine years                                           real candles (4-16 Nov)
  ATM  all          14,411 trades, -70, 1 of 10 years up                 46 picks, +11,741 (lot ~Rs11,431)
  ATM  >=20 pts      3,428 trades, -40, 3 of 9                           27 picks, +14,670
  ATM  >=25 pts      1,506 trades, +28, 3 of 7, halves -416 / +47        14 picks,  +7,369
  ATM  >=30 pts        622 trades, +14, 3 of 6, halves +432 / -75         2 picks,  +6,686
  OTM1 all          14,411 trades, -71, 1 of 10                          46 picks, +11,231 (lot ~Rs9,764)
  OTM1 >=20 pts      3,428 trades, -44, 3 of 9                           27 picks, +13,698
  OTM1 >=25 pts      1,506 trades, +17, 3 of 7, halves -384 / +35        14 picks,  +7,041
  OTM1 >=30 pts        622 trades,  +9, 3 of 6, halves +380 / -72         2 picks,  +6,198
  NONE PASSES. A big expected move (25+ points) turns the average slightly positive, but it is up in only 3 of 7 years
  and the halves disagree: too few and too uneven to trust (the size model only predicts that big on a few days a year).
  OTM1 does as well as ATM (within Rs10 a trade) but costs only ~Rs1,700 less a lot, so two picks still do not fit in
  Rs17,062.60 (two OTM1 lots ~Rs19,500). Nothing changes by this study; AUTO_STRIKE on the server is the owner's switch.
"""
import csv
import glob
import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import star_rules_study as sr

STEP, LOT, COST, STOP, RS_COST = 50, 65, 1.85, 0.10, 120
SIZES = {"all": 0, ">=20 pts": 20, ">=25 pts": 25, ">=30 pts": 30}
STRIKES = {"ATM": 0, "OTM1": 1}


def _mins(t):
    return int(t[:2]) * 60 + int(t[3:5])


# ---------------------------------------------------------------- each strike's numbers from Kite's quotes
def strike_numbers(optlive_dir, off):
    """b, a (as leanfilter_study.calibrate) and the premium share of NIFTY, for the strike `off` steps out of the money."""
    pairs, prem = [], []
    for path in sorted(glob.glob(os.path.join(optlive_dir, "snapshots", "*.csv"))):
        day = os.path.basename(path)[:-4]
        runs, spot = {}, {}
        with open(path) as f:
            for r in csv.DictReader(f):
                try:
                    runs.setdefault(r["at"], {})[(r["expiry"], float(r["strike"]), r["type"])] = float(r["ltp"])
                    spot[r["at"]] = float(r["spot"])
                except (KeyError, TypeError, ValueError):
                    continue
        times = sorted(runs, key=_mins)
        for t0, t1 in zip(times, times[1:]):
            if not 8 <= _mins(t1) - _mins(t0) <= 14 or t0 not in spot or t1 not in spot:
                continue
            exps = sorted({k[0] for k in runs[t0] if k[0] > day})
            if not exps:
                continue
            atm = float(round(spot[t0] / STEP) * STEP)
            for typ, side in (("CE", 1), ("PE", -1)):
                key = (exps[0], atm + side * off * STEP, typ)
                if key in runs[t0] and key in runs[t1]:
                    pairs.append((side * (spot[t1] - spot[t0]), runs[t1][key] - runs[t0][key]))
                    prem.append(runs[t0][key] / spot[t0])
    if len(pairs) < 100:
        return None
    x, y = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
    b, a = np.polyfit(x, y, 1)
    return {"b": round(float(b), 3), "a": round(float(a), 2), "prem_pct": round(float(np.median(prem)), 5), "pairs": len(pairs)}


# ---------------------------------------------------------------- nine years
def nine_year(t, nums):
    """Per * lean: year, size_pts and Rs a lot after costs for each strike."""
    import star_hold_study as sh
    t = t[~((t["d"] >= sh.CAS_FROM) & (t["k"] >= sh.CAS_K))].sort_values(["d", "k"])
    steps = [sh.forward(t, j)[0] for j in range(1, 4)]
    s = t["star"].values & steps[-1].notna().values
    side = np.sign(t["pred"].values[s])
    price = t["price"].values[s]
    out = pd.DataFrame({"year": t["year"].values[s], "size": t["size_pts"].values[s]})
    for name, n in nums.items():
        prem = n["prem_pct"] * price
        opt = np.column_stack([n["b"] * side * steps[j].values[s] * price + n["a"] * (j + 1) for j in range(3)])
        hit = opt <= -STOP * prem[:, None]
        first = np.where(hit.any(axis=1), hit.argmax(axis=1), -1)
        val = np.where(first >= 0, opt[np.arange(len(opt)), np.maximum(first, 0)], opt[:, -1])
        out[name] = (val - COST) * LOT
    return out


# ---------------------------------------------------------------- Kite's real candles
def real_candles(store_dir, optlive_dir):
    leans = []
    for f in sorted(glob.glob(os.path.join(store_dir, "live", "*.json"))):
        day = os.path.basename(f)[:-5]
        if day < "2026-11-04":
            continue
        d = json.load(open(f))
        closes = {datetime.utcfromtimestamp(c["time"]).strftime("%H:%M"): c["close"] for c in d.get("candles") or []}
        for x in d.get("leans") or []:
            before = [t for t in closes if t < x["at"]]
            if x.get("confident") and x["at"] <= "15:05" and before:
                leans.append((day, x["at"], x["lean"], closes[max(before)], x.get("size") or 0))
    out = {f"{k} {s}": [] for k in STRIKES for s in SIZES}
    cache = {}
    for day, at, lean, spot, size in leans:
        path = os.path.join(optlive_dir, "candles", f"{day}.csv")
        if not os.path.exists(path):
            continue
        rows = cache.setdefault(day, list(csv.DictReader(open(path))))
        typ = "CE" if lean == "up" else "PE"
        exps = sorted({r["expiry"] for r in rows if r["expiry"] > day})
        if not exps:
            continue
        for kname, off in STRIKES.items():
            strike = float(round(spot / STEP) * STEP) + (1 if typ == "CE" else -1) * off * STEP
            t0 = datetime.strptime(f"{day} {at}", "%Y-%m-%d %H:%M")
            want = [(t0 + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M") for i in range(6)]
            got = {r["datetime"]: r for r in rows if r["expiry"] == exps[0] and r["type"] == typ and float(r["strike"]) == strike and r["datetime"] in want}
            if want[0] not in got or want[-1] not in got:
                continue
            entry = float(got[want[0]]["open"])
            outp = float(got[want[-1]]["close"])
            for tm in want:
                if tm in got and float(got[tm]["low"]) <= entry * (1 - STOP):
                    outp = min(entry * (1 - STOP), float(got[tm]["open"]))
                    break
            rs = round((outp - entry) * LOT - RS_COST)
            for sname, smin in SIZES.items():
                if size >= smin:
                    out[f"{kname} {sname}"].append({"day": day, "rs": rs, "cost": round(entry * LOT)})
    return {k: {"picks": len(v), "total_rs": int(sum(x["rs"] for x in v)), "won": sum(x["rs"] > 0 for x in v),
                "lot_cost": int(np.median([x["cost"] for x in v])) if v else None} for k, v in out.items()}


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        import nextcandle_study as ns
        optlive = os.environ.get("OPTLIVE_DIR", "optlive")
        nums = {k: strike_numbers(optlive, off) for k, off in STRIKES.items()}
        out = {"strike_numbers": nums}
        df = ns.rows(*(intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), k) for k in ("nifty", "banknifty", "vix")), h=1)
        t = lf.walk_forward(df)
        out["from"], out["to"] = str(t["d"].min()), str(t["d"].max())
        p = nine_year(t, {k: v for k, v in nums.items() if v})
        res = {}
        for k in STRIKES:
            if k not in p:
                continue
            for sname, smin in SIZES.items():
                m = p["size"] >= smin
                r = sr.earns(p.loc[m, k], p.loc[m, "year"])
                yrs = p.loc[m, k].groupby(p.loc[m, "year"]).mean()
                r["halves"] = [int(yrs.iloc[:len(yrs) // 2].mean()), int(yrs.iloc[len(yrs) // 2:].mean())]
                r["since_2022"] = int(p.loc[m & (p["year"] >= 2022), k].mean())
                res[f"{k} {sname}"] = r
        out["nine_years"] = res
        out["real_candles"] = real_candles(os.environ.get("STORE_DIR", "store"), optlive)
        out["passes"] = [k for k, v in res.items() if v["earns_after_costs"]]
        print("STUDY starsize " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY starsize failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
