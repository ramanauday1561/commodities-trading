"""Backtest LightGBM variants side by side before changing the live model.

Usage: python scripts/experiment.py <key> [test_days] [step] [mode]
  mode "variants" (default): LightGBM variants for the expected close
  mode "risk": big-move probability and likely-range methods (see risk_and_range)
  mode "accuracy": NIFTY only, see accuracy_study.py
  mode "improve": NIFTY only, extra pre-open inputs and intraday patterns (see accuracy_study.improve)
  mode "events": big-move risk and ranges with and without US CPI / jobs / Fed calendar inputs
  mode "strategy": NIFTY only, trading rules scored on what an open or 10:15 entry earns to the close, after costs
  mode "preopen": NIFTY only, missing pre-open inputs after 19 Oct 2026 (preopen_study.py); "results": calls on days
    after heavyweight results; "earnings": can Yahoo serve results dates; "resultsrisk": results days as an input to
    big-move risk and ranges (19 Oct 2026: slightly worse, not used)
  mode "open": NIFTY only, calls traded from the open or 10:15, selective calls and expiry days (open_study.py)
  mode "rolls": futures history with and without the contract-roll adjustment; NIFTY calls without crude (roll_study.py)
  mode "vix": NIFTY only, India VIX as an input or a stand-aside filter for the from-open signal (vix_study.py)
  mode "resultsize": NIFTY only, how many of the heaviest stocks count as results days (results_size_study.py)
  mode "hourly": NIFTY only, next-hour and rest-of-day forecasts from 1-hour candles (hourly_study.py)
  mode "extreme": NIFTY only, India inputs, the chip index and a confidence cap for extreme overnight moves
  mode "commodity": gold/silver/crude, the move so far during the Indian day vs the settlement (accuracy_study)
  mode "dailyfill": daily candles rebuilt from 15-minute bars vs Yahoo's own daily rows (last ~55 sessions)

Every variant is retrained walk-forward (only data known before each test day) and scored on the same test days:
the last `test_days` trading days, every `step`-th day. Reported per variant: average miss (%) of the next close,
direction hit rate, and a paired comparison against the current model (mean difference in miss, with a t-statistic;
|t| < 2 means the difference is not distinguishable from luck).
"""
import json
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
import yfinance as yf

import gbm
from exo import load_exo


def load(symbol):
    raw = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].fillna(0.0)
    return df.iloc[:-1]            # the newest candle may still be live


def walk_forward(full, X, tests, rounds=gbm.ROUNDS, params=None, half_life=None, window=None):
    n = len(full)
    logc = np.log(full["close"].values)
    y1 = np.full(n, np.nan)
    y1[:-1] = logc[1:] - logc[:-1]
    valid = (np.arange(n) >= gbm.WARMUP) & ~np.isnan(y1)
    p = dict(gbm.PARAMS, objective="regression", **(params or {}))
    preds = []
    for t in tests:
        tr = np.where(valid & (np.arange(n) <= t - 2))[0]
        if window:
            tr = tr[-window:]
        w = None
        if half_life:
            w = 0.5 ** ((tr[-1] - tr) / half_life)
        m = lgb.train(p, lgb.Dataset(X[tr], gbm.winsorize(y1[tr]), weight=w), num_boost_round=rounds)
        preds.append(float(m.predict(X[[t - 1]])[0]))
    return np.array(preds)


def score(full, tests, pred_ret):
    prev = full["close"].values[np.array(tests) - 1]
    act = full["close"].values[np.array(tests)]
    pred = prev * np.exp(pred_ret)
    miss = np.abs(pred - act) / act * 100
    move = np.sign(act - prev)
    call = np.sign(pred - prev)
    hit = np.where(call == 0, 0.5, (call == move).astype(float))
    return miss, hit


