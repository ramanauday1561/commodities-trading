"""NIFTY calls you can trade from the open: what earns money from the 09:15 open, or from 10:15, to the close?

The live close call is ~77% right against yesterday's close on strong days, but only ~49% right from the open:
being right vs yesterday is mostly the opening gap, which nobody can trade. This study scores every rule on what a
trade earns (entry -> close, minus ~0.03% costs), walk-forward throughout (each day's model and its confidence
tier come only from earlier days). Hourly bars: ~2 years.

C. Models trained on the tradable move itself
   open_now     the live pre-open close call (target: close vs yesterday), traded from the open: the baseline
   open_target  same pre-open inputs (+ADRs, crude, USD/INR) but trained on open -> close
   at_open      also knows the actual opening gap and the "gap surprise" (actual gap minus the pre-open gap
                call): did NIFTY open further than the overnight markets implied? (needs a call at ~09:16)
   m1015_follow 10:15 rule: follow the move since yesterday's close (the earlier study: 50.5% wins)
   m1015        10:15 model, target 10:15 -> close: gap, first-hour move and range, where 10:15 sits in that
                range, Bank Nifty vs NIFTY in the first hour, yesterday's move, US futures overnight
D. Fewer, better calls
   tiers        every model is reported for all days and its top 50% / 20% / 10% most confident days
   agree        10:15 trade only when the 10:15 model and the at-open model point the same way
B. Indian calendar: NIFTY option expiry days (weekly; the last one of each month is the monthly expiry). Thursday
   until Aug 2025, Tuesday from Sep 2025; a holiday moves it to the session before. How the day behaves on expiry
   vs other days, and the at-open / 10:15 models with expiry inputs added.

Each model is also split into the first and second half of its test days: an edge that only exists in one half is
not one to trade. Usage: python scripts/experiment.py nifty 0 0 open   (CI; Yahoo is needed)
"""
import json

import numpy as np
import pandas as pd
import yfinance as yf

import todaycall as tc
from accuracy_study import COST_PCT, NIFTY, _wf_tiers, daily
from todaycall import OVERNIGHT

BANK = "^NSEBANK"
TUESDAY_FROM = pd.Timestamp("2025-09-01")       # NSE moved NIFTY expiry from Thursday to Tuesday
FIRST_HOUR_END = (4, 45)                         # 10:15 IST in UTC (end of the 09:15-10:15 bar)
LEVELS = (("all", 1.0), ("top50", 0.5), ("top20", 0.2), ("top10", 0.1))


def hourly_ohlc(symbol, period="730d"):
    raw = yf.download(symbol, period=period, interval="1h", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    idx = pd.to_datetime(raw.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    out = raw.rename(columns=str.lower)[["open", "high", "low", "close"]]
    out.index = idx + pd.Timedelta(hours=1)                                       # bar END, like todaycall.hourly
    return out.sort_index()


def first_hour(bars, d):
    """open, high, low, close of the 09:15-10:15 IST bar on day d, or None."""
    day = pd.Timestamp(d.date()).tz_localize("UTC")
    end = day + pd.Timedelta(hours=FIRST_HOUR_END[0], minutes=FIRST_HOUR_END[1])
    seg = bars.loc[end - pd.Timedelta(minutes=59):end]
    if not len(seg):
        return None
    r = seg.iloc[-1]
    return float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])


def expiry_flags(index):
    """weekly / monthly NIFTY expiry flags for the sessions in `index` (holidays: the session before)."""
    days = pd.DatetimeIndex(index).normalize()
    weekly = pd.Series(0.0, index=index)
    by_week = {}
    for d, orig in zip(days, index):
        by_week.setdefault((d.isocalendar()[0], d.isocalendar()[1]), []).append((d, orig))
    for rows in by_week.values():
        target = 1 if rows[0][0] >= TUESDAY_FROM else 3
        cands = [orig for d, orig in rows if d.weekday() <= target]
        if cands:
            weekly.loc[max(cands)] = 1.0
    monthly = pd.Series(0.0, index=index)
    exp = weekly[weekly > 0].index
    for _, grp in pd.Series(exp, index=exp).groupby([exp.year, exp.month]):
        monthly.loc[grp.index.max()] = 1.0
    return weekly, monthly


