"""Experiment mode "starstreak" (18 Nov 2026, asked by the owner after 18 Nov's three * leans in a row): two changes
to the automatic * picks, tested before the order server changes.

What the owner saw (4-18 Nov, the 19 published * leans of 25+ points, NIFTY points over 30 minutes on the lean's side):
  * Big * leans come in runs: 18 Nov 09:35, 09:45, 09:55 (all up), 6 Nov 14:15-14:55 (four, all down, +41 to +69).
    The app's money (APP_CAPITAL) holds one pick, so the 2nd and later leans of a run are skipped while it is open.
  * The 09:35 * lean of 25+ points was wrong over 30 minutes on 3 of 4 days (-68, -30, -36, +6).
Too few to act on, hence this test.

The rule today (orders_server.Auto with the owner's switches, AUTO_MIN_SIZE 25): a * lean whose expected 10-minute move
is 25+ NIFTY points buys the at-the-money option of the next expiry, 1 lot, a stop 10% under the price, out after 30
minutes; one pick open at a time (the app's money); no new pick after 15:00; every pick out by 15:15.
The variants:
  EXTEND      a new * lean of 25+ points on the open pick's side keeps the pick 30 minutes from that lean (instead of
              being skipped); the stop stays where it is; still out by 15:15
  SKIP_EARLY  no pick from the 09:25 and 09:35 * leans (the first ones of the day, before 09:45)
  BOTH        EXTEND and SKIP_EARLY together

Data, two layers:
  1. Nine years (2017-2026) of walk-forward * leans and expected-move sizes (leanfilter_study.walk_forward, each year
     from models trained only on the years before), stepped day by day in 10-minute candles, one pick at a time as the
     server does. The option is priced as star_size_study's at-the-money strike: b x NIFTY's move on the lean's side
     + a x 10-minute steps - 1.85 points a round trip (b, a from Kite's saved quotes). The stop is checked at each
     10-minute close and booked at that close's value (it can be below the stop: the pessimistic pricing learned in
     star_rules_study). From 3 Aug 2026 no lean is made for the 15:15 candle (the closing auction).
  2. The live days since 4 Nov 2026 (scoreboard live/<day>.json: the * leans the page published, their size, and the
     day's 10-minute NIFTY candles), priced the same way. Information only: about ten days.

Rule, fixed before the run. The unit is Rs a lot a trading day after costs (the variants change how many picks there
are, so a trade is not the unit). A variant replaces today's rule only if, in the nine-year layer, it makes more a day
than today's rule on average, in both halves of the years, since 2022 and in at least 7 of the 10 years (as
star_rules_study.compare). Passing would make the automatic picks lose less (or win more) in the test; whether the
picks earn at all is reported too (Rs a day above 0 on average, in both halves, since 2022 and in 7 of 10 years).
Nothing changes on the order server by this study; the owner decides.

Result: not run yet.
"""
import glob
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import star_rules_study as sr

LOT, COST, STOP, HOLD, MIN_SIZE = 65, 1.85, 0.10, 3, 25.0
LAST_ENTRY_K = 33          # row 33 makes the lean for the 14:55 candle; the 15:05 lean is after the server's 15:00
LAST_CLOSE_K = 34          # the 15:05 candle closes at 15:15: every pick is out by then
EARLY_K = 1                # rows 0 and 1: the 09:25 and 09:35 leans
VARIANTS = {"today": {}, "EXTEND": {"extend": True}, "SKIP_EARLY": {"skip_early": True},
            "BOTH": {"extend": True, "skip_early": True}}


def day_picks(rows, rule, b, a, prem_pct):
    """One day. rows: {k: (star, size, side, y)} with y NIFTY's return over candle k (the lean's candle) and price the
    close before it. Returns the day's picks: [(entry k, exit k, Rs a lot after costs)]."""
    ks = sorted(rows)
    out, i = [], 0
    while i < len(ks):
        k = ks[i]
        star, size, side, _y, price = rows[k]
        if not (star and size >= MIN_SIZE and k <= LAST_ENTRY_K) or (rule.get("skip_early") and k <= EARLY_K):
            i += 1
            continue
        prem, end, level, val, j = prem_pct * price, k + HOLD, 1.0, None, k
        while j < end and j <= LAST_CLOSE_K and j in rows:
            level *= 1 + rows[j][3]
            val = b * side * (level - 1) * price + a * (j - k + 1)
            if val <= -STOP * prem:
                break
            j += 1
            if rule.get("extend") and j in rows and j <= LAST_ENTRY_K:
                s2, z2, d2 = rows[j][0], rows[j][1], rows[j][2]
                if s2 and z2 >= MIN_SIZE and d2 == side:
                    end = max(end, j + HOLD)
        else:
            j -= 1
        if val is None:
            i += 1
            continue
        out.append((k, j, (val - COST) * LOT))
        i = ks.index(j) + 1 if j in ks else len(ks)      # the next pick only after this one is out
    return out


