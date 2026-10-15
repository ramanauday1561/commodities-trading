"""Where can NIFTY direction calls be right far more often than 61%? Three honest tests (walk-forward, no lookahead).

1. selective  next-day close direction from the evening before, but only on the days the model is most confident.
              The confidence cut-off for each day comes only from earlier days' predictions.
2. gap        direction of the opening gap (open vs previous close) from what happened between NIFTY's previous close
              and 09:10 IST: US index futures, Nikkei, KOSPI, Hang Seng (hourly bars, ~2 years).
3. intraday   direction of today's close vs yesterday's close, from where NIFTY trades at 10:15, 11:15 ... 14:15 IST.

"improve" (after 14 Oct 2026, a day the overnight markets leaned up and NIFTY fell 0.44%): does any of these help?
4. extra overnight inputs for the pre-open calls: Indian ADRs in New York (HDFC Bank, ICICI Bank, Infosys), crude
   oil and USD/INR, and a separate input for a big previous day (>1%), each compared with the live feature set
   on the same days, refitted walk-forward exactly like the live call.
5. after a big day: how often NIFTY rose the next day, and gapped up, after a rise or fall of more than 1%.
6. afternoon momentum: does the 12:15-13:15 move continue to the close? (14 Oct fell sharply from about 13:00.)
7. early checkpoints from 15-minute bars (only ~60 days): direction at 09:45 and 10:00 vs the close.

Every result is reported with the share of days it applies to and the "always up" rate on those same days.
Usage: python scripts/accuracy_study.py   (run in CI; Yahoo is needed)
"""
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import yfinance as yf

import gbm
from exo import load_exo
import todaycall as tc
from todaycall import OVERNIGHT, hourly, share_table, value_at  # shared with the live card

NIFTY = "^NSEI"
COVERAGE = (1.0, 0.5, 0.3, 0.2, 0.1)


def daily(symbol):
    raw = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].fillna(0.0).iloc[:-1]


def selective(full, exo, test_days=750):
    """1. Next-day direction classifier, scored by how confident it was."""
    X = gbm.features(full, exo).values
    n = len(full)
    logc = np.log(full["close"].values)
    y1 = np.full(n, np.nan)
    y1[:-1] = logc[1:] - logc[:-1]
    valid = (np.arange(n) >= gbm.WARMUP) & ~np.isnan(y1)
    probs, outcome = [], []
    for t in range(n - test_days, n):
        tr = np.where(valid & (np.arange(n) <= t - 2))[0]
        m = lgb.train(dict(gbm.PARAMS, objective="binary"), lgb.Dataset(X[tr], (y1[tr] > 0).astype(float)),
                      num_boost_round=gbm.ROUNDS)
        probs.append(float(m.predict(X[[t - 1]])[0]))
        outcome.append(float(y1[t - 1] > 0))
    p, o = np.array(probs), np.array(outcome)
    call = p > 0.5
    return {"test_days": test_days, "from": str(full.index[n - test_days].date()),
            "table": share_table(np.abs(p - 0.5), (call == (o == 1)).astype(float), o)}