def trades(side, ret):
    m = side != 0
    if not m.any():
        return {"trades": 0}
    pnl = side[m] * ret[m] * 100 - COST_PCT
    cum = np.cumsum(pnl)
    half = len(pnl) // 2
    return {"trades": int(m.sum()), "win_rate": round(float((pnl > 0).mean()), 3),
            "avg_pct": round(float(pnl.mean()), 3), "total_pct": round(float(pnl.sum()), 1),
            "max_dd_pct": round(float(np.max(np.maximum.accumulate(cum) - cum)), 1),
            "t_stat": round(float(pnl.mean() / (pnl.std(ddof=1) / np.sqrt(len(pnl)))), 2) if len(pnl) > 2 else None,
            "first_half_avg": round(float(pnl[:half].mean()), 3) if half else None,
            "second_half_avg": round(float(pnl[half:].mean()), 3) if half else None}


def by_level(pred, ret, valid, conf_hist=None):
    """Trades on all valid days and on the most confident ones (cut-off from earlier days only)."""
    out = {}
    conf = np.abs(pred)
    for name, top in LEVELS:
        take = np.zeros(len(pred), bool)
        seen = []
        for i in range(len(pred)):
            if not valid[i]:
                continue
            if len(seen) >= 20:
                take[i] = top >= 1.0 or conf[i] >= np.quantile(seen, 1 - top)
            seen.append(conf[i])
        out[name] = trades(np.where(take, np.sign(pred), 0).astype(int), ret)
    return out


def build():
    nd = daily(NIFTY)
    series = {k: tc.hourly(t) for k, t in {**OVERNIGHT, **tc.INDIA}.items()}
    df = tc.history(nd, series)
    nb, bb = hourly_ohlc(NIFTY), hourly_ohlc(BANK)
    rows = []
    for d in df.index:
        n1, b1 = first_hour(nb, d), first_hour(bb, d)
        if n1 is None:
            rows.append(None)
            continue
        opn, close = float(nd["open"].loc[d]), float(nd["close"].loc[d])
        _, hi, lo, p = n1
        hi, lo = max(hi, opn), min(lo, opn)
        f1 = p / opn - 1
        rows.append({"p1015": p, "o2c": close / opn - 1, "rest": close / p - 1, "f1": f1,
                     "range1": (hi - lo) / opn, "pos1": (p - lo) / (hi - lo) - 0.5 if hi > lo else 0.0,
                     "bank_rel": (b1[3] / b1[0] - 1 - f1) if b1 else 0.0})
    keep = [r is not None for r in rows]
    df = df[keep].copy()
    for k in rows[[i for i, r in enumerate(rows) if r is not None][0]]:
        df[k] = [r[k] for r in rows if r is not None]
    df["weekly_exp"], df["monthly_exp"] = expiry_flags(df.index)
    return nd, df


def calendar_stats(df):
    gapfade = -np.sign(df["gap"]) * df["o2c"]
    out = {}
    for name, m in (("weekly_expiry", df["weekly_exp"] > 0), ("monthly_expiry", df["monthly_exp"] > 0),
                    ("not_expiry", df["weekly_exp"] == 0)):
        s = df[m]
        out[name] = {"days": int(m.sum()), "avg_abs_open_to_close_pct": round(float(s["o2c"].abs().mean() * 100), 3),
                     "avg_abs_1015_to_close_pct": round(float(s["rest"].abs().mean() * 100), 3),
                     "open_to_close_up_rate": round(float((s["o2c"] > 0).mean()), 3),
                     "gap_fades_rate": round(float((gapfade[m] > 0).mean()), 3),
                     "first_hour_continues_rate": round(float((np.sign(s["f1"]) == np.sign(s["rest"])).mean()), 3)}
    return out


