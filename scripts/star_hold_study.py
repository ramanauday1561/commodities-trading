"""Experiment mode "starhold" (10 Nov 2026, asked by the user): the * leans, held longer, as the order server can.

Why: the owner plans to trade the Next 10 page's * (more confident) leans with real money through the order server,
which can hold a pick past the next 10 minutes. leanfilter_study.py (9 Nov) tested * leans held for 10 minutes only:
53.0% right, -Rs72 a lot a trade, 0 of 10 years up. On Kite's real prices they made +Rs5,213 over 4-9 Nov (31 trades),
too few to tell. This asks the one question not yet tested: does holding a * lean longer let the right side win by
more than the costs?

The trade (no new model): the * leans exactly as leanfilter_study.walk_forward makes them (LightGBM, walk-forward by
year from 2017, each year from a model trained only on the years before; * = confidence in its training years' top
20%). For each, buy the at-the-money option on the lean's side at the lean, sell it after the hold. Holds, fixed:
  H1   10 minutes (the existing test, for comparison)
  H3   30 minutes
  H6   60 minutes
  END  to the day's last 10-minute close
A hold that would run past the day's data is left out (H3, H6); END always exists. From 3 Aug 2026 (NSE's closing
auction) no lean is made for the 15:15 candle, as on the page.
Pricing, from Kite's saved quotes (leanfilter_study.calibrate on the options-live branch): option points =
b x NIFTY's move on the lean's side + a x (minutes held / 10) - 1.85 costs. b and a are measured on 10-minute steps; over
longer holds the option's share of the move changes (gamma), so the longer holds are an estimate, slightly kind to a
big move and harsh to a small one.

Rule, fixed before the run (four holds are tried, so the same strict rule as leanfilter_study): a hold is worth a
paper account only if its * trades earn after costs on average over 2017-2026, in both halves of those years, since
2022, and in at least 7 of the 10 years, with at least 300 trades. Passing would not make it a trade signal: it would
go to the paper accounts first, as information.

Result (run 10 Nov 2026 on the intraday-data and options-live branches; * leans 2017-01-02 to 2026-11-09; pricing
b 0.569, a -0.08 from 256 Kite quote pairs; Rs a lot after costs): ALL FOUR FAIL.
  H1  10 minutes   16,374 trades, right 53.0%, -1.11 pts, -Rs72, halves -1.23 / -1.03, since 2022 -0.99, 0 of 10 years
                   (the same numbers as leanfilter_study's F1: the code reproduces it)
  H3  30 minutes   14,393 trades, right 52.7%, -0.81 pts, -Rs53, halves -1.04 / -0.84, since 2022 -0.65, 1 of 10
  H6  60 minutes   12,162 trades, right 53.0%, -0.82 pts, -Rs53, halves -1.14 / -0.67, since 2022 -0.50, 1 of 10
  END to the close 16,374 trades, right 52.7%, -1.72 pts, -Rs112, halves -1.50 / -1.88, since 2022 -1.64, 2 of 10
  Holding 30 or 60 minutes loses less a trade than 10 (the cost is paid once over a longer move) but still loses in 9
  of 10 years; the one up year is 2024 (+Rs111 and +Rs232). Holding to the close loses most, -Rs518 a trade in 2026.
  A * lean is right about 53% of the time however long it is held, and that is not enough to pay for an option's
  costs and time decay. Nothing changes in the app; the * leans stay information, and the paper account keeps counting.
"""
import json
import os

import numpy as np
import pandas as pd

import intraday_data
import leanfilter_study as lf
import nextcandle_study as ns

HOLDS = {"H1 10 minutes": 1, "H3 30 minutes": 3, "H6 60 minutes": 6, "END to the last close": None}
CAS_FROM, CAS_K = pd.Timestamp("2026-08-03").date(), 35        # row 35 makes the lean for the 15:15 candle


def forward(t, h):
    """NIFTY's return from each row's close over the next h candles of the same day (None: to the day's last close),
    and the candles held; NaN where the day ends first."""
    t = t.sort_values(["d", "k"])
    g = np.log1p(t["y"]).groupby(t["d"])
    total = g.transform("sum")
    done = g.cumsum() - np.log1p(t["y"])                               # log return already behind each row
    left = t.groupby("d")["k"].transform("count") - t.groupby("d").cumcount()
    if h is None:
        return np.expm1(total - done), left
    ahead = g.transform(lambda s: s[::-1].rolling(h, min_periods=h).sum()[::-1])
    return np.expm1(ahead), pd.Series(h, index=t.index)


def summary(s, ret, n, b, a):
    side = np.sign(s["pred"].values)
    move = side * ret.values * s["price"].values
    pts = b * move + a * n.values - lf.COST
    yrs = pd.Series(pts, index=s["year"].values).groupby(level=0).mean()
    half = len(yrs) // 2
    rec = pts[s["year"].values >= 2022]
    return {"trades": int(len(s)), "right": round(float((move > 0).mean()), 3), "pts": round(float(pts.mean()), 2),
            "rs_per_lot": int(round(pts.mean() * lf.LOT)),
            "halves": [round(float(yrs.iloc[:half].mean()), 2), round(float(yrs.iloc[half:].mean()), 2)],
            "since_2022": round(float(rec.mean()), 2) if len(rec) else None,
            "years_up": f"{int((yrs > 0).sum())}/{len(yrs)}", "by_year_rs": {str(k): int(round(v * lf.LOT)) for k, v in yrs.items()}}


def run(t, b, a):
    t = t[~((t["d"] >= CAS_FROM) & (t["k"] >= CAS_K))].sort_values(["d", "k"])
    out = {}
    for name, h in HOLDS.items():
        ret, n = forward(t, h)
        ok = t["star"].values & ret.notna().values
        r = summary(t[ok], ret[ok], n[ok], b, a)
        r["passes"] = lf.passes(r)
        out[name] = r
    return out


def main():
    try:
        cal = lf.calibrate(os.environ.get("OPTLIVE_DIR", "optlive"))
        trusted = cal.get("pairs", 0) >= 100
        b, a = (cal["b"], cal["a"]) if trusted else (0.5, 0.0)
        d = os.environ.get("INTRADAY_DIR", "intra")
        df = ns.rows(*(intraday_data.load(d, k) for k in ("nifty", "banknifty", "vix")), h=1)
        t = lf.walk_forward(df)
        out = {"pricing_used": {"b": b, "a": a, "pairs": cal.get("pairs", 0)}, "from": str(t["d"].min()), "to": str(t["d"].max()),
               "holds": run(t, b, a)}
        out["any_passes"] = [k for k, v in out["holds"].items() if v["passes"]]
        print("STUDY starhold " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY starhold failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
