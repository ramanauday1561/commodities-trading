"""Experiment mode "gift" (29 Oct 2026): does GIFT Nifty (SGX Nifty before July 2023) help the trade from the open?

The 11-year test (long_signal_study.py) found the from-open signal's edge gone since 2022, probably because GIFT Nifty
now trades almost round the clock and the 09:15 open already prices the overnight markets. GIFT Nifty's own history
is not free, but Dukascopy's India 50 CFD (INDIDXUSD, overnight_data.py key "india") follows it and trades while NSE
is closed. Hourly, from 2015; the last candle known before 09:10 IST ends at 08:30 IST.
Inputs from it, for day D (NSE's 15:30 IST close on the day before = "prev"):
  gift_gap      India 50 at 08:30 IST vs at prev 15:30: the gap GIFT points to
  gift_night    prev 15:30 -> 06:30 IST (the US session and the night)
  gift_morning  06:30 -> 08:30 IST (Asia's open, before NSE's)
  gap_surprise  NIFTY's actual 09:15 gap minus gift_gap: what the opening auction added or took away
Checks (walk-forward, traded like the live signal: top-20% days, standing aside after results and US news, 0.5% stop
on 5-minute candles, 0.03% costs; LONG = long_signal_study.LONG):
  1. does it trade at night, and how much of the 09:15 gap does gift_gap explain (before / since July 2023)
  2. LONG vs LONG + the GIFT inputs, over all years and since July 2023
  3. the gap surprise alone: trade against it (the open overshot) or with it, when it is 0.15% or more
Rules fixed before the run: the GIFT inputs help if LONG + GIFT earns more per trade than LONG in both halves, more in
total, and makes money since July 2023 (the GIFT era). The surprise rule needs 30+ trades, half won, both halves up.
Data found (29 Oct 2026): no free GIFT Nifty history (Kaggle, NSE IX's site and SGX's tick files have none usable).
Dukascopy's India 50 CFD followed SGX Nifty and stopped when SGX Nifty moved to GIFT City: hourly prices from Dec 2017
to Jun 2023 only (one flat candle a month after that). So the GIFT-era part of the rule cannot be checked.
Result (run 40755746709, 1,373 sessions, Dec 2017 - Jun 2023):
  1. it traded 9 night hours a day (median) and explained 78% of the variation of NIFTY's 09:15 gap (R^2 0.782), against
     62% for our overnight markets: the open does take in what SGX / GIFT Nifty priced overnight
  2. LONG 186 trades, 38% won, +0.068% a trade (+0.115% / +0.022% by half); LONG + GIFT 149 trades, 46% won, +0.173%
     (+0.284% / +0.064%): better in both halves, but both lost money in 2022 and the first half of 2023 (-1.2%, -1.9%)
  3. fading the opening surprise (NIFTY opened 0.15%+ away from where SGX Nifty pointed, trade back towards it):
     648 trades, 46% won, +0.089% (+0.138% / +0.041%), up in 5 of 7 years; fails "half won". Following it lost.
  Fading the plain gap (no SGX price; NIFTY 5-minute history, 2015-2026, 0.5% stop, checked by hand the same day):
     0.15%+ gaps 2,008 trades, 46% won, +0.051%; since Jul 2023 +0.016% and losing in the later half. Not used.
Nothing changes in the app: GIFT Nifty helped in 2018-2021 but no free history exists for the years since, so it
cannot be tested where it matters. Recording a daily GIFT Nifty quote from now on would let it be tested later.
"""
import json
import os

import numpy as np
import pandas as pd

import intraday_data
import long_signal_study as ls
import overnight_data
import todaycall as tc

GIFT = ["gift_gap", "gift_night", "gift_morning", "gap_surprise"]
GIFT_ERA = pd.Timestamp("2023-07-03")
INFO, MORNING = (3, 0), (1, 0)                 # UTC: 08:30 IST (last hour candle before 09:10) and 06:30 IST


