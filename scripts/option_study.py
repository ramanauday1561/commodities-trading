"""Experiment mode "options" (31 Oct 2026): the 09:15 signal and option buying, priced on real NIFTY option premiums.

Asked by the user on 31 Oct 2026. Every rupee figure so far assumed an at-the-money option moves half as much as NIFTY,
minus about 1.85 option points (Rs120 a lot) a round trip, with no time decay. NSE's daily bhavcopy (option_data.py)
has each option's open and close, so a trade from the 09:15 open to the close can be priced on real premiums: decay,
the real delta and the market's own pricing included. (A 15:15 exit and the 0.5% stop need intraday option prices,
which the bhavcopy does not have, so every trade here is open to close with no stop.)
1. The 09:15 signal in options. On the days the signal traded (the 11-year walk-forward of long_signal_study.py, and
   the live signal's last 2 years), buy the CALL (signal up) or PUT at the open and sell at the close:
     ATM, nearest expiry (on an expiry day that is the expiring option)
     ATM, skipping expiry day (on an expiry day, the next expiry)        <- the rule below is about this one
     ATM, next expiry (one week further out)
     one strike out of the money, skipping expiry day
   beside the half-delta estimate on the same days, to see how far off the old figures were.
   Rule, fixed before the run: worth trading in options only if the ATM, skip-expiry-day trades earn after costs over
   all years, in both halves, and since 2022.
2. Are options cheap or dear? (a) India VIX's implied daily move against NIFTY's real moves since 2015. (b) An ATM
   straddle (CALL + PUT) bought at the open and sold at the close every day: it wins when NIFTY moves more during the
   session than the options priced in. (c) Can what is known by 09:15 pick the days it wins? A walk-forward model by
   year (LightGBM on India VIX, its change and its level against 20 days, NIFTY's last-5-day volatility against VIX,
   yesterday's range, the opening gap, days to expiry, weekday, results / US-news days), trading its top-20% days,
   beside three simple filters (results / US-news days, gaps of 0.5% or more, recent volatility above VIX).
   Rule, fixed before the run: picking works only if the model's top-20% straddles earn after costs (2 legs) over all
   test years, in both halves, in at least 6 of the test years, and more than straddles on every day.
Costs: 1.85 option points a leg for a round trip (Rs120 a lot of 65: brokerage, STT, fees, the bid-ask spread).
Points are per unit; Rs are for one lot of 65 (the lot size has changed over the years; the points have not).
Result (run 41119100372, 30 Oct 2026; option prices for 2,912 sessions, 1 Jan 2015 - 30 Oct 2026):
1. The 09:15 signal on real premiums (points per trade after costs; Rs a lot of 65):
                                   11-year walk-forward (190 trades)            live version, last 2 years (52 trades)
   ATM, nearest expiry             -3.39 (-Rs220), 40% won, since 2022 -10.94    +26.68 (+Rs1,734), 44% won
   ATM, skip expiry day            -2.29 (-Rs149), 43% won, since 2022 -6.83     +32.20 (+Rs2,093), 48% won (2026: -0.72)
   ATM, next expiry                +0.22 (+Rs14),  44% won, since 2022 -14.38    +27.99 (+Rs1,819), 46% won
   1 OTM, skip expiry day          -0.48 (-Rs31),  45% won, since 2022 -8.18     +22.84 (+Rs1,484), 44% won
   half-delta estimate, same days  -3.32                                         +36.41
   The 11-year version FAILS the rule (by half +5.62 / -10.21; 6 of 12 years up; losing since 2022). The live version
   passes it on paper (+54.59 / +9.82 by half), but its inputs and stand-aside rules were chosen on these same two
   years, so it is not an independent test, and 2026 so far is flat. Nothing changes in the app: the signal stays
   information plus the existing rule, and its live record keeps counting. Two things hold in both sets: the old
   half-delta figures were in the right range (within about 1-4 points a trade), and on expiry days the expiring
   option did worse than the next expiry's (by 1.1 and 5.5 points a trade).
2. (a) NIFTY's daily move averaged 0.84 of what India VIX implied (0.70-0.91 by year; 0.99 in 2026); it moved more
   than implied on only 31% of days. (b) An ATM straddle bought at the open and sold at the close lost on 70% of
   2,839 days: -10.37 points (-Rs674 a lot) a day, in every one of the 12 years, more since 2022 (-13.41) and most
   on the day before expiry (-16.28). (c) Picking fails: the model's top 20% lost less (-5.21 points, 2 of 11 years
   up), and results / US-news days (-7.10), gaps of 0.5%+ (-9.89) and recent volatility above VIX (-11.79) all lost.
   Buying options from the open starts behind on most days: the premium prices a bigger move than usually comes.
"""
import json
import os

