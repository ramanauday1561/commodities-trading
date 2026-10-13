"""Where can NIFTY direction calls be right far more often than 61%? Three honest tests (walk-forward, no lookahead).

1. selective  next-day close direction from the evening before, but only on the days the model is most confident.
              The confidence cut-off for each day comes only from earlier days' predictions.
2. gap        direction of the opening gap (open vs previous close) from what happened between NIFTY's previous close
              and 09:10 IST: US index futures, Nikkei, KOSPI, Hang Seng (hourly bars, ~2 years).
3. intraday   direction of today's close vs yesterday's close, from where NIFTY trades at 10:15, 11:15 ... 14:15 IST.

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

NIFTY = "^NSEI"
OVERNIGHT = {"es": "ES=F", "nq": "NQ=F", "nikkei": "^N225", "kospi": "^KS11", "hangseng": "^HSI"}
COVERAGE = (1.0, 0.5, 0.3, 0.2, 0.1)


def daily(symbol):
    raw = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].fillna(0.0).iloc[:-1]


def hourly(symbol):
    raw = yf.download(symbol, period="730d", interval="1h", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Close"])
    idx = pd.to_datetime(raw.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return pd.Series(raw["Close"].values, index=idx + pd.Timedelta(hours=1)).sort_index()   # indexed by bar END


def value_at(series, t):
    """Last price known at time t (bar end <= t)."""
    s = series.loc[:t]
    return float(s.iloc[-1]) if len(s) else np.nan


def share_table(conf, correct, up, levels=COVERAGE, min_hist=60):
    """Accuracy when only the most confident calls are made. The cut-off for day i is the (1-c) quantile of the
    confidence of days before i, so it never looks ahead."""
    conf, correct, up = map(np.asarray, (conf, correct, up))
    out = {}
    for c in levels:
        take = np.zeros(len(conf), bool)
        for i in range(min_hist, len(conf)):
            take[i] = c >= 1.0 or (i > 0 and conf[i] >= np.quantile(conf[:i], 1 - c))
        n = int(take.sum())
        out[f"top_{int(c * 100)}pct"] = {"days": n, "share": round(n / max(len(conf) - min_hist, 1), 3),
                                         "accuracy": round(float(correct[take].mean()), 3) if n else None,
                                         "always_up_same_days": round(float(up[take].mean()), 3) if n else None}
    return out


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
        rows.append({"d": d, **f, "gap": nd["open"].iloc[i] / nd["close"].iloc[i - 1] - 1})
    df = pd.DataFrame(rows).set_index("d").replace([np.inf, -np.inf], np.nan)
    feats = list(OVERNIGHT) + ["prev_day"]
    df[feats] = df[feats].fillna(0.0)
    df = df[df["gap"].abs() > 1e-6]                       # days where Yahoo's open equals the previous close are unusable
    preds = np.full(len(df), np.nan)
    Xa, ya = df[feats].values, df["gap"].values
    for i in range(60, len(df)):
        X, y = Xa[:i], ya[:i]
        mu, sd = X.mean(0), X.std(0) + 1e-12
        Z = (X - mu) / sd
        w = np.linalg.solve(Z.T @ Z + 5.0 * np.eye(len(feats)), Z.T @ (y - y.mean()))
        preds[i] = y.mean() + ((Xa[i] - mu) / sd) @ w
    ok = ~np.isnan(preds)
    p, g = preds[ok], ya[ok]
    rule = np.sign(df["es"].values[ok])
    return {"days": int(ok.sum()), "from": str(df.index[ok][0].date()), "gap_up_rate": round(float((g > 0).mean()), 3),
            "es_futures_sign_rule_accuracy": round(float((rule == np.sign(g)).mean()), 3),
            "corr_by_market": {k: round(float(np.corrcoef(df[k].values[ok], g)[0, 1]), 3) for k in feats},
            "table": share_table(np.abs(p), (np.sign(p) == np.sign(g)).astype(float), (g > 0).astype(float), min_hist=20)}


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