def gap(nd):
    """2. Opening gap direction from overnight markets (ridge regression refitted every day on earlier days)."""
    series = {k: hourly(t) for k, t in OVERNIGHT.items()}
    rows = []
    days = nd.index
    for i in range(1, len(days)):
        d, prev = days[i], days[i - 1]
        t_prev = pd.Timestamp(prev.date()).tz_localize("UTC") + pd.Timedelta(hours=10)        # 15:30 IST
        t_open = pd.Timestamp(d.date()).tz_localize("UTC") + pd.Timedelta(hours=3, minutes=40)  # 09:10 IST
        if t_prev < min(s.index[0] for s in series.values()):
            continue
        f = {k: value_at(s, t_open) / value_at(s, t_prev) - 1 for k, s in series.items()}
        f["prev_day"] = nd["close"].iloc[i - 1] / nd["close"].iloc[i - 2] - 1 if i >= 2 else 0.0
        rows.append({"d": d, **f, "gap": nd["open"].iloc[i] / nd["close"].iloc[i - 1] - 1,
                     "day": nd["close"].iloc[i] / nd["close"].iloc[i - 1] - 1})
    df = pd.DataFrame(rows).set_index("d").replace([np.inf, -np.inf], np.nan)
    feats = list(OVERNIGHT) + ["prev_day"]
    df[feats] = df[feats].fillna(0.0)
    df = df[df["gap"].abs() > 1e-6]                       # days where Yahoo's open equals the previous close are unusable
    def walk(target):
        preds = np.full(len(df), np.nan)
        Xa, ya = df[feats].values, df[target].values
        for i in range(60, len(df)):
            X, y = Xa[:i], ya[:i]
            mu, sd = X.mean(0), X.std(0) + 1e-12
            Z = (X - mu) / sd
            w = np.linalg.solve(Z.T @ Z + 5.0 * np.eye(len(feats)), Z.T @ (y - y.mean()))
            preds[i] = y.mean() + ((Xa[i] - mu) / sd) @ w
        return preds, ya

    preds, ya = walk("gap")
    pc, yc = walk("day")
    okc = ~np.isnan(pc)
    close_table = share_table(np.abs(pc[okc]), (np.sign(pc[okc]) == np.sign(yc[okc])).astype(float),
                              (yc[okc] > 0).astype(float), min_hist=20)
    ok = ~np.isnan(preds)
    p, g = preds[ok], ya[ok]
    rule = np.sign(df["es"].values[ok])
    return {"days": int(ok.sum()), "from": str(df.index[ok][0].date()), "gap_up_rate": round(float((g > 0).mean()), 3),
            "es_futures_sign_rule_accuracy": round(float((rule == np.sign(g)).mean()), 3),
            "corr_by_market": {k: round(float(np.corrcoef(df[k].values[ok], g)[0, 1]), 3) for k in feats},
            "table": share_table(np.abs(p), (np.sign(p) == np.sign(g)).astype(float), (g > 0).astype(float), min_hist=20),
            "close_from_overnight": close_table}


def intraday(nd):
    """3. Today's close direction (vs yesterday's close) from where NIFTY trades at each hour."""
    bars = hourly(NIFTY)
    prev_close = nd["close"].shift(1)
    out = {}
    for hh, mm in ((4, 45), (5, 45), (6, 45), (7, 45), (8, 45)):          # 10:15 ... 14:15 IST (bar ends, UTC)
        label = f"{(hh * 60 + mm + 330) // 60:02d}:{(hh * 60 + mm + 330) % 60:02d} IST"
        moves, final = [], []
        for d in nd.index:
            t = pd.Timestamp(d.date()).tz_localize("UTC") + pd.Timedelta(hours=hh, minutes=mm)
            day_bars = bars.loc[pd.Timestamp(d.date()).tz_localize("UTC"):t]
            if len(day_bars) == 0 or pd.isna(prev_close.loc[d]):
                continue
            moves.append(float(day_bars.iloc[-1]) / prev_close.loc[d] - 1)
            final.append(nd["close"].loc[d] / prev_close.loc[d] - 1)
        m, f = np.array(moves), np.array(final)
        res = {"days": len(m), "accuracy_all_days": round(float((np.sign(m) == np.sign(f)).mean()), 3)}
        for thr in (0.0025, 0.005, 0.0075, 0.01):
            sel = np.abs(m) > thr
            res[f"move_over_{thr * 100:.2f}pct"] = {"share": round(float(sel.mean()), 3),
                                                    "accuracy": round(float((np.sign(m[sel]) == np.sign(f[sel])).mean()), 3)
                                                    if sel.any() else None}
        out[label] = res
    return out


EXTRA = {"hdb": "HDB", "ibn": "IBN", "infy": "INFY", "crude": "CL=F", "usdinr": "INR=X"}
VARIANTS = {"live": [], "adrs": ["hdb", "ibn", "infy"], "crude_inr": ["crude", "usdinr"], "big_day": ["prev_big"],
            "all": ["hdb", "ibn", "infy", "crude", "usdinr", "prev_big"]}


def _calls(df, feats, target):
    preds = tc.walk_forward(df[feats].values, df[target].values)
    ok = ~np.isnan(preds)
    p, y = preds[ok], df[target].values[ok]
    t = share_table(np.abs(p), (np.sign(p) == np.sign(y)).astype(float), (y > 0).astype(float), min_hist=20)
    return {k: t[k] for k in ("top_100pct", "top_50pct", "top_20pct", "top_10pct")}


def overnight_variants(nd):
    """4. Same walk-forward ridge as the live call, with extra overnight inputs. Every variant is scored on the same days."""
    series = {k: hourly(t) for k, t in {**OVERNIGHT, **EXTRA}.items()}
    df = tc.history(nd, series)
    cols = list(OVERNIGHT) + list(EXTRA) + ["prev_day"]
    df[cols] = df[cols].fillna(0.0)
    df["prev_big"] = np.where(df["prev_day"].abs() > 0.01, df["prev_day"], 0.0)
    out = {"days": len(df), "from": str(df.index[0].date()),
           "corr_with_gap": {k: round(float(np.corrcoef(df[k], df["gap"])[0, 1]), 3) for k in cols + ["prev_big"]},
           "corr_with_day": {k: round(float(np.corrcoef(df[k], df["day"])[0, 1]), 3) for k in cols + ["prev_big"]}}
    for name, extra in VARIANTS.items():
        feats = tc.FEATS + extra
        out[name] = {"gap": _calls(df, feats, "gap"), "close": _calls(df, feats, "day")}
    return out