import numpy as np
import pandas as pd

import intraday_data
import long_signal_study as ls
import option_data
import overnight_data
import todaycall as tc

COST, LOT = 1.85, 65
GIFT_ERA_ON = pd.Timestamp("2022-01-01").date()


def pick(ch, d, ref, typ, rule, otm=0):
    """One option from day d's rows: CE or PE, by expiry rule, the strike nearest ref (or `otm` steps further out)."""
    ex = sorted(ch["expiry"].unique())
    cands = {"nearest": [e for e in ex if e >= d], "no_expiry_day": [e for e in ex if e > d],
             "next": [e for e in ex if e > d][1:]}[rule]
    if not cands:
        return None
    c = ch[(ch["expiry"] == cands[0]) & (ch["type"] == typ)]
    if c.empty:
        return None
    strikes = np.sort(c["strike"].unique())
    i = int(np.argmin(np.abs(strikes - ref)))
    i = i + otm if typ == "CE" else i - otm
    if not 0 <= i < len(strikes):
        return None
    return c[c["strike"] == strikes[i]].iloc[0]


def summarise(rows):
    """rows: [(date, option points after costs, % of premium)] -> trades, won, averages, halves, years, since 2022."""
    if not rows:
        return {"trades": 0}
    rows = sorted(rows)
    pts = np.array([p for _, p, _ in rows])
    half = len(rows) // 2
    by = {}
    for d, p, _ in rows:
        by.setdefault(d.year, []).append(p)
    recent = [p for d, p, _ in rows if d >= GIFT_ERA_ON]
    return {"trades": len(rows), "won": round(float((pts > 0).mean()), 3), "avg_pts": round(float(pts.mean()), 2),
            "rs_per_lot": int(round(pts.mean() * LOT)), "avg_pct_of_premium": round(float(np.mean([r for _, _, r in rows])), 1),
            "halves_pts": [round(float(pts[:half].mean()), 2), round(float(pts[half:].mean()), 2)] if half else None,
            "years_up": f"{sum(np.sum(v) > 0 for v in by.values())}/{len(by)}",
            "by_year_pts": {str(y): round(float(np.mean(v)), 2) for y, v in sorted(by.items())},
            "since_2022": {"trades": len(recent), "avg_pts": round(float(np.mean(recent)), 2) if recent else None}}


def signal_in_options(days, opt, nd):
    """Part 1 for one set of signal days {date: +1 / -1}."""
    by_day = {d: g for d, g in opt.groupby("d")}
    variants = {"ATM, nearest expiry": ("nearest", 0), "ATM, skip expiry day": ("no_expiry_day", 0),
                "ATM, next expiry": ("next", 0), "1 OTM, skip expiry day": ("no_expiry_day", 1)}
    out, est, covered = {}, [], 0
    for name, (rule, otm) in variants.items():
        rows = []
        for d, side in days.items():
            ch, ts = by_day.get(d), pd.Timestamp(d)
            if ch is None or ts not in nd.index:
                continue
            o = pick(ch, d, float(nd.loc[ts, "open"]), "CE" if side > 0 else "PE", rule, otm)
            if o is None:
                continue
            rows.append((d, float(o["close"]) - float(o["open"]) - COST, (float(o["close"]) / float(o["open"]) - 1) * 100))
            if name == "ATM, skip expiry day":
                move = float(nd.loc[ts, "close"]) - float(nd.loc[ts, "open"])
                est.append((d, 0.5 * side * move - COST, 0.0))
        out[name] = summarise(rows)
        covered = max(covered, len(rows))
    out["half-delta estimate, same days"] = summarise(est)
    out["signal days"], out["with option prices"] = len(days), covered
    m = out["ATM, skip expiry day"]
    out["worth_trading_in_options"] = bool(m.get("trades", 0) >= 30 and m["avg_pts"] > 0 and all(h > 0 for h in m["halves_pts"])
                                           and (m["since_2022"]["avg_pts"] or 0) > 0)
    return out


