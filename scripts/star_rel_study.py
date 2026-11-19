"""Experiment mode "starrel" (19 Nov 2026, asked by the owner after 19 Nov's late * leans): which * leans should the
server buy?

What the live days show: the 25-point filter (AUTO_MIN_SIZE 25) is easy to pass at the open, where every move is big
(the usual 09:35 move is about 26 points), and hard later (on 19 Nov the 14:45-15:05 * leans expected 16-24 points
and were not bought; two of the three were right). The four 09:35 picks of 25+ points lost (study starstreak). So the
idea: judge the expected move against the usual move at that time of day (the page's "bigger than usual"), not in
fixed points. And the 15:05 * lean comes after the server's 15:00 limit.

The rule today (orders_server.Auto, AUTO_MIN_SIZE 25): a * lean of 25+ points expected buys the at-the-money option of
the next expiry, 1 lot, stop 10% under the price, out after 30 minutes, one pick open at a time, no new pick after
15:00, out by 15:15. The variants, otherwise the same:
  R1.0 / R1.2 / R1.4   a * lean whose expected move is at least 1.0 / 1.2 / 1.4 times the usual move at that time of
                       day (the size model's average for that candle in its training years), in place of 25 points
  LATE                 25+ points, and the 15:05 * lean is bought too (held 10 minutes, out at 15:15)

Data and pricing exactly as star_streak_study (whose day_picks this uses): nine years of walk-forward * leans with
their expected and usual sizes, stepped day by day in 10-minute candles, ATM option priced from Kite's quotes, stops
booked at the 10-minute close they are seen at; and, as information, the live days since 4 Nov 2026 (the leans the
page published, with their sizes; 19 Nov included).

Rule, fixed before the run (Rs a lot a trading day after costs, nine-year layer): a variant replaces today's rule only
if it makes more a day than today's rule on average, in both halves of the years, since 2022, and in at least 70% of
the years in which either rule made a pick (2017-2019 had no 25-point * lean, so a fixed "7 of 10" would count years
with nothing to compare). Several variants are tried, so all four conditions are needed. Whether the picks earn at all
is reported too. Nothing changes on the order server by this study: a passing variant becomes a switch the owner turns
on (AUTO_MIN_RATIO); a failing one does not.

Result: not run yet.
"""
import json
import os

import pandas as pd

import star_rules_study as sr
import star_streak_study as st

VARIANTS = {"today": {}, "R1.0": {"min_ratio": 1.0}, "R1.2": {"min_ratio": 1.2}, "R1.4": {"min_ratio": 1.4},
            "LATE": {"last_entry_k": 34}}


def compare(x, base, years):
    """x vs base (Rs a day): better on average, in both halves, since 2022, and in 70%+ of the years with picks."""
    r = sr.compare(x, base, years)
    xs, bs = x.groupby(years).mean(), base.groupby(years).mean()
    active = [y for y in xs.index if xs[y] != 0 or bs[y] != 0]
    better = sum(xs[y] > bs[y] for y in active)
    r["years_better_with_picks"] = f"{better}/{len(active)}"
    r["passes"] = bool(r["better_avg"] > 0 and all(h > 0 for h in r["halves"]) and r["since_2022"] > 0
                       and active and better >= 0.7 * len(active))
    return r


def nine_years(days, n):
    res, series = {}, {}
    for name, rule in VARIANTS.items():
        s, picks = st.run_days(days, rule, n["b"], n["a"], n["prem_pct"])
        series[name] = s
        res[name] = {"picks": len(picks), "days_with_picks": int((s != 0).sum()),
                     "rs_per_pick": int(round(sum(p[3] for p in picks) / len(picks))) if picks else None}
    years = pd.Series([d.year for d in series["today"].index], index=series["today"].index)
    for name in VARIANTS:
        res[name].update(st.earns_daily(series[name], years))
        if name != "today":
            res[name]["vs_today"] = compare(series[name], series["today"], years)
    return res


def live(days, n):
    out = {}
    for name, rule in VARIANTS.items():
        s, picks = st.run_days(days, rule, n["b"], n["a"], n["prem_pct"])
        out[name] = {"total_rs": int(round(s.sum())), "picks": len(picks),
                     "by_day": {d: int(round(v)) for d, v in s.items() if v},
                     "list": [f"{d} {st.hm(565 + 10 * k0)}-{st.hm(575 + 10 * k1)} {int(round(rs)):+d}" for d, k0, k1, rs in picks]}
    return out


def main():
    try:
        import intraday_data
        import leanfilter_study as lf
        import nextcandle_study as ns
        import star_size_study as ss
        n = ss.strike_numbers(os.environ.get("OPTLIVE_DIR", "optlive"), 0) or {"b": 0.55, "a": -0.2, "prem_pct": 0.007, "pairs": 0}
        out = {"pricing": n, "live_days": live(st.live_days(os.environ.get("STORE_DIR", "store")), n)}
        df = ns.rows(*(intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), k) for k in ("nifty", "banknifty", "vix")), h=1)
        t = lf.walk_forward(df)
        out["from"], out["to"] = str(t["d"].min()), str(t["d"].max())
        out["nine_years"] = nine_years(st.nine_year_days(t), n)
        out["passes"] = [k for k, v in out["nine_years"].items() if k != "today" and v["vs_today"]["passes"]]
        print("STUDY starrel " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY starrel failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
