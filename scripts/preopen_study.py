"""After 19 Oct 2026 (pre-open close call -0.09% "no clear call"; NIFTY fell 1.11% from a flat open as private banks
slid after weekend results and crude neared $109): which missing inputs would have helped, tested walk-forward.

The pre-open inputs mix information of different ages. US index futures from NIFTY's close to 09:10 IST include both
the US cash session and the hours after it (Asia, and on Mondays the whole weekend), while the New York-listed Indian
ADRs stop at the US close. On 19 Oct the ADRs (+1.3 to +1.9%, Friday's session, before the bank results) cancelled
the fresher futures and Asian markets (Nasdaq futures -1.2%, Nikkei -1.3%), so the call landed near zero.

Variants (each compared with the live inputs on the same days, for the opening gap, the close vs yesterday and the
tradable open -> close move):
  fresh    US futures split at the US cash close: es_day / nq_day (NIFTY close -> US close) and es_night / nq_night
           (US close -> 09:10 IST, the part the ADRs have not seen)
  weekend  ADR moves on days after a weekend or holiday as separate inputs (older news by the time NIFTY opens)
  vix      India VIX: change on the previous session and its level against the past year
  bank     Bank Nifty's previous-session move relative to NIFTY's
  crude    crude oil and USD/INR in the close and open -> close models too (the gap call already uses them)
Intraday: from 11:15 / 12:15 IST, does following the move since the open to the close earn money after costs?

Every model is a ridge refitted each day on earlier days only (todaycall.walk_forward); tiers come from earlier days'
confidence. Usage: python scripts/experiment.py nifty 0 0 preopen   (CI; Yahoo is needed)
"""
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import todaycall as tc
import yfinance as yf

from accuracy_study import NIFTY
from open_study import by_level, hourly_ohlc, trades
from todaycall import OVERNIGHT, value_at

NY = ZoneInfo("America/New_York")
ADRS = ["hdb", "ibn", "infy"]


def us_close_utc(day):
    """16:00 New York on `day`, in UTC."""
    return pd.Timestamp(datetime.combine(day, time(16, 0), NY)).tz_convert("UTC")


def add_features(df, nd, series, vix, bank):
    rows = []
    days = list(nd.index)
    pos = {d: i for i, d in enumerate(days)}
    for d in df.index:
        i = pos[d]
        prev = days[i - 1].date()
        t_prev, t_us, t_cut = tc.utc_at(prev, tc.PREV_CLOSE), us_close_utc(prev), tc.utc_at(d.date(), tc.CUTOFF)
        r = {}
        for k in ("es", "nq"):
            s = series[k]
            a, b, c = value_at(s, t_prev), value_at(s, t_us), value_at(s, t_cut)
            ok = all(np.isfinite(v) and v for v in (a, b, c))
            r[f"{k}_day"] = b / a - 1 if ok else 0.0
            r[f"{k}_night"] = c / b - 1 if ok else 0.0
        wk = float((d.date() - prev).days > 1)
        r["weekend"] = wk
        for k in ADRS:
            r[f"{k}_wk"] = df.at[d, k] * wk
            r[f"{k}_wd"] = df.at[d, k] * (1 - wk)
        pv = vix.loc[:days[i - 1]]
        if len(pv) > 2:
            r["vix_chg"] = float(np.log(pv.iloc[-1] / pv.iloc[-2]))
            hist = pv.iloc[-250:]
            r["vix_z"] = float((pv.iloc[-1] - hist.mean()) / (hist.std() + 1e-9))
        else:
            r["vix_chg"] = r["vix_z"] = 0.0
        pb = bank.loc[:days[i - 1]]
        nret = nd["close"].iloc[i - 1] / nd["close"].iloc[i - 2] - 1 if i >= 2 else 0.0
        r["bank_rel"] = float(pb.iloc[-1] / pb.iloc[-2] - 1 - nret) if len(pb) > 2 and pb.index[-1] == days[i - 1] else 0.0
        rows.append(r)
    extra = pd.DataFrame(rows, index=df.index).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return pd.concat([df, extra], axis=1)