def gift_inputs(df, nd, india):
    rows = []
    days = list(nd.index)
    pos = {d: k for k, d in enumerate(days)}
    for d in df.index:
        k = pos[d]
        prev = days[k - 1].date()
        a = tc.value_at(india, tc.utc_at(prev, tc.PREV_CLOSE))
        m = tc.value_at(india, tc.utc_at(d.date(), MORNING))
        b = tc.value_at(india, tc.utc_at(d.date(), INFO))
        ok = all(np.isfinite(x) and x for x in (a, m, b))
        g = b / a - 1 if ok else 0.0
        rows.append({"gift_gap": g, "gift_night": m / a - 1 if ok else 0.0, "gift_morning": b / m - 1 if ok else 0.0,
                     "gap_surprise": df.loc[d, "gap"] - g if ok else 0.0, "gift_ok": ok,
                     "night_moves": int(((india.index > tc.utc_at(prev, tc.PREV_CLOSE)) &
                                         (india.index <= tc.utc_at(d.date(), MORNING))).sum())})
    return pd.DataFrame(rows, index=df.index)


def main():
    try:
        od = os.environ.get("OVERNIGHT_DIR", "od")
        series = {k: overnight_data.load(od, k) for k in ("es", "nq", "nikkei", "hangseng")}
        india = overnight_data.load(od, "india")
        series.update({k: ls.us_close_series(t) for k, t in (("hdb", "HDB"), ("ibn", "IBN"), ("infy", "INFY"))})
        nd = ls.nifty_daily()
        df = tc.history(nd, series)
        end = min(s.index[-1] for s in [*series.values()][:4] + [india]).tz_convert(None).normalize()
        # the India 50 CFD followed SGX Nifty and stopped trading when it moved to GIFT City (July 2023): one flat
        # candle a month after that, so only Dec 2017 - Jun 2023 has the overnight prices (checked 29 Oct 2026)
        df = df[(df.index >= ls.FIRST) & (df.index <= end) & (df.index < GIFT_ERA)]
        df = df.join(gift_inputs(df, nd, india))
        df = df[df["gift_ok"]]
        intra = intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), "nifty")
        o2c = ((1 + df["day"]) / (1 + df["gap"]) - 1).values
        skip = ls.skip_days(df, nd)
        era = df.index >= GIFT_ERA
        out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date()),
               "gift_era_days": int(era.sum()), "india_hours": len(india)}

        # 1. does it trade at night; how much of the gap it explains
        r2 = lambda x, y: round(float(np.corrcoef(x, y)[0, 1] ** 2), 3)
        out["night_hours_with_trades_median"] = float(df["night_moves"].median())
        out["gap_explained_r2"] = r2(df["gift_gap"], df["gap"])
        out["gap_explained_by_overnight_markets_r2"] = round(float(np.corrcoef(
            tc.walk_forward(df[ls.LONG].values, df["gap"].values)[tc.MIN_HIST:], df["gap"].values[tc.MIN_HIST:])[0, 1] ** 2), 3)

        # 2. LONG vs LONG + GIFT
        res = {}
        for name, feats in (("LONG", ls.LONG), ("LONG + GIFT", ls.LONG + GIFT)):
            p, t = ls.wf(df[feats].values, o2c)
            tr = ls.trades(df, p, t, skip, intra)
            res[name] = {"all years": ls.summary(tr)}
        out.update(res)
        a, b = res["LONG + GIFT"]["all years"], res["LONG"]["all years"]
        out["gift_helps"] = bool(a.get("trades", 0) >= 30 and a["total_pct"] > b["total_pct"]
                                 and all(x > y for x, y in zip(a["avg_halves"], b["avg_halves"])))

        # 3. the gap surprise alone
        for name, sign in (("fade the surprise", -1), ("follow the surprise", 1)):
            tr = {}
            for j, d in enumerate(df.index):
                s = df["gap_surprise"].iloc[j]
                if abs(s) < 0.0015 or skip[j]:
                    continue
                side = float(np.sign(s)) * sign
                g = intra.get(d.date())
                tr[d.date()] = (ls.history_study.path(g, side) if g is not None and len(g) > 60
                                else side * o2c[j] * 100 - tc.TRADE_COST_PCT)
            r = ls.summary(tr)
            r["passes"] = bool(r.get("trades", 0) >= 30 and r["win"] >= 0.5 and all(h is not None and h > 0 for h in r["avg_halves"]))
            out[name] = r
        print("STUDY gift " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY gift failed: {e!r}", flush=True)
