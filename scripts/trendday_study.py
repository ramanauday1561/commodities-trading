"""Experiment mode "trendday" (29 Oct 2026): can a strong morning be ridden to 15:15 with a CALL (or a PUT)?

Asked after 29 Oct 2026: NIFTY opened flat (22,690.65), was +0.5% by 10:15 with India VIX easing and Bank NIFTY along,
and closed +1.05%. "Follow the move" made Rs12,425 that day but has lost in every year since 2015, so this tests the
narrow version that day suggests, on the stored 5-minute history (intraday_data.py: NIFTY, Bank NIFTY, India VIX).
Rule, fixed before the run:
  at 10:15 (the close of the 10:10 candle) NIFTY is 0.4% or more above its 09:15 open, Bank NIFTY is too, and India VIX
  is below yesterday's close -> buy at 10:15 and hold to 15:15 (the close of the 15:10 candle). The mirror (0.4% or more
  below, Bank NIFTY too, VIX above yesterday) is a PUT. Run with no stop, and with the 0.5% stop the app uses
  (checked on 5-minute highs and lows from 10:15).
Money: NIFTY % after 0.03% costs (as the 09:15 signal is tested), and an at-the-money option as in
  nextcandle_study.py: half the NIFTY move minus about 1.85 option points (Rs120 a lot) a round trip. Five hours of
  time decay is not included, so the option figures are better than real.
Passes only if, for the rule as written (0.4%, both sides): 100+ trades, half or more won, and it earns after costs in
  both halves of the years, in 7 or more of the 12 years, and since July 2023 (the GIFT Nifty era).
  0.3% and 0.6% and each side alone are printed beside it, to see how fragile it is, not to pick the best.
Result (29 Oct 2026, run in the session on the intraday-data branch: 2,857 sessions, Jan 2015 - 29 Oct 2026): fails.
  On 29 Oct it fired (10:15: NIFTY +0.42% from the open, Bank NIFTY +0.62%, VIX -2.2%): CALL +0.64% to 15:15.
  Over 11 years, no stop: 381 trades, 51% won, -0.001% a trade (about -Rs28 a lot before time decay), 6 of 12 years up,
    -0.015% since July 2023. CALL only +0.11% since July 2023 but on 29 trades, -0.09% in the first half.
  With the 0.5% stop: 45% won (fails "half won"), +0.02% a trade, about +1.2 option points (+Rs80 a lot) before time
    decay, 7 of 12 years, +0.037% since July 2023. Five hours of decay on an at-the-money weekly option is several
    points, more than that edge.
  0.3% and 0.6% land in the same place (+0.02% to +0.07% a trade); nothing is far enough from zero to pay for an option.
  So 29 Oct was a day the rule wins, not a rule: strong mornings carry on to 15:15 about as often as they fade.
"""
import json
import os

import numpy as np
import pandas as pd

import intraday_data

COST_PCT, STOP_PCT = 0.03, 0.5
DELTA, COST_OPT_PTS, LOT = 0.5, 1.85, 65
ENTRY, EXIT = (10, 10), (15, 10)                # 5-minute candles starting then: their closes are 10:15 and 15:15
GIFT_ERA = pd.Timestamp("2023-07-03").date()


def _bar(g, hm):
    """Position of the 5-minute candle starting at hm in a day's frame, or None."""
    t = g.index[(g.index.hour == hm[0]) & (g.index.minute == hm[1])]
    return g.index.get_loc(t[0]) if len(t) else None


def days(nifty, bank, vix):
    """One row per session with the 10:15 inputs and the path to 15:15."""
    ds, out = sorted(nifty), []
    for a, d in zip(ds, ds[1:]):
        g = nifty[d]
        i, j = _bar(g, ENTRY), _bar(g, EXIT)
        if i is None or j is None or j <= i:
            continue
        b, v = bank.get(d), vix.get(d)
        bi = _bar(b, ENTRY) if b is not None else None
        vi = _bar(v, ENTRY) if v is not None else None
        vpc = float(vix[a]["Close"].iloc[-1]) if a in vix and len(vix[a]) else np.nan
        out.append({"d": d, "open": float(g["Open"].iloc[0]), "entry": float(g["Close"].iloc[i]),
                    "exit": float(g["Close"].iloc[j]), "highs": g["High"].values[i + 1:j + 1],
                    "lows": g["Low"].values[i + 1:j + 1],
                    "bank": float(b["Close"].iloc[bi]) / float(b["Open"].iloc[0]) - 1 if bi is not None else np.nan,
                    "vix": float(v["Close"].iloc[vi]) / vpc - 1 if vi is not None and np.isfinite(vpc) else np.nan})
    return out


