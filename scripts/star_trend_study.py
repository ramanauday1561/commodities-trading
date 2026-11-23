"""Experiment mode "startrend" (23 Nov 2026, asked by the owner after the 23 Nov day): should the automatic * picks
skip a * lean that bets against a clearly trending day?

What happened: NIFTY opened at 25,929 (gap up) and fell all day to about 25,366 (-1.7% on the day). 21 * leans had an
expected move of 25+ points (the server's AUTO_MIN_SIZE); 17 of them said "up", against the falling day, and 10 of 21
were right. No pick was bought (each cost more than this app's money), but on the day's 10-minute Kite quotes the
server's rule at two strikes out of the money (AUTO_STRIKE=otm2) would have lost about Rs2,858 on 6 picks.

The rule tested (fixed before the run): SKIP a * lean when the day is trending against it:
  at least 30 minutes into the day (3 candles), the day trending (NIFTY's move since the open is at least 40% of the
  distance it has travelled since the open: leanfilter_study.trend_inputs' "er" >= 0.4, the same trend measure as
  study leanfilters F3), and the lean on the other side of the move since the open.
Everything else is the server's rule as it runs (orders_server.Auto): * leans of 25+ points expected, entries until
14:55, the at-the-money option of the next expiry, 1 lot, 10% stop, out after 30 minutes or at 15:15.

Data, two layers (as study starstop, whose pricing this reuses):
  1. Kite's real 5-minute option candles (options-live, 4 Nov 2026 on) with the * leans the page published
     (scoreboard live/<day>.json); the trend measure at each lean from the stored 5-minute NIFTY candles.
  2. Nine years: the * leans as leanfilter_study.walk_forward makes them (walk-forward by year), priced from NIFTY's
     5-minute candles with the stop seen inside each candle (star_stop_study.path_pick), premium = the median entry
     premium of layer 1's picks, b and a from Kite's quotes (leanfilter_study.calibrate). Rs a lot after costs.

Pass rule, fixed before the run. The skip passes only if the * leans it KEEPS earn more a trade than all the server's *
leans (layer 2, 10% stop): on average, in both halves of the years, since 2022, and in at least 70% of the years that
have trades (the 25-point leans come only in busy years); AND on layer 1 the leans it skips lost money in total (so
skipping them would have helped on the real days). Whether the kept leans earn after costs is reported
(leanfilter_study.passes) and does not change the verdict. A pass goes to the owner before the server changes.
"""
import json
import math
import os

import numpy as np
import pandas as pd

import star_stop_study as ss

ER_MIN, MIN_K = 0.4, 2


def against(side, since_open, er, k):
    """True when the lean (side +1 up / -1 down) bets against a trending day."""
    return bool(k >= MIN_K and er >= ER_MIN and since_open != 0 and np.sign(since_open) != side)


# ---------------------------------------------------------------- layer 1
def trend_at(nifty, bank, vix, day):
    """{lean time 'HH:MM': (er, since_open, k)} for one day, from the stored 5-minute candles."""
    import leanfilter_study as lf
    import nextcandle_study as ns
    from datetime import date
    d0 = date.fromisoformat(day)
    keep = sorted(d for d in nifty if d <= d0)[-3:]
    sub = lambda m: {d: m[d] for d in keep if d in m}
    rows = ns.rows(sub(nifty), sub(bank), sub(vix), h=1, live=True)
    if rows.empty:
        return {}
    t = lf.trend_inputs(rows)
    t = t[t["d"] == d0]
    out = {}
    for r in t.itertuples():
        m = 9 * 60 + 25 + 10 * int(r.k)                       # row k makes the lean for the candle at 09:25 + 10k
        out[f"{m // 60:02d}:{m % 60:02d}"] = (float(r.er), float(r.since_open), int(r.k))
    return out


def layer1(store_dir, optlive_dir, nifty, bank, vix):
    import csv
    res, cache, trends = [], {}, {}
    for day, at, lean, spot, size in ss.star_leans(store_dir):
        path = os.path.join(optlive_dir, "candles", f"{day}.csv")
        if not os.path.exists(path):
            continue
        if day not in cache:
            with open(path) as fh:
                cache[day] = list(csv.DictReader(fh))
            trends[day] = trend_at(nifty, bank, vix, day)
        r = ss.real_pick(cache[day], day, at, lean, spot, 0.10)
        tr = trends[day].get(at)
        if r is None or tr is None:
            continue
        side = 1 if lean == "up" else -1
        res.append({"day": day, "at": at, "lean": lean, "rs": r["rs"], "er": round(tr[0], 2),
                    "skip": against(side, tr[1], tr[0], tr[2])})
    skipped = [x for x in res if x["skip"]]
    kept = [x for x in res if not x["skip"]]
    by_day = {}
    for x in res:
        d = by_day.setdefault(x["day"], {"all": 0, "kept": 0, "skipped": 0})
        d["all"] += x["rs"]
        d["skipped" if x["skip"] else "kept"] += x["rs"]
    return {"trades": len(res), "all_rs": int(sum(x["rs"] for x in res)),
            "kept": {"trades": len(kept), "rs": int(sum(x["rs"] for x in kept))},
            "skipped": {"trades": len(skipped), "rs": int(sum(x["rs"] for x in skipped)), "won": sum(x["rs"] > 0 for x in skipped)},
            "by_day": by_day, "picks": res}