def after_big_day(nd):
    """5. Next-day behaviour after a big move (full daily history)."""
    r = nd["close"].pct_change()
    g = nd["open"] / nd["close"].shift(1) - 1
    nxt, gap_next = r.shift(-1), g.shift(-1)
    ok = nxt.notna() & r.notna() & (gap_next.abs() > 1e-6)
    res = {"all_days": {"days": int(ok.sum()), "next_up": round(float((nxt[ok] > 0).mean()), 3),
                        "gap_up": round(float((gap_next[ok] > 0).mean()), 3)}}
    for name, sel in (("after_up_over_1pct", r > 0.01), ("after_down_over_1pct", r < -0.01),
                      ("after_up_over_1_5pct", r > 0.015), ("after_down_over_1_5pct", r < -0.015)):
        m = ok & sel
        res[name] = {"days": int(m.sum()), "next_up": round(float((nxt[m] > 0).mean()), 3) if m.any() else None,
                     "gap_up": round(float((gap_next[m] > 0).mean()), 3) if m.any() else None,
                     "next_mean_pct": round(float(nxt[m].mean() * 100), 3) if m.any() else None}
    recent = nd.index >= nd.index[-1] - pd.Timedelta(days=3 * 365)
    m = ok & (r > 0.01) & recent
    res["after_up_over_1pct_last_3y"] = {"days": int(m.sum()), "next_up": round(float((nxt[m] > 0).mean()), 3) if m.any() else None}
    return res


def afternoon_momentum(nd):
    """6. Does the 12:15-13:15 IST move carry on to the close? Hourly bars (~2 years)."""
    bars = hourly(NIFTY)
    rows = []
    for d in nd.index:
        day = pd.Timestamp(d.date()).tz_localize("UTC")
        a, b = value_at(bars, day + pd.Timedelta(hours=6, minutes=45)), value_at(bars, day + pd.Timedelta(hours=7, minutes=45))
        if len(bars.loc[day:day + pd.Timedelta(hours=6, minutes=45)]) < 3:
            continue
        rows.append((b / a - 1, nd["close"].loc[d] / b - 1))
    x, y = np.array(rows).T
    out = {"days": len(x), "continues_all": round(float((np.sign(x) == np.sign(y)).mean()), 3),
           "corr": round(float(np.corrcoef(x, y)[0, 1]), 3)}
    for thr in (0.002, 0.003, 0.005):
        m = np.abs(x) > thr
        out[f"hour_move_over_{thr * 100:.1f}pct"] = {"share": round(float(m.mean()), 3),
                                                     "continues": round(float((np.sign(x[m]) == np.sign(y[m])).mean()), 3) if m.any() else None,
                                                     "rest_of_day_same_sign_mean_pct": round(float((np.sign(x[m]) * y[m]).mean() * 100), 3) if m.any() else None}
    return out