def trade(r, side, stop=None):
    """NIFTY % of the trade after costs (side +1 CALL, -1 PUT), with an optional stop in % from the entry."""
    e = r["entry"]
    if stop is not None:
        hit = (r["lows"] <= e * (1 - stop / 100)) if side > 0 else (r["highs"] >= e * (1 + stop / 100))
        if hit.any():
            return -stop - COST_PCT
    return side * (r["exit"] / e - 1) * 100 - COST_PCT


def signal(r, move=0.004, sides=(1, -1)):
    """+1 / -1 / 0 for the rule at 10:15."""
    m = r["entry"] / r["open"] - 1
    if not (np.isfinite(r["bank"]) and np.isfinite(r["vix"])):
        return 0
    if 1 in sides and m >= move and r["bank"] >= move and r["vix"] < 0:
        return 1
    if -1 in sides and m <= -move and r["bank"] <= -move and r["vix"] > 0:
        return -1
    return 0


def summary(rows, results):
    """Trades, share won, average %, option points and Rs a lot, by halves, by year, and since July 2023."""
    if not results:
        return {"trades": 0}
    pct = np.array([x for _, x, _ in results])
    pts = np.array([DELTA * (x + COST_PCT) / 100 * e - COST_OPT_PTS for _, x, e in results])  # the option's own cost, not the index's
    years = sorted({d.year for d, _, _ in results})
    half = years[len(years) // 2] if len(years) > 1 else years[0]
    by_year = {str(y): round(float(np.mean([x for d, x, _ in results if d.year == y])), 3) for y in years}
    part = lambda f: [x for d, x, _ in results if f(d)]
    halves = [part(lambda d: d.year < half), part(lambda d: d.year >= half)]
    era = part(lambda d: d >= GIFT_ERA)
    return {"trades": len(pct), "won": round(float((pct > 0).mean()), 3), "avg_pct": round(float(pct.mean()), 3),
            "opt_pts": round(float(pts.mean()), 2), "rs_per_lot": round(float(pts.mean()) * LOT),
            "halves_pct": [round(float(np.mean(h)), 3) if h else None for h in halves],
            "years_up": f"{sum(v > 0 for v in by_year.values())}/{len(by_year)}", "by_year": by_year,
            "since_jul_2023": {"trades": len(era), "avg_pct": round(float(np.mean(era)), 3) if era else None}}


def run(rows, move=0.004, sides=(1, -1), stop=None):
    res = []
    for r in rows:
        s = signal(r, move, sides)
        if s:
            res.append((r["d"], trade(r, s, stop), r["entry"]))
    return summary(rows, res)


def passes(s):
    up = s.get("years_up", "0/1").split("/")
    return bool(s.get("trades", 0) >= 100 and s["won"] >= 0.5 and all(h is not None and h > 0 for h in s["halves_pct"])
                and int(up[0]) >= 7 and (s["since_jul_2023"]["avg_pct"] or 0) > 0)


def main():
    try:
        d = os.environ.get("INTRADAY_DIR", "intra")
        rows = days(*(intraday_data.load(d, k) for k in ("nifty", "banknifty", "vix")))
        out = {"days": len(rows), "from": str(rows[0]["d"]), "to": str(rows[-1]["d"])}
        for stop in (None, STOP_PCT):
            name = "no stop" if stop is None else f"{stop}% stop"
            rule = run(rows, stop=stop)
            rule["passes"] = passes(rule)
            out[name] = {"rule (0.4%, both sides)": rule,
                         "CALL only": run(rows, sides=(1,), stop=stop), "PUT only": run(rows, sides=(-1,), stop=stop),
                         "0.3%": run(rows, move=0.003, stop=stop), "0.6%": run(rows, move=0.006, stop=stop)}
        print("STUDY trendday " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY trendday failed: {e!r}", flush=True)