# ---------------------------------------------------------------- layer 2
def nine_year(t, nifty, b, a, prem_pct):
    """Per server * lean: year, Rs a lot after costs (10% stop, inside the candle) and whether the skip removes it."""
    t = t[t["star"] & (t["size_pts"] >= ss.MIN_SIZE) & (t["k"] <= 33)]
    t = t[~((t["d"] >= ss.CAS_FROM) & (t["k"] >= 35))]
    out = []
    for r in t.itertuples():
        g = nifty.get(r.d)
        w = ss.bars_after(g, r.k) if g is not None else None
        if w is None:
            continue
        side = 1 if r.pred > 0 else -1
        rs = (ss.path_pick(r.price, side, w, prem_pct * r.price, b, a, 0.10) - ss.COST_PTS) * ss.LOT
        out.append({"year": r.year, "rs": rs, "skip": against(side, r.since_open, r.er, r.k)})
    return pd.DataFrame(out)


def test(p):
    """Kept vs all, Rs a trade: overall, by year (halves, since 2022, share of years better)."""
    import leanfilter_study as lf
    kept, yrs = p[~p["skip"]], p["year"]
    ky, ay = kept.groupby("year")["rs"].mean(), p.groupby("year")["rs"].mean()
    diff = (ky - ay.reindex(ky.index)).sort_index()
    half = len(diff) // 2
    need = math.ceil(0.7 * len(diff))
    r = {"all": {"trades": int(len(p)), "rs_per_trade": int(round(p["rs"].mean()))},
         "kept": {"trades": int(len(kept)), "rs_per_trade": int(round(kept["rs"].mean()))},
         "skipped": {"trades": int(p["skip"].sum()), "rs_per_trade": int(round(p.loc[p["skip"], "rs"].mean())) if p["skip"].any() else None},
         "better_avg": round(float(kept["rs"].mean() - p["rs"].mean()), 1),
         "halves": [round(float(diff.iloc[:half].mean()), 1), round(float(diff.iloc[half:].mean()), 1)] if half else None,
         "since_2022": round(float(kept.loc[kept["year"] >= 2022, "rs"].mean() - p.loc[yrs >= 2022, "rs"].mean()), 1),
         "years_better": f"{int((diff > 0).sum())}/{len(diff)} (need {need})",
         "by_year_kept_minus_all": {str(k): int(round(v)) for k, v in diff.items()}}
    r["passes"] = bool(r["better_avg"] > 0 and r["halves"] and all(h > 0 for h in r["halves"]) and r["since_2022"] > 0
                       and int((diff > 0).sum()) >= need)
    by = kept.groupby("year")["rs"].mean()
    h2 = len(by) // 2
    earn = {"trades": int(len(kept)), "pts": float(kept["rs"].mean()), "halves": [float(by.iloc[:h2].mean()), float(by.iloc[h2:].mean())],
            "since_2022": float(kept.loc[kept["year"] >= 2022, "rs"].mean()), "years_up": f"{int((by > 0).sum())}/{len(by)}"}
    r["kept_earns_after_costs"] = lf.passes(earn)
    r["kept_years_up"] = earn["years_up"]
    return r


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        import nextcandle_study as ns
        optlive, store = os.environ.get("OPTLIVE_DIR", "optlive"), os.environ.get("STORE_DIR", "store")
        nifty, bank, vix = (intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), k) for k in ("nifty", "banknifty", "vix"))
        l1 = layer1(store, optlive, nifty, bank, vix)
        prem = ss.layer1(store, optlive)["premium_pct_median"] or 0.8
        cal = lf.calibrate(optlive)
        b, a = (cal["b"], cal["a"]) if cal.get("pairs", 0) >= 100 else (0.5, 0.0)
        t = lf.walk_forward(ns.rows(nifty, bank, vix, h=1))
        l2 = test(nine_year(t, nifty, b, a, prem / 100))
        out = {"pricing": {"b": b, "a": a, "premium_pct": prem}, "from": str(t["d"].min()), "to": str(t["d"].max()),
               "layer1_real_options": {k: v for k, v in l1.items() if k != "picks"}, "layer2_nine_years": l2}
        out["passes"] = bool(l2["passes"] and l1["skipped"]["trades"] and l1["skipped"]["rs"] < 0)
        print("STUDY startrend " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY startrend failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
