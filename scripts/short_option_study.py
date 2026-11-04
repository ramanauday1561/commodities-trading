"""Experiment mode "shortopt" (4 Nov 2026, asked by the user): selling NIFTY options from the open, on real premiums.

Why: option_study.py found that an ATM straddle BOUGHT at the 09:15 open and sold at the close lost in every one of 12
years (-10.37 points a day after costs), and that NIFTY moved 0.84 of what India VIX implied. The other side of that
trade, selling, is the only consistent edge our data has shown. This study prices it on NSE's daily bhavcopy
(option_data.py: each option's open, high, low and close), 2015 to now, one lot of 65 every session.

Variants (each sold at the contract's first price of the day, bought back at its close or at a stop):
  A. Short ATM straddle, nearest expiry (the expiring contract on expiry day), no stop
  B. Short ATM straddle, next expiry after today (skip expiry day), no stop
  C. A with a stop on each leg at +50% of its sale price
  D. A with a stop on each leg at +30%
  E. Short iron fly, nearest expiry: A plus a bought CALL and PUT about 1% of NIFTY away (the wings cap the loss)
  F. E on the next expiry after today
A stop is hit when the leg's high for the day reaches it (the bhavcopy has the day's high, so a touched stop is known,
not its time); the leg is then bought back at the stop plus 2 points of slippage. The wings are held to the close.
Costs: 1.85 option points a leg for the round trip (Rs120 a lot: brokerage, STT, fees, the spread), as option_study.py.
Margin is estimated, not NSE's SPAN: a naked straddle 15% of NIFTY's value per lot; an iron fly its largest possible
loss (wing width - credit) plus 2% exposure.

Rule, fixed before the run: a variant is worth paper-trading only if, after costs, it earns on average (1) over all
days, (2) in both halves, (3) since 2022, (4) in at least 9 of the 12 years, and (5) its worst day loses no more than
25% of its margin. Six variants are tried on the same data, so one passing by a little would still be luck-prone;
anything that passes goes to paper trading in the app, not to real money.

Result (run 41811711586, 4 Nov 2026; 2,906 sessions, 1 Jan 2015 - 3 Nov 2026; Rs a lot of 65 a day after costs):
  A. straddle, nearest, no stop     +232/day, won 60%, halves -0.60 / +7.74 pts, since 2022 +7.58 pts, 7/12 years,
                                    worst day -66,771 (4 Jun 2024, the election result), max drawdown -197,808
  B. straddle, skip expiry day      +202/day, halves -0.66 / +6.88, 7/12 years, worst -66,771
  C. A with 50% stops               +229/day, halves -0.26 / +7.32, since 2022 +6.92, 8/12 years, worst -21,312
                                    (23 Mar 2020), max drawdown -142,644, stops hit on 60% of days, Sharpe 1.29
  D. A with 30% stops               +110/day, 6/12 years
  E. iron fly (1% wings), nearest   -386/day, 1/12 years      F. iron fly, skip expiry day  -445/day, 0/12 years
  None passes. Selling straddles lost money every year 2015-2019 (about -Rs100 to -Rs230 a day) and made money every
  year since 2020 (A: +Rs209 to +Rs893 a day, rising), so the first half fails. The gain is concentrated on expiry
  days (A: +13.81 points on expiry days, +1.68 on others). The wings of the iron fly cost more than they saved on
  bhavcopy opens (thin far-out-of-the-money first trades are part of that). By India VIX at the open (A): low
  +Rs130, middle +Rs101, high +Rs471 a day, with the worst days in the high third.
  Choosing "since 2020" now would be picking the window after seeing it; the honest next step is a forward record:
  the app now records live option prices every 10 minutes (options_live.py), so variant C can be paper-traded on
  real prices from here on, as information.
"""
import json
import os

import numpy as np
import pandas as pd

import intraday_data
import long_signal_study as ls
import option_data
from option_study import COST, GIFT_ERA_ON, LOT, pick

SLIP = 2.0
NAKED_MARGIN, EXPOSURE = 0.15, 0.02


def leg_short(o, stop=None):
    """Points for one sold option: sale price - buyback (the close, or the stop if the day's high reached it)."""
    sold, hi, close = float(o["open"]), float(o["high"]), float(o["close"])
    if stop is not None and hi >= sold * (1 + stop):
        return -sold * stop - SLIP, True
    return sold - close, False


def wing(ch, expiry, typ, target):
    c = ch[(ch["expiry"] == expiry) & (ch["type"] == typ)]
    if c.empty:
        return None
    strikes = np.sort(c["strike"].unique())
    k = strikes[int(np.argmin(np.abs(strikes - target)))]
    return c[c["strike"] == k].iloc[0]