def run_days(days, rule, b, a, prem_pct):
    """days: {day: rows}. Rs a day (0 on a day without picks) and the picks."""
    per, picks = {}, []
    for d, rows in days.items():
        p = day_picks(rows, rule, b, a, prem_pct)
        per[d] = sum(x[2] for x in p)
        picks += [(d,) + x for x in p]
    return pd.Series(per), picks


# ---------------------------------------------------------------- layer 1: nine years
def nine_year_days(t):
    import star_hold_study as sh
    t = t[~((t["d"] >= sh.CAS_FROM) & (t["k"] >= sh.CAS_K))].sort_values(["d", "k"])
    days = {}
    for d, g in t.groupby("d"):
        days[d] = {int(k): (bool(s), float(z), int(np.sign(p)), float(y), float(pr))
                   for k, s, z, p, y, pr in zip(g["k"], g["star"], g["size_pts"], g["pred"], g["y"], g["price"])}
    return days


def earns_daily(v, years):
    yrs = v.groupby(years).mean()
    half = len(yrs) // 2
    r = {"rs_per_day": int(round(v.mean())), "halves": [int(yrs.iloc[:half].mean()), int(yrs.iloc[half:].mean())],
         "since_2022": int(v[years >= 2022].mean()), "years_up": f"{int((yrs > 0).sum())}/{len(yrs)}",
         "by_year": {str(k): int(round(x)) for k, x in yrs.items()}}
    r["earns"] = bool(r["rs_per_day"] > 0 and all(h > 0 for h in r["halves"]) and r["since_2022"] > 0 and int((yrs > 0).sum()) >= 7)
    return r


def layer1(days, b, a, prem_pct):
    res, series = {}, {}
    for name, rule in VARIANTS.items():
        s, picks = run_days(days, rule, b, a, prem_pct)
        series[name] = s
        res[name] = {"picks": len(picks), "days_with_picks": int((s != 0).sum()),
                     "rs_per_pick": int(round(np.mean([p[3] for p in picks]))) if picks else None,
                     "minutes_held": round(float(np.mean([(p[2] - p[1] + 1) * 10 for p in picks])), 1) if picks else None}
    years = pd.Series([d.year for d in series["today"].index], index=series["today"].index)
    for name in VARIANTS:
        res[name].update(earns_daily(series[name], years))
        if name != "today":
            res[name]["vs_today"] = sr.compare(series[name], series["today"], years)
    return res


# ---------------------------------------------------------------- layer 2: the live days
def live_days(store_dir, since="2026-11-04"):
    days = {}
    for f in sorted(glob.glob(os.path.join(store_dir, "live", "*.json"))):
        day = os.path.basename(f)[:-5]
        if day < since:
            continue
        d = json.load(open(f))
        closes = {datetime.fromtimestamp(c["time"], timezone.utc).strftime("%H:%M"): c["close"] for c in d.get("candles") or []}
        leans = {x["at"]: x for x in d.get("leans") or []}
        rows = {}
        for k in range(LAST_CLOSE_K + 1):
            m = 9 * 60 + 25 + 10 * k
            at, before = f"{m // 60:02d}:{m % 60:02d}", f"{(m - 10) // 60:02d}:{(m - 10) % 60:02d}"
            if at not in closes or before not in closes:
                continue
            x = leans.get(at) or {}
            rows[k] = (bool(x.get("confident")), float(x.get("size") or 0), 1 if x.get("lean") == "up" else -1,
                       closes[at] / closes[before] - 1, closes[before])
        if rows:
            days[day] = rows
    return days


def hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def layer2(days, b, a, prem_pct):
    out = {}
    for name, rule in VARIANTS.items():
        s, picks = run_days(days, rule, b, a, prem_pct)
        out[name] = {"total_rs": int(round(s.sum())), "picks": len(picks),
                     "list": [f"{d} {hm(565 + 10 * k0)}-{hm(575 + 10 * k1)} {int(round(rs)):+d}" for d, k0, k1, rs in picks]}
    return out


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        import nextcandle_study as ns
        import star_size_study as ss
        optlive = os.environ.get("OPTLIVE_DIR", "optlive")
        n = ss.strike_numbers(optlive, 0) or {"b": 0.55, "a": -0.2, "prem_pct": 0.007, "pairs": 0}
        out = {"pricing": n}
        out["layer2_live_days"] = layer2(live_days(os.environ.get("STORE_DIR", "store")), n["b"], n["a"], n["prem_pct"])
        df = ns.rows(*(intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), k) for k in ("nifty", "banknifty", "vix")), h=1)
        t = lf.walk_forward(df)
        out["from"], out["to"] = str(t["d"].min()), str(t["d"].max())
        out["layer1_nine_years"] = layer1(nine_year_days(t), n["b"], n["a"], n["prem_pct"])
        out["passes"] = [k for k, v in out["layer1_nine_years"].items() if k != "today" and v["vs_today"]["passes"]]
        print("STUDY starstreak " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY starstreak failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
