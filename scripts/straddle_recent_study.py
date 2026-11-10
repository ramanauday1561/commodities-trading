"""Experiment mode "straddle2022" (10 Nov 2026, asked by the user): the 50%-stop short straddle since 2022, tested harder.

Why: short_option_study.py (4 Nov 2026) found that selling the at-the-money straddle from the open with a 50% stop on
each leg (its variant C) lost every year 2015-2019 and made money since, so it failed that study's rule on the first
half. It is paper-traded in the app since 4 Nov and is the only idea that was up on all four days of real prices.

What is already known, so this run cannot "discover" it: variant C averaged +6.92 points a day since 2022 and the
no-stop straddle was up in every year since 2020. The window 2022-2026 was chosen AFTER seeing that. So a pass here
does not prove an edge; it only says the result is not carried by one year, by expiry days, by cheap costs or by a
few months. What is new in this run is everything in the rule below except the plain average.

The trade (one variant only, so nothing is picked from several): every session from 1 Jan 2022, sell the ATM CALL and
PUT of the nearest expiry at each contract's first price of the day (NSE bhavcopy, option_data.py); a leg is bought
back at +50% of its sale price plus 2 points if its day's high reached that, the rest at the close; 1.85 points a leg
of costs; one lot of 65. Exactly short_option_study.day_rows' variant C, the paper trade in the app. NIFTY's open
(the strike) comes from the stored 5-minute history (intraday_data.py; Kite's candles since 19 May 2026).

Rule, fixed before the run. The straddle passes only if ALL hold on 2022 - now, after costs:
  1. it earns on average in every calendar year of the window (2022, 2023, 2024, 2025, 2026);
  2. it earns in both halves of the window;
  3. it earns on the days that are not expiry days, taken alone;
  4. hard costs: with 3.70 points a leg (double) and 5 points of slippage on every stop, it still earns on average
     and in at least 4 of the 5 years;
  5. at least 60% of the calendar months are up;
  6. the worst day loses no more than 25% of the margin (15% of NIFTY's value a lot, as before), and the largest
     drawdown is no more than what it earns in an average 250 sessions.
A pass changes nothing in the app: the straddle stays a paper trade on real prices, information only. A fail is
written down the same way.

Information, not part of the rule: the four days with Kite's own 5-minute option candles (4-9 Nov 2026) priced three
ways: this bhavcopy model, the app's paper trade (Kite's first price), and a seller who is 5 minutes late (sells at
the 09:20 price, stops from the candles after). Four days say little; they show how much the first price matters.

Result: not run yet when this rule was written (see the commit history).
"""
import csv
import json
import os

import numpy as np
import pandas as pd

import intraday_data
import option_data
import short_option_study as so
from option_study import COST, GIFT_ERA_ON, LOT

HARD_COST, HARD_SLIP = 2 * COST, 5.0
STOP = 0.5