def day_rows(opt, nd):
    """One row per session and variant: points after costs, stops hit, credit, margin estimate."""
    by_day = {d: g for d, g in opt.groupby("d")}
    rows = []
    for ts in nd.index:
        d, ch = ts.date(), by_day.get(ts.date())
        if ch is None:
            continue
        spot = float(nd.loc[ts, "open"])
        for name, rule, stop, fly in (("A", "nearest", None, False), ("B", "no_expiry_day", None, False),
                                      ("C", "nearest", 0.5, False), ("D", "nearest", 0.3, False),
                                      ("E", "nearest", None, True), ("F", "no_expiry_day", None, True)):
            ce, pe = pick(ch, d, spot, "CE", rule), pick(ch, d, spot, "PE", rule)
            if ce is None or pe is None or ce["expiry"] != pe["expiry"] or float(ce["open"]) <= 0 or float(pe["open"]) <= 0:
                continue
            (a, sa), (b, sb) = leg_short(ce, stop), leg_short(pe, stop)
            credit = float(ce["open"]) + float(pe["open"])
            pts, legs = a + b, 2
            margin = NAKED_MARGIN * spot * LOT
            if fly:
                w = round(spot * 0.01 / 50) * 50 or 50
                wc, wp = wing(ch, ce["expiry"], "CE", float(ce["strike"]) + w), wing(ch, pe["expiry"], "PE", float(pe["strike"]) - w)
                if wc is None or wp is None or float(wc["strike"]) <= float(ce["strike"]) or float(wp["strike"]) >= float(pe["strike"]):
                    continue
                pts += (float(wc["close"]) - float(wc["open"])) + (float(wp["close"]) - float(wp["open"]))
                credit -= float(wc["open"]) + float(wp["open"])
                width = max(float(wc["strike"]) - float(ce["strike"]), float(pe["strike"]) - float(wp["strike"]))
                margin = max(width - credit, 0) * LOT + EXPOSURE * spot * LOT
                legs = 4
            rows.append({"d": d, "v": name, "pts": pts - legs * COST, "stopped": int(sa) + int(sb), "credit": credit,
                         "margin": margin, "dte": (ce["expiry"] - d).days})
    return pd.DataFrame(rows)


def judge(g):
    """The numbers for one variant, and the rule."""
    g = g.sort_values("d")
    pts = g["pts"].to_numpy()
    rs = pts * LOT
    half = len(g) // 2
    years = g.groupby(g["d"].map(lambda x: x.year))["pts"]
    recent = g[g["d"] >= GIFT_ERA_ON]["pts"]
    cum = np.cumsum(rs)
    dd = float(np.max(np.maximum.accumulate(cum) - cum)) if len(cum) else 0.0
    margin = float(g["margin"].median())
    worst = float(rs.min())
    out = {"days": int(len(g)), "won": round(float((pts > 0).mean()), 3), "avg_pts": round(float(pts.mean()), 2),
           "rs_per_lot_day": int(round(rs.mean())), "total_rs_per_lot": int(round(rs.sum())),
           "halves_pts": [round(float(pts[:half].mean()), 2), round(float(pts[half:].mean()), 2)],
           "since_2022_pts": round(float(recent.mean()), 2) if len(recent) else None,
           "years_up": f"{int((years.sum() > 0).sum())}/{years.ngroups}",
           "by_year_rs_per_day": {str(y): int(round(v.mean() * LOT)) for y, v in years},
           "worst_day_rs": int(round(worst)), "worst_day": str(g.loc[g["pts"].idxmin(), "d"]),
           "p1_day_rs": int(round(np.percentile(rs, 1))), "max_drawdown_rs": int(round(dd)),
           "stops_hit_share": round(float((g["stopped"] > 0).mean()), 3),
           "median_margin_rs": int(round(margin)), "yearly_return_on_margin_pct": round(float(rs.mean() * 250 / margin * 100), 1),
           "sharpe": round(float(pts.mean() / pts.std() * np.sqrt(250)), 2) if pts.std() else None,
           "expiry_day_pts": round(float(g[g["dte"] == 0]["pts"].mean()), 2) if (g["dte"] == 0).any() else None,
           "other_days_pts": round(float(g[g["dte"] > 0]["pts"].mean()), 2)}
    n_years = years.ngroups
    out["passes"] = bool(pts.mean() > 0 and all(h > 0 for h in out["halves_pts"]) and (out["since_2022_pts"] or 0) > 0
                         and int((years.sum() > 0).sum()) >= min(9, n_years) and -worst <= 0.25 * margin)
    return out


def by_vix(g, vix_close):
    """Information for the best variant: average points by the VIX level known at the open (yesterday's close)."""
    v = g["d"].map(lambda d: vix_close.loc[:d - pd.Timedelta(days=1)].iloc[-1] if len(vix_close.loc[:d - pd.Timedelta(days=1)]) else np.nan)
    q = pd.qcut(v, 3, labels=["low", "middle", "high"])
    return {str(k): {"days": int(len(x)), "rs_per_day": int(round(x["pts"].mean() * LOT)), "worst_rs": int(round(x["pts"].min() * LOT))}
            for k, x in g.groupby(q, observed=True)}


def main():
    try:
        dirs = [x for x in os.environ.get("OPTIONS_DIRS", "opt").split(",") if x]
        opt = option_data.load(dirs)
        if opt.empty:
            raise RuntimeError("no option data: run mode optdata first")
        nd = ls.nifty_daily()
        rows = day_rows(opt, nd)
        out = {"option_days": int(opt["d"].nunique()), "from": str(opt["d"].min()), "to": str(opt["d"].max())}
        names = {"A": "short ATM straddle, nearest expiry, no stop", "B": "short ATM straddle, skip expiry day, no stop",
                 "C": "A with 50% stops per leg", "D": "A with 30% stops per leg",
                 "E": "short iron fly (1% wings), nearest expiry", "F": "short iron fly, skip expiry day"}
        for k, name in names.items():
            out[f"{k}. {name}"] = judge(rows[rows["v"] == k])
        best = max(names, key=lambda k: rows[rows["v"] == k]["pts"].mean())
        try:
            vix5 = intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), "vix")
            vix_close = pd.Series({pd.Timestamp(d): float(g["Close"].iloc[-1]) for d, g in vix5.items()}).sort_index()
            g = rows[rows["v"] == best].copy()
            g["d"] = pd.to_datetime(g["d"])
            out[f"by India VIX at the open, variant {best} (information)"] = by_vix(g, vix_close)
        except Exception as e:
            out["by India VIX"] = f"failed: {e!r}"
        out["any_passes"] = [k for k in names if out[f"{k}. {names[k]}"]["passes"]]
        print("STUDY shortopt " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"STUDY shortopt failed: {e!r}", flush=True)
