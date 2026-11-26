"""Experiment mode "starlate" (26 Nov 2026, asked by the owner after the 26 Nov day): should the automatic * picks stop
taking new picks after 14:35?

What happened: four real picks (two strikes out, 1 lot, 25+ points expected), all CALLs on an up day, none stopped
out: 10:15 +Rs4,131, 14:05 +2,119, 14:25 +1,433 (before charges), and the 14:45 pick, held to the 15:15 exit, -Rs494.
Since 3 Aug 2026 NSE closes by auction: NIFTY stands still from 15:15, so the server sells everything at 15:15 and a
pick bought at 14:45 or 14:55 gets only 30 or 20 minutes, the last of the day.

The rule tested (fixed before the run): NO new * pick from the 14:45 lean on (the 14:45 and 14:55 leans are skipped;
the server's last entry today is the 14:55 lean). Everything else as the server: * leans of 25+ points expected, the
next expiry after today, 1 lot, 10% stop, out after 30 minutes or at 15:15.

Data, two layers (as studies starstop and startrend):
  1. Kite's real 5-minute option candles (options-live, 4 Nov 2026 on) with the * leans the page published, at the
     money (star_stop_study.real_pick).
  2. Nine years: the * leans as leanfilter_study.walk_forward makes them, priced from NIFTY's 5-minute candles with the
     stop seen inside each candle (star_stop_study.path_pick), premium = layer 1's median, b and a from Kite's quotes.

Pass rule, fixed before the run. The cut passes only if the * leans it KEEPS earn more a trade than all the server's
* leans (layer 2): on average, in both halves of the years, since 2022, and in at least 70% of the years with trades;
AND on layer 1 the leans it skips lost money in total. Whether the kept leans earn after costs is reported and does
not change the verdict. A pass goes to the owner before the server changes.

RESULT (run 26 Nov 2026 with that day's candles, locally on the data branches; walk-forward * leans 2017-01-02 to
2026-11-26; b 0.549, a -0.16; premium 0.878% of NIFTY): DOES NOT PASS.
  Layer 1 (real option candles, 52 picks at the money, 4-26 Nov): all +Rs2,329; kept 47 +Rs1,697; the 5 late picks
  skipped made +Rs632 (6 Nov 14:55 +3,403, 20 Nov 14:55 +124, 23 Nov 14:45 -1,888 and 14:55 -640, 26 Nov 14:45 -367).
  Layer 2 (nine years, 1,561 trades): all +Rs31 a trade, kept +Rs45, skipped -Rs31; better by 14.1 on average, since
  2022 +18.0, but the first half -5.9 / second +24.9 and better in only 4 of 7 years (need 5): 2020 +3, 2021 -46,
  2022 +26, 2023 +50, 2024 +66, 2025 -13, 2026 -3. The kept leans do not earn after costs (3 of 7 years up).
  The late leans lose a little on average but not steadily; the server keeps entering until the 14:55 lean.
"""
import csv
import json
import os

import star_stop_study as ss
import star_trend_study as st

LATE_K = 32                                     # the 14:45 lean (09:25 + 10 x 32 minutes)


def late(at=None, k=None):
    """True for a lean the cut skips: the 14:45 lean or later (by 'HH:MM' or by row k)."""
    return bool(k >= LATE_K) if k is not None else at >= "14:45"


def layer1(store_dir, optlive_dir):
    res, cache = [], {}
    for day, at, lean, spot, size in ss.star_leans(store_dir):
        path = os.path.join(optlive_dir, "candles", f"{day}.csv")
        if not os.path.exists(path):
            continue
        if day not in cache:
            with open(path) as fh:
                cache[day] = list(csv.DictReader(fh))
        r = ss.real_pick(cache[day], day, at, lean, spot, 0.10)
        if r:
            res.append({"day": day, "at": at, "rs": r["rs"], "skip": late(at=at)})
    sk, kept = [x for x in res if x["skip"]], [x for x in res if not x["skip"]]
    return {"trades": len(res), "all_rs": int(sum(x["rs"] for x in res)),
            "kept": {"trades": len(kept), "rs": int(sum(x["rs"] for x in kept))},
            "skipped": {"trades": len(sk), "rs": int(sum(x["rs"] for x in sk)), "won": sum(x["rs"] > 0 for x in sk),
                        "picks": [f"{x['day']} {x['at']} {x['rs']:+d}" for x in sk]}}


def nine_year(t, nifty, b, a, prem_pct):
    import pandas as pd
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
        out.append({"year": r.year, "rs": rs, "skip": late(k=int(r.k))})
    return pd.DataFrame(out)


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        import nextcandle_study as ns
        optlive, store = os.environ.get("OPTLIVE_DIR", "optlive"), os.environ.get("STORE_DIR", "store")
        nifty, bank, vix = (intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), k) for k in ("nifty", "banknifty", "vix"))
        l1 = layer1(store, optlive)
        prem = ss.layer1(store, optlive)["premium_pct_median"] or 0.8
        cal = lf.calibrate(optlive)
        b, a = (cal["b"], cal["a"]) if cal.get("pairs", 0) >= 100 else (0.5, 0.0)
        t = lf.walk_forward(ns.rows(nifty, bank, vix, h=1))
        l2 = st.test(nine_year(t, nifty, b, a, prem / 100))
        out = {"pricing": {"b": b, "a": a, "premium_pct": prem}, "from": str(t["d"].min()), "to": str(t["d"].max()),
               "layer1_real_options": l1, "layer2_nine_years": l2}
        out["passes"] = bool(l2["passes"] and l1["skipped"]["trades"] and l1["skipped"]["rs"] < 0)
        print("STUDY starlate " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY starlate failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