def straddles(opt, nd, vix_close, events):
    """Part 2: one row per session with an ATM straddle (skip expiry day), its result and the 09:15 inputs."""
    by_day = {d: g for d, g in opt.groupby("d")}
    c = nd["close"]
    ret = c.pct_change()
    rows = []
    for j in range(25, len(nd)):
        ts = nd.index[j]
        d = ts.date()
        ch = by_day.get(d)
        prev = nd.index[j - 1].date()
        if ch is None or prev not in vix_close.index:
            continue
        ref = float(nd["open"].iloc[j])
        legs = [pick(ch, d, ref, t, "no_expiry_day") for t in ("CE", "PE")]
        if any(x is None for x in legs) or legs[0]["expiry"] != legs[1]["expiry"]:
            continue
        cost_in = sum(float(x["open"]) for x in legs)
        pts = sum(float(x["close"]) for x in legs) - cost_in - 2 * COST
        v = vix_close.loc[:prev]
        vix = float(v.iloc[-1])
        rv5 = float(ret.iloc[j - 5:j].std() * np.sqrt(252) * 100)
        rows.append({"d": d, "pts": pts, "pct": pts / cost_in * 100, "vix": vix,
                     "vix_chg": vix / float(v.iloc[-2]) - 1 if len(v) > 1 else 0.0,
                     "vix_vs20": vix / float(v.iloc[-20:].mean()) - 1, "rv5_vs_vix": rv5 / vix if vix else 1.0,
                     "prev_range": float((nd["high"].iloc[j - 1] - nd["low"].iloc[j - 1]) / c.iloc[j - 1]),
                     "gap_abs": abs(ref / float(c.iloc[j - 1]) - 1), "dte": (legs[0]["expiry"] - d).days,
                     "dow": ts.dayofweek, "event": float(events.get(d, False)),
                     "move_c2c": abs(float(ret.iloc[j])) * 100, "move_o2c": abs(float(c.iloc[j]) / ref - 1) * 100})
    return pd.DataFrame(rows)


FEATS = ["vix", "vix_chg", "vix_vs20", "rv5_vs_vix", "prev_range", "gap_abs", "dte", "dow", "event"]