def auc(p, y):
    """Probability that a random big-move day got a higher score than a random calm day (0.5 = no skill)."""
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    r = pd.Series(np.concatenate([pos, neg])).rank().values
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def interval_score(lo, hi, y, alpha=0.2):
    """Winkler score of a (1-alpha) interval: width plus a penalty for misses (lower is better)."""
    return (hi - lo) + 2 / alpha * np.maximum(lo - y, 0) + 2 / alpha * np.maximum(y - hi, 0)


def risk_and_range(key, inst, full, X, tests, flag=None, label=""):
    """Big-move probability (|next-day move| > big_move_pct) and 80% ranges for the next close, walk-forward."""
    n = len(full)
    logc = np.log(full["close"].values)
    y1 = np.full(n, np.nan)
    y1[:-1] = logc[1:] - logc[:-1]
    valid = (np.arange(n) >= gbm.WARMUP) & ~np.isnan(y1)
    thr = np.log(1 + inst["big_move_pct"] / 100)
    big = (np.abs(y1) > thr).astype(float)
    p_model, p_clim, p_recent, ys = [], [], [], []
    rng = {"fixed": [], "quantile": []}
    for t in tests:
        tr = np.where(valid & (np.arange(n) <= t - 2))[0]
        x = X[[t - 1]]
        cls = lgb.train(dict(gbm.PARAMS, objective="binary"), lgb.Dataset(X[tr], big[tr]), num_boost_round=gbm.ROUNDS)
        p_model.append(float(cls.predict(x)[0]))
        p_clim.append(float(big[tr].mean()))
        p_recent.append(float(big[tr[-60:]].mean()))
        yw = gbm.winsorize(y1[tr])
        m = float(gbm.fit(X[tr], yw, "regression").predict(x)[0])
        q10 = float(gbm.fit(X[tr], yw, "quantile", 0.1).predict(x)[0])
        q90 = float(gbm.fit(X[tr], yw, "quantile", 0.9).predict(x)[0])
        res = y1[tr] - y1[tr].mean()                      # the current method: one width from all past errors
        rng["fixed"].append((m + np.quantile(res, 0.1), m + np.quantile(res, 0.9)))
        rng["quantile"].append((min(q10, m), max(q90, m)))
        ys.append(y1[t - 1])                              # return from day t-1 to day t
    y = np.array(ys)
    yb = (np.abs(y) > thr).astype(float)
    out = {"big_move_pct": inst["big_move_pct"], "big_day_rate": round(float(yb.mean()), 3), "risk": {}, "range": {}}
    clim_brier = float(((np.array(p_clim) - yb) ** 2).mean())
    for name, p in (("climatology", p_clim), ("last_60_days", p_recent), ("model", p_model)):
        p = np.array(p)
        brier = float(((p - yb) ** 2).mean())
        out["risk"][name] = {"brier": round(brier, 4), "skill_vs_climatology": round(1 - brier / clim_brier, 3),
                             "auc": round(auc(p, yb), 3), "mean_p": round(float(p.mean()), 3)}
    # coverage-corrected quantile range: widen/narrow by the factor that gave 80% on the previous 120 test days only
    q = np.array(rng["quantile"])
    mid = q.mean(axis=1)
    half = (q[:, 1] - q[:, 0]) / 2
    scaled = []
    for i in range(len(y)):
        s = 1.0
        if i >= 60:
            z = np.abs(y[max(0, i - 120):i] - mid[max(0, i - 120):i]) / half[max(0, i - 120):i]
            s = float(np.quantile(z, 0.8))
        scaled.append((mid[i] - s * half[i], mid[i] + s * half[i]))
    rng["quantile_calibrated"] = scaled
    for name, iv in rng.items():
        iv = np.array(iv)
        lo, hi = iv[:, 0], iv[:, 1]
        out["range"][name] = {"coverage": round(float(((y >= lo) & (y <= hi)).mean()), 3),
                              "avg_width_pct": round(float((hi - lo).mean() * 100), 3),
                              "interval_score": round(float(interval_score(lo, hi, y).mean() * 100), 4)}
    # does the range widen on days that turn out wild? (correlation of predicted width with the size of the move)
    for name, iv in rng.items():
        iv = np.array(iv)
        out["range"][name]["width_vs_move_corr"] = round(float(np.corrcoef(iv[:, 1] - iv[:, 0], np.abs(y))[0, 1]), 3)
    if flag is not None:                                 # the same scores on event days only, e.g. US CPI / Fed / jobs days
        f = np.array([bool(flag[t - 1]) for t in tests])
        if f.any():
            ev = {"days": int(f.sum()), "big_day_rate": round(float(yb[f].mean()), 3)}
            for name in ("climatology", "model"):
                p = np.array(p_clim if name == "climatology" else p_model)[f]
                ev[f"brier_{name}"] = round(float(((p - yb[f]) ** 2).mean()), 4)
                ev[f"mean_p_{name}"] = round(float(p.mean()), 3)
            iv = np.array(rng["quantile_calibrated"])[f]
            ev["range_coverage"] = round(float(((y[f] >= iv[:, 0]) & (y[f] <= iv[:, 1])).mean()), 3)
            ev["range_width_pct"] = round(float((iv[:, 1] - iv[:, 0]).mean() * 100), 3)
            ev["interval_score"] = round(float(interval_score(iv[:, 0], iv[:, 1], y[f]).mean() * 100), 4)
            ev["avg_abs_move_pct"] = round(float(np.abs(y[f]).mean() * 100), 3)
            ev["avg_abs_move_other_days_pct"] = round(float(np.abs(y[~f]).mean() * 100), 3)
            out["event_days"] = ev
    print(f"RISK {key} {label}" + json.dumps(out), flush=True)
    return out


