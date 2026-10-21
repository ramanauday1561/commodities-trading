"""Experiment mode "rolls" (20 Oct 2026): what the futures roll adjustment (rolls.py) changes, and the NIFTY crude input.

crude / gold / silver: LightGBM on Yahoo's raw continuous history vs the roll-adjusted one, on the live backtest days
(same days as predict.py), plus the next-day forecast each one gives against the price trading now.
nifty: the close call, the from-open signal and the gap call with and without the crude input (Yahoo's hourly CL=F also
jumps at every roll, e.g. 18 Sep and 15 Oct 2026, and its weight in the calls is close to zero).
"""
import json

import numpy as np
import pandas as pd
import yfinance as yf

import rolls
from calendars import next_sessions
from evalutil import backtest_indices
from exo import load_exo
from gbm import run_gbm


def _raw(symbol):
    raw = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].fillna(0.0)


def futures(inst):
    raw_all = _raw(inst["ticker"])
    log = rolls.update(inst["ticker"], raw_all, None)
    adj_all = rolls.adjust(raw_all, log)
    live = float(raw_all["close"].iloc[-1])                  # the newest candle may still be live: keep it out
    out = {"rolls": log, "latest_candle": [str(raw_all.index[-1].date()), round(live, 2)]}
    n = len(raw_all) - 1
    wide = sorted(set((backtest_indices(n, 2048) or []) + np.linspace(512, 2047, 40).astype(int).tolist()))
    for name, df in (("raw", raw_all.iloc[:-1]), ("adjusted", adj_all.iloc[:-1])):
        exo = load_exo(inst.get("exo"), df.index)
        future = pd.DatetimeIndex(next_sessions(df.index[-1].date(), 4, inst.get("calendar")))
        last = float(df["close"].iloc[-1])
        res = run_gbm(df, future, last, wide, exo, inst.get("big_move_pct"))
        f0 = res["forecast"][0]
        out[name] = {"last_close": round(last, 2), "next": {k: f0[k] for k in ("time", "close", "cal_p10", "cal_p90", "prob_up")},
                     "next_vs_latest_candle_pct": round((f0["close"] / live - 1) * 100, 2),
                     "backtest": res["backtest"], "risk": res["risk"]}
    return out


def nifty():
    import todaycall as tc
    from accuracy_study import _wf_tiers
    nd = tc.daily()
    nd = nd[nd.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
    series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
    df = tc.history(nd, series)
    day, gap = df["day"].values, df["gap"].values
    o2c = (1 + day) / (1 + gap) - 1

    def trades(p, tiers):
        top = np.isin(tiers, ["very_strong", "strong"])
        pnl = np.sign(p[top]) * o2c[top] * 100 - tc.TRADE_COST_PCT
        h = len(pnl) // 2
        return {"trades": int(top.sum()), "win_rate": round(float((pnl > 0).mean()), 3), "avg_pct": round(float(pnl.mean()), 3),
                "first_half_avg": round(float(pnl[:h].mean()), 3), "second_half_avg": round(float(pnl[h:].mean()), 3)}

    def hits(p, tiers, y):
        ok, top = tiers != "na", np.isin(tiers, ["very_strong", "strong"])
        hit = np.sign(p) == np.sign(y)
        h = int(ok.sum()) // 2
        okh = np.where(ok)[0]
        return {"days": int(ok.sum()), "hit_all": round(float(hit[ok].mean()), 3), "hit_top20": round(float(hit[top].mean()), 3),
                "first_half": round(float(hit[okh[:h]].mean()), 3), "second_half": round(float(hit[okh[h:]].mean()), 3)}

    out = {"days": len(df), "from": str(df.index[0].date())}
    for name, drop in (("with_crude", []), ("no_crude", ["crude"])):
        fresh = [k for k in tc.FRESH_FEATS if k not in drop]
        gapf = [k for k in tc.GAP_FEATS if k not in drop]
        pc, tc_ = _wf_tiers(df[fresh].values, day)
        po, to = _wf_tiers(df[fresh].values, o2c)
        pg, tg = _wf_tiers(df[gapf].values, gap)
        out[name] = {"close": hits(pc, tc_, day), "from_open_signal": trades(po, to), "gap": hits(pg, tg, gap)}
    return out


def main(key):
    try:
        if key == "nifty":
            res = nifty()
        else:
            inst = next(i for i in json.load(open("scripts/instruments.json")) if i["key"] == key)
            res = futures(inst)
        print(f"STUDY rolls {key} " + json.dumps(res), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY rolls {key} failed: {e!r}", flush=True)