def judge(g):
    """The numbers for the 50%-stop straddle over the window, and the rule."""
    g = g.sort_values("d").reset_index(drop=True)
    pts = g["pts"].to_numpy()
    hard = pts - 2 * (HARD_COST - COST) - (HARD_SLIP - so.SLIP) * g["stopped"].to_numpy()
    year, month = g["d"].map(lambda x: x.year), g["d"].map(lambda x: (x.year, x.month))
    by_year, hard_year, by_month = g["pts"].groupby(year).mean(), pd.Series(hard).groupby(year).mean(), g["pts"].groupby(month).sum()
    half = len(g) // 2
    rs = pts * LOT
    cum = np.cumsum(rs)
    dd = float(np.max(np.maximum.accumulate(cum) - cum))
    margin, worst = float(g["margin"].median()), float(rs.min())
    other = g[g["dte"] > 0]["pts"]
    out = {"days": int(len(g)), "from": str(g["d"].iloc[0]), "to": str(g["d"].iloc[-1]),
           "won": round(float((pts > 0).mean()), 3), "avg_pts": round(float(pts.mean()), 2),
           "rs_per_lot_day": int(round(rs.mean())), "total_rs_per_lot": int(round(rs.sum())),
           "by_year_rs_per_day": {str(y): int(round(v * LOT)) for y, v in by_year.items()},
           "halves_pts": [round(float(pts[:half].mean()), 2), round(float(pts[half:].mean()), 2)],
           "expiry_day_pts": round(float(g[g["dte"] == 0]["pts"].mean()), 2) if (g["dte"] == 0).any() else None,
           "other_days_pts": round(float(other.mean()), 2), "other_days": int(len(other)),
           "hard_costs_avg_pts": round(float(hard.mean()), 2),
           "hard_costs_by_year_rs_per_day": {str(y): int(round(v * LOT)) for y, v in hard_year.items()},
           "months_up": f"{int((by_month > 0).sum())}/{len(by_month)}",
           "worst_day_rs": int(round(worst)), "worst_day": str(g.loc[g["pts"].idxmin(), "d"]),
           "median_margin_rs": int(round(margin)), "max_drawdown_rs": int(round(dd)),
           "avg_250_sessions_rs": int(round(rs.mean() * 250)), "stops_hit_share": round(float((g["stopped"] > 0).mean()), 3),
           "sharpe": round(float(pts.mean() / pts.std() * np.sqrt(250)), 2) if pts.std() else None}
    out["rule"] = {"1 every year up": bool((by_year > 0).all()),
                   "2 both halves up": bool(all(h > 0 for h in out["halves_pts"])),
                   "3 non-expiry days up": bool(len(other) and other.mean() > 0),
                   "4 hard costs up, 4 of 5 years": bool(hard.mean() > 0 and (hard_year > 0).sum() >= min(4, len(hard_year))),
                   "5 60% of months up": bool((by_month > 0).mean() >= 0.6),
                   "6 worst day and drawdown": bool(-worst <= 0.25 * margin and dd <= rs.mean() * 250)}
    out["passes"] = all(out["rule"].values())
    return out


def late_seller(rows, strike, expiry):
    """Points after costs for a seller 5 minutes late, from one day's 5-minute option candles: both legs sold at the
    close of the 09:15 candle; a leg is stopped when a later candle's high reaches +50%; the rest at the last close."""
    pts = 0.0
    for typ in ("CE", "PE"):
        c = sorted((r for r in rows if r["expiry"] == expiry and float(r["strike"]) == float(strike) and r["type"] == typ),
                   key=lambda r: r["datetime"])
        if len(c) < 2 or c[0]["datetime"][11:16] != "09:15":
            return None
        sold = float(c[0]["close"])
        hit = max(float(r["high"]) for r in c[1:]) >= sold * (1 + STOP)
        pts += -sold * STOP - so.SLIP if hit else sold - float(c[-1]["close"])
    return round(pts - 2 * COST, 2)


def kite_days(optlive, model):
    """The days with Kite's own option candles, priced three ways (information). model: {date string: points}."""
    path = os.path.join(optlive, "paper", "straddle.json")
    out = []
    for x in (json.load(open(path)) if os.path.exists(path) else []):
        f = os.path.join(optlive, "candles", f"{x['d']}.csv")
        late = late_seller(list(csv.DictReader(open(f))), x["strike"], x["expiry"]) if os.path.exists(f) else None
        out.append({"d": x["d"], "bhavcopy_model_rs": None if x["d"] not in model else int(round(model[x["d"]] * LOT)),
                    "paper_trade_rs": x["rs"], "five_minutes_late_rs": None if late is None else int(round(late * LOT))})
    return out


def main():
    try:
        opt = option_data.load([x for x in os.environ.get("OPTIONS_DIRS", "opt").split(",") if x])
        opt = opt[opt["d"] >= GIFT_ERA_ON]
        if opt.empty:
            raise RuntimeError("no option data: run mode optdata first")
        days = intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), "nifty")
        nd = pd.DataFrame({"open": {pd.Timestamp(d): float(g["Open"].iloc[0]) for d, g in days.items() if d >= GIFT_ERA_ON}}).sort_index()
        rows = so.day_rows(opt, nd)
        c = rows[rows["v"] == "C"]
        out = {"50%-stop short straddle, nearest expiry, since 2022": judge(c)}
        out["Kite days, three ways (information)"] = kite_days(os.environ.get("OPTLIVE_DIR", "optlive"),
                                                               {str(d): p for d, p in zip(c["d"], c["pts"])})
        print("STUDY straddle2022 " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY straddle2022 failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