def dailyfill_check(inst):
    """How close is a daily candle rebuilt from 15-minute bars to the official daily row? (see dailyfill.py)"""
    import yfinance as yf
    from dailyfill import daily_from_intraday
    get = lambda **kw: yf.download(inst["ticker"], auto_adjust=False, progress=False, **kw)
    bars, daily = get(period="60d", interval="15m"), get(period="3mo", interval="1d")
    for df in (bars, daily):
        df.columns = [str(c[0] if isinstance(c, tuple) else c).lower() for c in df.columns]
    h, m = map(int, inst["close"].split(":"))
    diffs = {k: [] for k in ("open", "high", "low", "close")}
    days, skipped = 0, 0
    for day, row in daily.dropna(subset=["close"]).iterrows():
        if pd.Timestamp(day).tz_localize(None) < pd.Timestamp(bars.index[0]).tz_localize(None) + pd.Timedelta(days=2):
            continue
        r = daily_from_intraday(bars, day.date(), inst["tz"], h, m, inst.get("calendar"))
        if r is None:
            skipped += 1
            continue
        days += 1
        for k in diffs:
            diffs[k].append(abs(r[k] / row[k] - 1) * 100)
    out = {"days": days, "skipped": skipped}
    for k, v in diffs.items():
        if v:
            out[k] = {"mean_pct": round(float(np.mean(v)), 3), "p90_pct": round(float(np.percentile(v, 90)), 3),
                      "max_pct": round(float(np.max(v)), 3)}
    print("DAILYFILL " + json.dumps({"key": inst["key"], **out}), flush=True)