def daily(symbol):
    """Daily candles; today's row only once the NSE session has closed (accuracy_study.daily always drops it)."""
    raw = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    out = raw.rename(columns=str.lower)[["open", "high", "low", "close"]]
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    if len(out) and out.index[-1].date() >= now.date() and (now.hour, now.minute) < (15, 45):
        out = out.iloc[:-1]
    return out


def daily_close(symbol):
    return daily(symbol)["close"]


LIVE_GAP = tc.GAP_FEATS
LIVE_DAY = tc.FEATS
FRESH = ["es_day", "es_night", "nq_day", "nq_night", "nikkei", "kospi", "hangseng", "prev_day"]
VARIANTS = {
    "live": None,                                          # the live feature sets (gap: GAP_FEATS, close: FEATS)
    "fresh": FRESH + ADRS + ["crude", "usdinr"],
    "fresh_weekend": FRESH + [f"{k}_{s}" for k in ADRS for s in ("wd", "wk")] + ["crude", "usdinr"],
    "live_vix": "+vix",
    "live_bank": "+bank",
    "live_crude": "+crude",
    "fresh_weekend_vix": FRESH + [f"{k}_{s}" for k in ADRS for s in ("wd", "wk")] + ["crude", "usdinr", "vix_chg", "vix_z"],
    "fresh_weekend_vix_bank": FRESH + [f"{k}_{s}" for k in ADRS for s in ("wd", "wk")] + ["crude", "usdinr", "vix_chg",
                                                                                          "vix_z", "bank_rel"],
}


def feats_for(variant, target):
    base = LIVE_GAP if target in ("gap", "o2c") else LIVE_DAY
    v = VARIANTS[variant]
    if v is None:
        return base
    if v == "+vix":
        return base + ["vix_chg", "vix_z"]
    if v == "+bank":
        return base + ["bank_rel"]
    if v == "+crude":
        return base + [c for c in ("crude", "usdinr") if c not in base]
    return v


def score(pred, y, o2c, valid):
    p, t = pred[valid], y[valid]
    out = {"days": int(valid.sum()), "accuracy_all": round(float((np.sign(p) == np.sign(t)).mean()), 3),
           "corr": round(float(np.corrcoef(p, t)[0, 1]), 3),
           "pred_sd_vs_actual_sd": round(float(p.std() / (t.std() + 1e-12)), 3)}
    big = np.abs(t) > 0.008
    out["big_days"] = {"days": int(big.sum()), "sign_right": round(float((np.sign(p[big]) == np.sign(t[big])).mean()), 3)
                       if big.any() else None}
    tab = tc.share_table(np.abs(p), (np.sign(p) == np.sign(t)).astype(float), (t > 0).astype(float),
                         levels=(1.0, 0.5, 0.2, 0.1), min_hist=20, pnl=np.sign(p) * o2c[valid])
    out["tiers"] = {k: {"accuracy": v["accuracy"], "days": v["days"], "from_open": v.get("from_open")}
                    for k, v in tab.items()}
    return out


def intraday_follow(nd, df):
    """Follow the move since the open at 11:15 / 12:15 IST to the close (after costs)."""
    bars = hourly_ohlc(NIFTY)
    out = {}
    for label, (h, m) in (("11:15", (5, 45)), ("12:15", (6, 45))):
        side, ret = [], []
        for d in df.index:
            day = pd.Timestamp(d.date()).tz_localize("UTC")
            seg = bars.loc[day:day + pd.Timedelta(hours=h, minutes=m)]
            if len(seg) < 2:
                continue
            p = float(seg["close"].iloc[-1])
            o, c = float(nd["open"].loc[d]), float(nd["close"].loc[d])
            mv = p / o - 1
            side.append(mv)
            ret.append(c / p - 1)
        mv, ret = np.array(side), np.array(ret)
        res = {}
        for thr in (0.0025, 0.004, 0.006):
            s = np.where(np.abs(mv) > thr, np.sign(mv), 0).astype(int)
            res[f"move_over_{thr * 100:.2f}pct"] = trades(s, ret)
        out[label] = res
    return out