def early_checkpoints(nd):
    """7. Close direction (vs yesterday) from the move at 09:45 and 10:00 IST. 15-minute bars: only ~60 days."""
    raw = yf.download(NIFTY, period="60d", interval="15m", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    idx = pd.to_datetime(raw.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    bars = pd.Series(raw["Close"].values, index=idx + pd.Timedelta(minutes=15)).dropna()
    prev = nd["close"].shift(1)
    out = {}
    for label, hm in (("09:45", (4, 15)), ("10:00", (4, 30)), ("10:15", (4, 45))):
        mv, fin = [], []
        for d in nd.index:
            day = pd.Timestamp(d.date()).tz_localize("UTC")
            if day < bars.index[0] or pd.isna(prev.loc[d]):
                continue
            seg = bars.loc[day:day + pd.Timedelta(hours=hm[0], minutes=hm[1])]
            if not len(seg):
                continue
            mv.append(float(seg.iloc[-1]) / prev.loc[d] - 1)
            fin.append(nd["close"].loc[d] / prev.loc[d] - 1)
        m, f = np.array(mv), np.array(fin)
        res = {"days": len(m), "accuracy_all": round(float((np.sign(m) == np.sign(f)).mean()), 3) if len(m) else None}
        for thr in (0.0025, 0.005):
            s = np.abs(m) > thr
            res[f"over_{thr * 100:.2f}pct"] = {"share": round(float(s.mean()), 3),
                                               "accuracy": round(float((np.sign(m[s]) == np.sign(f[s])).mean()), 3) if s.any() else None}
        out[label] = res
    return out


FUTURES_CHECKS_IST = ("09:30", "12:30", "15:30", "17:30", "19:00", "20:30")


def futures_intraday(ticker):
    """8. Gold / silver / crude: does the move since the previous settlement, seen at a time of the Indian day, keep its
    sign to today's settlement (~23:00 IST)? Hourly bars (~2 years); the daily close of a future is its settlement.
    "rest_continues" asks the tradable question: does the rest of the day (checkpoint -> settlement) go the same way?"""
    nd = daily(ticker)
    bars = hourly(ticker)
    prev = nd["close"].shift(1)
    out = {}
    for label in FUTURES_CHECKS_IST:
        h, m = map(int, label.split(":"))
        mv, fin = [], []
        for d in nd.index:
            if pd.isna(prev.loc[d]):
                continue
            t = pd.Timestamp(d.date()).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=h, minutes=m)
            t = t.tz_convert("UTC")
            seg = bars.loc[t - pd.Timedelta(hours=3):t]                  # need a fresh price, not yesterday's
            if not len(seg) or t < bars.index[0]:
                continue
            mv.append(float(seg.iloc[-1]) / prev.loc[d] - 1)
            fin.append(nd["close"].loc[d] / prev.loc[d] - 1)
        x, f = np.array(mv), np.array(fin)
        rest = (1 + f) / (1 + x) - 1                                       # from the checkpoint to the settlement
        res = {"days": len(x), "accuracy_all": round(float((np.sign(x) == np.sign(f)).mean()), 3) if len(x) else None,
               "up_rate": round(float((f > 0).mean()), 3) if len(x) else None,
               "rest_continues_all": round(float((np.sign(x) == np.sign(rest)).mean()), 3) if len(x) else None}
        for thr in (0.0025, 0.005, 0.01):
            sel = np.abs(x) > thr
            res[f"over_{thr * 100:.2f}pct"] = {"share": round(float(sel.mean()), 3),
                                               "accuracy": round(float((np.sign(x[sel]) == np.sign(f[sel])).mean()), 3) if sel.any() else None,
                                               "rest_continues": round(float((np.sign(x[sel]) == np.sign(rest[sel])).mean()), 3) if sel.any() else None,
                                               "rest_mean_same_side_pct": round(float((np.sign(x[sel]) * rest[sel]).mean() * 100), 3) if sel.any() else None}
        out[label] = res
    return out


def commodity(key):
    inst = next(i for i in json.load(open("scripts/instruments.json")) if i["key"] == key)
    try:
        print(f"STUDY futures_intraday {key} " + json.dumps(futures_intraday(inst["ticker"])), flush=True)
    except Exception as e:
        print(f"STUDY futures_intraday {key} failed: {e!r}", flush=True)


INDIA = ["hdb", "ibn", "infy", "crude", "usdinr"]
FEATURE_SETS = {"live": [], "sox": ["sox"], "india": INDIA, "india_sox": INDIA + ["sox"]}
TIER_TOP = (("very_strong", 0.10), ("strong", 0.20), ("lean", 0.50))


def _tiers_with_cap(X, y, cap_z):
    """Walk-forward calls like the live card, with each day's tier from the confidence of earlier calls. With cap_z,
    a day whose inputs sit more than cap_z standard deviations from the training data gets at most "lean"."""
    preds = tc.walk_forward(X, y)
    rows = []
    for i in range(tc.MIN_HIST, len(y)):
        past = np.abs(preds[tc.MIN_HIST:i])
        if len(past) < 20:
            continue
        mu, sd = X[:i].mean(0), X[:i].std(0) + 1e-12
        z = float(np.max(np.abs((X[i] - mu) / sd)))
        tier = "none"
        for name, top in TIER_TOP:
            if abs(preds[i]) >= np.quantile(past, 1 - top):
                tier = name
                break
        if cap_z is not None and z > cap_z and tier in ("very_strong", "strong"):
            tier = "lean"
        rows.append((tier, z, float(np.sign(preds[i]) == np.sign(y[i]))))
    return rows


def _summ(rows, extreme_z=4.0):
    out = {}
    order = ["very_strong", "strong", "lean", "none"]
    for i, name in enumerate(order[:-1]):                    # cumulative, like the page: "calls at least this strong"
        hit = [r[2] for r in rows if r[0] in order[:i + 1]]
        out[name] = {"days": len(hit), "accuracy": round(float(np.mean(hit)), 3) if hit else None}
    ext = [r for r in rows if r[1] > extreme_z]
    out["extreme_days"] = {"days": len(ext), "accuracy_all": round(float(np.mean([r[2] for r in ext])), 3) if ext else None,
                           "top_tier_calls": sum(r[0] in ("very_strong", "strong") for r in ext),
                           "top_tier_accuracy": round(float(np.mean([r[2] for r in ext if r[0] in ("very_strong", "strong")])), 3)
                           if any(r[0] in ("very_strong", "strong") for r in ext) else None}
    out["all_days"] = {"days": len(rows), "accuracy": round(float(np.mean([r[2] for r in rows])), 3)}
    return out


def extreme_days(nd):
    """9. After 15 Oct 2026 (KOSPI -7.6%, Nikkei -4.9% in a chip-led sell-off; NIFTY rose ~1.9% after a 'very strong'
    call for lower): India-specific inputs, the semiconductor index, and a cap on confidence when inputs are extreme."""
    extra = {"hdb": "HDB", "ibn": "IBN", "infy": "INFY", "crude": "CL=F", "usdinr": "INR=X", "sox": "^SOX"}
    series = {k: hourly(t) for k, t in {**OVERNIGHT, **extra}.items()}
    df = tc.history(nd, series)
    cols = list(OVERNIGHT) + list(extra) + ["prev_day"]
    df[cols] = df[cols].fillna(0.0)
    out = {"days": len(df), "from": str(df.index[0].date())}
    # how extreme were this morning's inputs (overnight to 09:10 IST on the last day in the data + 1)?
    today = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    for name, extra_feats in FEATURE_SETS.items():
        feats = tc.FEATS + extra_feats
        X = df[feats].values
        res = {}
        for target in ("gap", "day"):
            y = df[target].values
            res[target] = {"no_cap": _summ(_tiers_with_cap(X, y, None)),
                           "cap_z4": _summ(_tiers_with_cap(X, y, 4.0)),
                           "cap_z3": _summ(_tiers_with_cap(X, y, 3.0))}
        # replay this morning's call with this feature set
        try:
            prev_day = nd.index[-1].date()
            f = tc.overnight_features(series, prev_day, today.date(), tc.utc_at(today.date(), tc.CUTOFF),
                                      nd["close"].iloc[-1] / nd["close"].iloc[-2] - 1)
            x = np.array([f[k] for k in feats])
            mu, sd = X.mean(0), X.std(0) + 1e-12
            res["today"] = {"date": str(today.date()), "max_abs_z": round(float(np.max(np.abs((x - mu) / sd))), 2),
                            "z_by_input": {k: round(float(v), 2) for k, v in zip(feats, (x - mu) / sd)},
                            "gap_pred_pct": round(tc.ridge_predict(tc.ridge_fit(X, df["gap"].values), x) * 100, 3),
                            "close_pred_pct": round(tc.ridge_predict(tc.ridge_fit(X, df["day"].values), x) * 100, 3)}
        except Exception as e:
            res["today"] = repr(e)
        out[name] = res
    return out


def extreme():
    nd = daily(NIFTY)
    try:
        print("STUDY extreme_days " + json.dumps(extreme_days(nd)), flush=True)
    except Exception as e:
        print(f"STUDY extreme_days failed: {e!r}", flush=True)


def improve():
    nd = daily(NIFTY)
    for name, fn in (("overnight_variants", lambda: overnight_variants(nd)), ("after_big_day", lambda: after_big_day(nd)),
                     ("afternoon_momentum", lambda: afternoon_momentum(nd)), ("early_checkpoints", lambda: early_checkpoints(nd))):
        try:
            print(f"STUDY {name} " + json.dumps(fn()), flush=True)
        except Exception as e:
            print(f"STUDY {name} failed: {e!r}", flush=True)


def main():
    nd = daily(NIFTY)
    inst = next(i for i in json.load(open("scripts/instruments.json")) if i["key"] == "nifty")
    exo = load_exo(inst.get("exo"), nd.index)
    for name, fn in (("selective", lambda: selective(nd, exo)), ("gap", lambda: gap(nd)), ("intraday", lambda: intraday(nd))):
        try:
            print(f"STUDY {name} " + json.dumps(fn()), flush=True)
        except Exception as e:
            print(f"STUDY {name} failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()