def picking(st):
    """Part 2(c): walk-forward by year, the model's top-20% days, against every day and three simple filters."""
    import lightgbm as lgb
    st = st.copy()
    st["year"] = [d.year for d in st["d"]]
    params = {"objective": "regression", "learning_rate": 0.03, "num_leaves": 7, "min_data_in_leaf": 40,
              "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1}
    top, every = [], []
    for y in sorted(st["year"].unique())[1:]:
        tr, te = st[st["year"] < y], st[st["year"] == y]
        if len(tr) < 150:
            continue
        m = lgb.train(params, lgb.Dataset(tr[FEATS].values, tr["pct"].clip(-100, tr["pct"].quantile(0.99)).values), 200)
        cut = np.quantile(m.predict(tr[FEATS].values), 0.8)
        p = m.predict(te[FEATS].values)
        top += [(d, a, b) for d, a, b, q in zip(te["d"], te["pts"], te["pct"], p) if q >= cut]
        every += list(zip(te["d"], te["pts"], te["pct"]))
    test_from = min(d for d, _, _ in every) if every else None
    t = st[st["d"] >= test_from] if test_from else st.iloc[:0]
    rows = lambda f: list(zip(t.loc[f, "d"], t.loc[f, "pts"], t.loc[f, "pct"]))
    out = {"model top 20%": summarise(top), "every day (same years)": summarise(every),
           "results / US-news days": summarise(rows(t["event"] > 0)), "gap 0.5% or more": summarise(rows(t["gap_abs"] >= 0.005)),
           "recent volatility above VIX": summarise(rows(t["rv5_vs_vix"] > 1))}
    a, b = out["model top 20%"], out["every day (same years)"]
    up = a.get("years_up", "0/1").split("/")
    out["picking_works"] = bool(a.get("trades", 0) >= 50 and a["avg_pts"] > 0 and all(h > 0 for h in a["halves_pts"])
                                and int(up[0]) >= 6 and a["avg_pts"] > b.get("avg_pts", 0))
    return out


def vix_vs_moves(nd, vix_close):
    """Part 2(a): India VIX's implied daily move (the expected size of a normal move) against NIFTY's real ones."""
    ret = nd["close"].pct_change().abs() * 100
    imp = (vix_close.shift(1) / np.sqrt(252) * np.sqrt(2 / np.pi)).reindex(pd.Index([t.date() for t in nd.index]))
    df = pd.DataFrame({"real": ret.values, "implied": imp.values}, index=nd.index).dropna()
    by = df.groupby(df.index.year).mean()
    return {"days": len(df), "avg_real_pct": round(float(df["real"].mean()), 3), "avg_implied_pct": round(float(df["implied"].mean()), 3),
            "real_over_implied": round(float(df["real"].mean() / df["implied"].mean()), 2),
            "days_bigger_than_implied": round(float((df["real"] > df["implied"]).mean()), 3),
            "by_year_real_over_implied": {str(y): round(float(r["real"] / r["implied"]), 2) for y, r in by.iterrows()}}


def main():
    try:
        dirs = [x for x in os.environ.get("OPTIONS_DIRS", "opt").split(",") if x]
        opt = option_data.load(dirs)
        if opt.empty:
            raise RuntimeError("no option data: run mode optdata first")
        out = {"option_days": int(opt["d"].nunique()), "from": str(opt["d"].min()), "to": str(opt["d"].max())}
        nd = ls.nifty_daily()
        vix5 = intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), "vix")
        vix_close = pd.Series({d: float(g["Close"].iloc[-1]) for d, g in vix5.items()}).sort_index()

        # the signal's days: the 11-year walk-forward (Dukascopy inputs) and the live signal's last 2 years (Yahoo)
        od = os.environ.get("OVERNIGHT_DIR", "od")
        series = {k: overnight_data.load(od, k) for k in ("es", "nq", "nikkei", "hangseng")}
        series.update({k: ls.us_close_series(t) for k, t in (("hdb", "HDB"), ("ibn", "IBN"), ("infy", "INFY"))})
        df = tc.history(nd, series)
        end = min(series[k].index[-1] for k in ("es", "nq", "nikkei", "hangseng")).tz_convert(None).normalize()
        df = df[(df.index >= ls.FIRST) & (df.index <= end)]
        p, t = ls.wf(df[ls.LONG].values, ((1 + df["day"]) / (1 + df["gap"]) - 1).values)
        skip = ls.skip_days(df, nd)
        long_days = {d: (1 if p[j] > 0 else -1) for j, d in enumerate(df.index.date)
                     if t[j] in tc.TRADE_TIERS and not skip[j]}
        yd = tc.history(nd, {k: tc.hourly(s) for k, s in {**tc.OVERNIGHT, **tc.INDIA}.items()})
        p2, t2 = ls.wf(yd[tc.OPEN_FEATS].values, ((1 + yd["day"]) / (1 + yd["gap"]) - 1).values)
        skip2 = ls.skip_days(yd, nd)
        live_days = {d: (1 if p2[j] > 0 else -1) for j, d in enumerate(yd.index.date)
                     if t2[j] in tc.TRADE_TIERS and not skip2[j]}

        out["1. 09:15 signal, 11-year walk-forward"] = signal_in_options(long_days, opt, nd)
        out["1. 09:15 signal, live version (last 2 years)"] = signal_in_options(live_days, opt, nd)

        events = dict(zip(nd.index.date, ls.skip_days(pd.DataFrame(index=nd.index), nd)))
        out["2a. India VIX vs real moves"] = vix_vs_moves(nd, vix_close)
        st = straddles(opt, nd, vix_close, events)
        out["2b. ATM straddle open to close, every day"] = summarise(list(zip(st["d"], st["pts"], st["pct"])))
        out["2b. straddle points by days to expiry (8 = 8 or more)"] = {str(k): round(float(g["pts"].mean()), 2)
                                                               for k, g in st.groupby(st["dte"].clip(upper=8))}
        out["2c. picking straddle days"] = picking(st)
        print("STUDY options " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY options failed: {e!r}", flush=True)