def study():
    nd, df = build()
    prev_close = nd["close"].shift(1).reindex(df.index).values
    move1015 = df["p1015"].values / prev_close - 1
    gap_pred, _ = _wf_tiers(df[tc.GAP_FEATS].values, df["gap"].values)
    df["gap_surprise"] = np.where(np.isnan(gap_pred), 0.0, df["gap"] - np.nan_to_num(gap_pred))
    valid = ~np.isnan(gap_pred)
    valid[:np.argmax(valid) + tc.MIN_HIST] = False          # every model scored on the same days, after warm-up
    o2c, rest = df["o2c"].values, df["rest"].values
    feats_1015 = ["gap", "f1", "range1", "pos1", "bank_rel", "prev_day", "es", "nq"]
    exp = ["weekly_exp", "monthly_exp"]
    models = {
        "open_now": (tc.FEATS, "day", o2c),
        "open_target": (tc.GAP_FEATS, "o2c", o2c),
        "at_open": (tc.GAP_FEATS + ["gap", "gap_surprise"], "o2c", o2c),
        "at_open_expiry": (tc.GAP_FEATS + ["gap", "gap_surprise"] + exp, "o2c", o2c),
        "m1015": (feats_1015, "rest", rest),
        "m1015_expiry": (feats_1015 + exp, "rest", rest),
    }
    out = {"days": int(valid.sum()), "from": str(df.index[valid][0].date()), "to": str(df.index[-1].date()),
           "cost_pct": COST_PCT, "calendar": calendar_stats(df[valid]),
           "buy_open_every_day": trades(np.where(valid, 1, 0), o2c),
           "m1015_follow": trades(np.where(valid & (np.abs(move1015) > 0.0025), np.sign(move1015), 0).astype(int), rest)}
    preds = {}
    for name, (feats, target, ret) in models.items():
        p = tc.walk_forward(df[feats].values, df[target].values)
        preds[name] = p
        out[name] = by_level(np.nan_to_num(p), ret, valid & ~np.isnan(p))
    # D: 10:15 trade only when the 10:15 model and the at-open model agree
    agree = np.sign(np.nan_to_num(preds["m1015"])) == np.sign(np.nan_to_num(preds["at_open"]))
    out["agree_m1015_at_open"] = by_level(np.where(agree, np.nan_to_num(preds["m1015"]), 0.0), rest, valid & agree)
    agree3 = agree & (np.sign(np.nan_to_num(preds["open_now"])) == np.sign(np.nan_to_num(preds["m1015"])))
    out["agree_all_three"] = by_level(np.where(agree3, np.nan_to_num(preds["m1015"]), 0.0), rest, valid & agree3)
    # B as a plain rule: short from the open on expiry days (and, for comparison, on other days)
    wk = df["weekly_exp"].values > 0
    out["short_open_weekly_expiry"] = trades(np.where(valid & wk, -1, 0), o2c)
    out["short_open_monthly_expiry"] = trades(np.where(valid & (df["monthly_exp"].values > 0), -1, 0), o2c)
    out["short_open_not_expiry"] = trades(np.where(valid & ~wk, -1, 0), o2c)
    out["expiry_by_weekday"] = {("thursday_era" if era else "tuesday_era"): trades(
        np.where(valid & wk & ((df.index < TUESDAY_FROM) == era), -1, 0), o2c) for era in (True, False)}
    # the two pre-open models pointing the same way
    both = np.sign(np.nan_to_num(preds["open_target"])) == np.sign(np.nan_to_num(preds["open_now"]))
    out["agree_open_target_open_now"] = by_level(np.where(both, np.nan_to_num(preds["open_target"]), 0.0), o2c,
                                                 valid & both)
    return out


def main():
    try:
        print("STUDY open " + json.dumps(study()), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY open failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
