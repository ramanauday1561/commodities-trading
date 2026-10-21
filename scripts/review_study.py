"""Experiment mode "review" (21 Oct 2026): patterns behind 19 and 21 Oct, tested before any change.

On both days NIFTY opened higher than the overnight markets implied, then sold off all day (19 Oct: +0.02% open,
-1.11% close; 21 Oct: +0.55% open vs a +0.10% gap call, then below yesterday's close by noon). Heavyweight bank results
had just come out (HDFC Bank's ADR -3.3% overnight on 21 Oct), and a very large IPO (Jio Platforms) opened on 21 Oct.
Questions, each scored on ~2 years of hourly data, walk-forward, after ~0.03% costs and in both halves:
  A. gap surprise: when NIFTY opens further than the pre-open gap call said, does the excess fade by the close?
     (trade at the 09:15 open against the surprise; needs a call just after the open)
  B. failed gap: a gap up that is below the open by 10:15 (or a gap down above it) -> follow the failure 10:15 -> close
  C. banks after results: the HDFC Bank / ICICI ADR move on the sessions after their results, as an input to the close
     call and the from-open signal (interaction term), vs the live inputs
"""
import json

import numpy as np

import todaycall as tc
from open_study import build, trades
from preopen_study import results_dates


def halves_hit(hit):
    h = len(hit) // 2
    return [round(float(hit[:h].mean()), 3), round(float(hit[h:].mean()), 3)] if h else None


def rule(name, side, ret, out):
    out[name] = trades(side.astype(int), ret)


def main():
    try:
        nd, df = build()                                         # hourly-history days with open / 10:15 / close
        out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date())}
        gap_pred = tc.walk_forward(df[tc.GAP_FEATS].values, df["gap"].values)
        ok = ~np.isnan(gap_pred)
        ok[:np.argmax(ok) + 20] = False
        surprise = np.where(ok, df["gap"].values - np.nan_to_num(gap_pred), 0.0)
        o2c, rest, gap = df["o2c"].values, df["rest"].values, df["gap"].values
        f1 = df["f1"].values                                     # open -> 10:15
        out["surprise_sd_pct"] = round(float(surprise[ok].std() * 100), 3)
        # A. fade the gap surprise from the open
        a = {}
        for thr in (0.0015, 0.0025, 0.004):
            m = ok & (np.abs(surprise) > thr)
            rule(f"fade_surprise_gt_{thr * 100:.2f}pct", np.where(m, -np.sign(surprise), 0), o2c, a)
            rule(f"follow_surprise_gt_{thr * 100:.2f}pct", np.where(m, np.sign(surprise), 0), o2c, a)
        up = ok & (surprise > 0.0025)
        rule("fade_up_surprise_only_gt_0.25pct", np.where(up, -1, 0), o2c, a)
        out["A_gap_surprise_from_open"] = a
        # B. failed gaps at 10:15
        b = {}
        for thr in (0.002, 0.004):
            fail_up = ok & (gap > thr) & (f1 < 0)
            fail_dn = ok & (gap < -thr) & (f1 > 0)
            held_up = ok & (gap > thr) & (f1 > 0)
            rule(f"gap_up_gt_{thr * 100:.1f}pct_failed_short_1015", np.where(fail_up, -1, 0), rest, b)
            rule(f"gap_down_gt_{thr * 100:.1f}pct_failed_long_1015", np.where(fail_dn, 1, 0), rest, b)
            rule(f"gap_up_gt_{thr * 100:.1f}pct_held_long_1015", np.where(held_up, 1, 0), rest, b)
        out["B_failed_gap_at_1015"] = b
        # C. bank ADRs after results
        rd = results_dates()
        days = list(nd.index)
        pos = {d: i for i, d in enumerate(days)}
        banks = ("HDFCBANK", "ICICIBANK")
        after = np.array([any(days[pos[d] - 1] <= x < d for t, ds in rd.items() if t.split(".")[0] in banks for x in ds)
                          if pos.get(d, 0) > 0 else False for d in df.index])
        df["bank_res"] = np.where(after, df["hdb"] + df["ibn"], 0.0)
        out["bank_results_days"] = int(after.sum())
        c = {}
        for name, feats in (("live", tc.FRESH_FEATS), ("with_bank_results", tc.FRESH_FEATS + ["bank_res"])):
            for target, y in (("close", df["day"].values), ("from_open", o2c)):
                p = tc.walk_forward(df[feats].values, y)
                m = ~np.isnan(p)
                hit = np.sign(p[m]) == np.sign(y[m])
                conf, top, seen = np.abs(p), np.zeros(len(p), bool), []
                for i in np.where(m)[0]:
                    if len(seen) >= 20:
                        top[i] = conf[i] >= np.quantile(seen, 0.8)
                    seen.append(conf[i])
                r = {"hit": round(float(hit.mean()), 3), "halves": halves_hit(hit),
                     "hit_on_bank_results_days": round(float((np.sign(p) == np.sign(y))[m & after].mean()), 3)
                     if (m & after).any() else None,
                     "top20_trades": trades(np.where(top, np.sign(p), 0).astype(int), o2c)}
                c[f"{name}_{target}"] = r
        out["C_banks_after_results"] = c
        # D. the hourly check by move size: moves of this size vs moves at least this big (what the page showed)
        table = tc.intraday_table(nd, tc.hourly(tc.NIFTY))
        out["D_hourly_check_by_move_size"] = {
            utc_hm: {f"{b * 100:.2f}pct": {"at_least": row[b]["accuracy"], "this_size": tc.band_accuracy(row, b),
                                            "share": row[b]["share"]} for b in tc.BUCKETS if b in row}
            for utc_hm, row in ((f"{h:02d}:{m:02d}UTC", table[(h, m)]) for h, m in tc.CHECKPOINTS)}
        # today's inputs for the record
        out["recent"] = {str(d.date()): {"gap_pct": round(float(g * 100), 2), "surprise_pct": round(float(s * 100), 2),
                                         "open_to_1015_pct": round(float(x * 100), 2), "o2c_pct": round(float(o * 100), 2)}
                         for d, g, s, x, o in list(zip(df.index, gap, surprise, f1, o2c))[-6:]}
        print("STUDY review " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY review failed: {e!r}", flush=True)