def main(key, test_days=750, step=2, mode="variants"):
    if mode == "commodity":
        if key != "nifty":
            import accuracy_study
            accuracy_study.commodity(key)
        return
    if mode == "calendar":                               # just print the parsed US event calendar
        if key == "nifty":
            import us_events
            from collections import Counter
            ev = us_events.fetch_all()
            for k, v in ev.items():
                print(f"CAL {k} per year " + json.dumps(dict(sorted(Counter(d.year for d in v).items()))), flush=True)
                for y in sorted({d.year for d in v})[-3:]:
                    print(f"CAL {k} {y}: " + ", ".join(d.isoformat() for d in v if d.year == y), flush=True)
            html = us_events._get(us_events.FOMC_CURRENT)
            t = us_events._text(html)
            i = t.find("2027 FOMC Meetings")
            print("CAL 2027 text: " + t[i:i + 900], flush=True)
        return
    if mode == "strategy":
        if key == "nifty":
            import accuracy_study
            accuracy_study.strategy_main()
        return
    if mode in ("preopen", "earnings", "results"):
        if key == "nifty":
            import preopen_study
            {"preopen": preopen_study.main, "earnings": preopen_study.earnings_probe,
             "results": preopen_study.results_study}[mode]()
        return
    if mode == "rolls":                                   # futures roll adjustment; NIFTY with / without crude
        import roll_study
        roll_study.main(key)
        return
    if mode == "hourly":                                  # NIFTY: next-hour / rest-of-day forecasts from 1-hour candles
        import hourly, os, tempfile
        with tempfile.TemporaryDirectory() as out:          # also check the chart's hourly file for every market
            hourly.main(out, [key])
            p = os.path.join(out, f"hourly-{key}.json")
            if os.path.exists(p):
                b = json.load(open(p))["bars"]
                print(f"hourly {key}: {len(b)} bars, first {b[0]}, last {b[-1]}, {os.path.getsize(p) // 1024} KB", flush=True)
        if key == "nifty":
            import hourly_study
            hourly_study.main()
        return
    if mode == "oct23":                                   # NIFTY: ADRs on results days, earlier cutoff, high oil
        if key == "nifty":
            import oct23_study
            oct23_study.main()
        return
    if mode == "vix":                                     # NIFTY: India VIX as an input or a filter for the from-open signal
        if key == "nifty":
            import vix_study
            vix_study.main()
        return
    if mode == "resultsize":                              # NIFTY: 5, 11, 20 or 50 stocks as "heavyweight results"
        if key == "nifty":
            import results_size_study
            results_size_study.main()
        return
    if mode == "review":                                  # NIFTY: gap surprise, failed gaps, banks after results
        if key == "nifty":
            import review_study
            review_study.main()
        return
    if mode == "open":
        if key == "nifty":
            import open_study
            open_study.main()
        return
    if mode == "extreme":
        if key == "nifty":
            import accuracy_study
            accuracy_study.extreme()
        return
    if mode in ("accuracy", "improve"):        # NIFTY-only studies of where direction calls are most reliable
        if key == "nifty":
            import accuracy_study
            accuracy_study.main() if mode == "accuracy" else accuracy_study.improve()
        return
    inst = next(i for i in json.load(open("scripts/instruments.json")) if i["key"] == key)
    if mode == "dailyfill":
        return dailyfill_check(inst)
    full = load(inst["ticker"])
    exo = load_exo(inst.get("exo"), full.index)
    X_exo = gbm.features(full, exo).values
    X_px = gbm.features(full, None).values
    n = len(full)
    tests = list(range(n - test_days, n, step))
    prev = full["close"].values[np.array(tests) - 1]
    act = full["close"].values[np.array(tests)]
    naive_miss = np.abs(prev - act) / act * 100
    up_rate = float((act > prev).mean())
    print(f"{key}: {n} candles, {len(tests)} test days {full.index[tests[0]].date()} -> {full.index[tests[-1]].date()}, "
          f"up-rate {up_rate:.3f}, naive miss {naive_miss.mean():.3f}%", flush=True)

    if mode == "risk":
        return risk_and_range(key, inst, full, X_exo, tests)
    if mode == "events":                                 # US CPI / jobs / Fed calendar as extra inputs (us_events.py)
        import us_events
        from calendars import next_sessions
        events = us_events.fetch_all()
        if key == "nifty":                               # print the parsed calendar once, to check it by eye
            from collections import Counter
            print("FOMC per year " + json.dumps(dict(sorted(Counter(d.year for d in events.get("fomc", [])).items()))), flush=True)
            for y in (2008, 2019, 2024, 2026):
                print(f"FOMC {y}: " + ", ".join(d.isoformat() for d in events.get("fomc", []) if d.year == y), flush=True)
        nxt = next_sessions(full.index[-1].date(), 1, inst.get("calendar"))[0]
        ev = us_events.features(full.index, nxt, events, inst.get("event_timing", "after_close"))
        print(f"{key}: event columns {list(ev.columns)}, event share {ev.get('ev_any', pd.Series([0])).mean():.3f}", flush=True)
        X_ev = gbm.features(full, ev if exo is None else pd.concat([exo, ev], axis=1)).values
        flag = ev["ev_any"].values if "ev_any" in ev else None
        risk_and_range(key, inst, full, X_exo, tests, flag, "without_events ")
        return risk_and_range(key, inst, full, X_ev, tests, flag, "with_events ")

    if mode == "resultsrisk":                            # NIFTY: heavyweight results as an input to big-move risk and ranges
        if key != "nifty":
            return
        import preopen_study
        from calendars import next_sessions
        rd = preopen_study.results_dates()
        idx = pd.DatetimeIndex(full.index).normalize()
        nxt = np.array(list(idx[1:]) + [pd.Timestamp(next_sessions(full.index[-1].date(), 1, inst.get("calendar"))[0])],
                       dtype="datetime64[ns]")
        n_res = np.zeros(len(idx))
        for t, ds in rd.items():                         # dated between this close and the next one (after the close)
            days = np.array(sorted(ds), dtype="datetime64[ns]")
            n_res += (np.searchsorted(days, nxt, side="left") - np.searchsorted(days, idx.values, side="left")) > 0
        ev = pd.DataFrame({"res_n": n_res, "res_any": (n_res > 0).astype(float)}, index=full.index)
        print(f"nifty: results on {int(ev['res_any'].sum())} of {len(ev)} sessions; last: "
              + ", ".join(str(d.date()) for d in ev.index[ev["res_any"] > 0][-5:]), flush=True)
        X_res = gbm.features(full, ev if exo is None else pd.concat([exo, ev], axis=1)).values
        flag = ev["res_any"].values
        risk_and_range(key, inst, full, X_exo, tests, flag, "without_results ")
        return risk_and_range(key, inst, full, X_res, tests, flag, "with_results ")

    variants = {
        "current": dict(X=X_exo),
        "no_exo": dict(X=X_px),
        "recency_3y": dict(X=X_exo, half_life=756),
        "last_10y": dict(X=X_exo, window=2520),
        "more_trees": dict(X=X_exo, rounds=300, params=dict(learning_rate=0.02)),
        "fewer_trees": dict(X=X_exo, rounds=60),
    }
    base_miss = None
    results = {}
    for name, v in variants.items():
        X = v.pop("X")
        miss, hit = score(full, tests, walk_forward(full, X, tests, **v))
        if base_miss is None:
            base_miss = miss
        d = miss - base_miss
        t = float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if d.std() > 0 else 0.0
        dn = miss - naive_miss
        tn = float(dn.mean() / (dn.std(ddof=1) / np.sqrt(len(dn))))
        results[name] = {"miss_pct": round(float(miss.mean()), 4), "hit": round(float(hit.mean()), 3),
                         "vs_current": round(float(d.mean()), 4), "t_vs_current": round(t, 2),
                         "vs_naive": round(float(dn.mean()), 4), "t_vs_naive": round(tn, 2)}
        print(f"{key} {name:12s} " + json.dumps(results[name]), flush=True)
    print(f"RESULT {key} " + json.dumps({"up_rate": round(up_rate, 3), "naive_miss": round(float(naive_miss.mean()), 4),
                                          "days": len(tests), "variants": results}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], *(int(a) for a in sys.argv[2:4]), *sys.argv[4:5])