def study():
    nd = daily(NIFTY)
    series = {k: tc.hourly(t) for k, t in {**OVERNIGHT, **tc.INDIA}.items()}
    df = tc.history(nd, series)
    vix, bank = daily_close("^INDIAVIX"), daily_close("^NSEBANK")
    df = add_features(df, nd, series, vix, bank)
    df["o2c"] = (1 + df["day"]) / (1 + df["gap"]) - 1
    o2c = df["o2c"].values
    out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date()),
           "weekend_days": int(df["weekend"].sum()),
           "vix_rows_nonzero": int((df["vix_z"] != 0).sum()), "bank_rows_nonzero": int((df["bank_rel"] != 0).sum()),
           "corr_with_o2c": {k: round(float(np.corrcoef(df[k], df["o2c"])[0, 1]), 3)
                             for k in ["es_day", "es_night", "nq_day", "nq_night", "hdb_wd", "hdb_wk", "vix_chg", "vix_z",
                                       "bank_rel", "crude"]},
           "corr_with_day": {k: round(float(np.corrcoef(df[k], df["day"])[0, 1]), 3)
                             for k in ["es_day", "es_night", "nq_day", "nq_night", "hdb_wd", "hdb_wk", "vix_chg", "vix_z",
                                       "bank_rel", "crude"]}}
    preds = {}
    for target in ("gap", "day", "o2c"):
        y = df[target].values
        res = {}
        for name in VARIANTS:
            p = tc.walk_forward(df[feats_for(name, target)].values, y)
            preds[(name, target)] = p
        valid = np.all([~np.isnan(preds[(n, target)]) for n in VARIANTS], axis=0)
        for name in VARIANTS:
            res[name] = score(preds[(name, target)], y, o2c, valid)
            if target == "o2c":
                res[name]["trades"] = by_level(np.nan_to_num(preds[(name, target)]), o2c, valid)
        out[target] = res
    # the last few days, 19 Oct 2026 included once it has closed
    last = df.iloc[-5:]
    out["last_days"] = {str(d.date()): {"actual_day_pct": round(float(r["day"] * 100), 2),
                                        "actual_o2c_pct": round(float(r["o2c"] * 100), 2),
                                        **{f"{n}_close_pred_pct": round(float(preds[(n, 'day')][df.index.get_loc(d)] * 100), 2)
                                           for n in ("live", "fresh_weekend", "fresh_weekend_vix")},
                                        **{f"{n}_o2c_pred_pct": round(float(preds[(n, 'o2c')][df.index.get_loc(d)] * 100), 2)
                                           for n in ("live", "fresh_weekend", "fresh_weekend_vix")}}
                         for d, r in last.iterrows()}
    try:
        out["intraday_follow"] = intraday_follow(nd, df)
    except Exception as e:
        out["intraday_follow"] = repr(e)
    return out


def main():
    try:
        print("STUDY preopen " + json.dumps(study()), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY preopen failed: {e!r}", flush=True)


if __name__ == "__main__":
    main()


HEAVY = ["HDFCBANK.NS", "ICICIBANK.NS", "RELIANCE.NS", "INFY.NS", "TCS.NS", "AXISBANK.NS", "KOTAKBANK.NS", "SBIN.NS"]


def earnings_probe():
    """Can past and upcoming results dates of NIFTY heavyweights be read from Yahoo (for an event-risk input)?"""
    out = {}
    for t in HEAVY:
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=60)
            if ed is None or not len(ed):
                out[t] = "none"
                continue
            idx = pd.DatetimeIndex(ed.index)
            out[t] = {"rows": len(ed), "first": str(idx.min().date()), "last": str(idx.max().date()),
                      "recent": [str(x.date()) for x in sorted(idx)[-6:]]}
        except Exception as e:
            out[t] = repr(e)[:200]
    print("STUDY earnings " + json.dumps(out), flush=True)
