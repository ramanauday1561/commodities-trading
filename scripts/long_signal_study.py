"""Experiment mode "longsignal" (28 Oct 2026): the 09:15 from-open signal tested on ~11 years instead of 2.

The live signal learns from Yahoo's hourly candles, which go back only 2 years, so it has been tested on ~65 trades.
Dukascopy's free hourly history (overnight_data.py) covers the S&P 500 and Nasdaq futures, Nikkei and Hang Seng from
2015; the US-listed shares of HDFC Bank, ICICI Bank and Infosys only need their daily US close (Yahoo, decades). KOSPI
and USD/INR have no long free history, so the long version leaves them out:
  LONG = es_day, es_night, nq_day, nq_night, nikkei, hangseng, prev_day, hdb, ibn, infy, ret3   (live: + kospi, usdinr)
Checks, all walk-forward (each day predicted only from earlier days), traded like the live signal: top-20% most
confident days, standing aside after heavyweight results and after US CPI / jobs / Fed news, from the 09:15 open to
the close with the 0.5% stop on 5-minute candles (intraday_data.py), 0.03% costs:
  1. data check: on the last 2 years, the Dukascopy-built inputs against the Yahoo-built ones (correlation)
  2. the long signal over 2015-2026: per year, both halves
  3. the last 2 years: the long signal trained on all years vs trained on the latest 500 days only, and the live signal
Rules fixed before the run: (2) "works on 11 years" needs earnings after costs in both halves and in at least 7 of the
10 full years 2016-2025; (3) switching the live signal to long training needs more per trade than the live signal in both halves
of the last 2 years and a higher total.
Result (28 Oct 2026, run 40737181025; 2,871 sessions, 2 Feb 2015 - 30 Sep 2026; 705 stood aside for results / US news):
  1. the Dukascopy inputs track the Yahoo ones: correlation 0.93 / 0.90 (S&P 500 day / night), 0.93 / 0.90 (Nasdaq),
     0.88 (Nikkei), 0.93 (Hang Seng), 0.99 (the three ADRs) over 721 shared sessions
  2. the long signal: 190 trades, 43% won, +0.116% a trade after costs (+22% in total), but +0.206% in the first half
     and +0.027% in the second; by year +1.9 +4.9 -0.2 +10.5 +1.6 +5.1 +2.6 -0.9 -2.0 +0.4 -2.2 +0.5 (2015-2026), so
     6 of 10 full years up: it FAILS the 11-year rule. The edge was real in 2015-2021 (+26%) and has gone since 2022
     (-3.3% in 2022-2026). A likely reason: since July 2023 GIFT Nifty trades almost round the clock, so the opening
     gap already prices the overnight markets and little is left for the move from the open.
  3. the last 2 years: trained on all years, 13 trades, -0.132% each; on the latest 500 days, 55 trades, +0.033%; the
     live signal 35 trades, +0.098% (-0.144% / +0.326% by half). No switch to long training.
"""
import json
import os

import numpy as np
import pandas as pd
import yfinance as yf

import history_study
import intraday_data
import overnight_data
import results_calendar as rc
import todaycall as tc
import us_events
from vix_study import stats

LONG = ["es_day", "es_night", "nq_day", "nq_night", "nikkei", "hangseng", "prev_day", "hdb", "ibn", "infy", "ret3"]
FIRST = pd.Timestamp("2015-02-02")
RECENT = 500


def nifty_daily():
    raw = yf.download(tc.NIFTY, period="max", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    today = pd.Timestamp.now(tz="Asia/Kolkata").date()
    return raw.rename(columns=str.lower)[["open", "high", "low", "close"]][raw.index.date < today]


def us_close_series(symbol):
    """Daily closes indexed by the US close (16:00 New York) in UTC, so todaycall.value_at sees them when they happen."""
    raw = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Close"])
    idx = [pd.Timestamp(d.date()).tz_localize(tc.NY) + pd.Timedelta(hours=16) for d in raw.index]
    return pd.Series(raw["Close"].values, index=pd.DatetimeIndex(idx).tz_convert("UTC")).sort_index()


def wf(X, y, window=None):
    """Walk-forward ridge like todaycall.walk_forward, optionally on the latest `window` days only; and the tiers."""
    preds = np.full(len(y), np.nan)
    for i in range(tc.MIN_HIST, len(y)):
        lo = max(0, i - window) if window else 0
        preds[i] = tc.ridge_predict(tc.ridge_fit(X[lo:i], y[lo:i]), X[i])
    tiers = np.array(["na"] * len(y), dtype=object)
    for i in range(tc.MIN_HIST + 20, len(y)):
        past = np.abs(preds[tc.MIN_HIST:i])
        tiers[i] = "none"
        for name, top in tc.TIERS:
            if abs(preds[i]) >= np.quantile(past, 1 - top):
                tiers[i] = name
                break
    return preds, tiers


def skip_days(df, nd):
    """Sessions the live signal stands aside on: after heavyweight results, after US CPI / jobs / Fed news."""
    out = np.zeros(len(df), bool)
    try:
        cal = rc.fetch()
        if cal:
            out |= rc.flags(nd.index, cal).reindex(df.index).fillna(False).values.astype(bool)
    except Exception as e:
        print(f"results calendar: {e!r}", flush=True)
    ev = us_events.fetch_all()
    days = list(nd.index.date)
    pos = {d: k for k, d in enumerate(days)}
    for j, d in enumerate(df.index.date):
        k = pos.get(d)
        if k:
            prev = days[k - 1]
            if tc.us_since(ev, prev, d):
                out[j] = True
    return out


def trades(df, preds, tiers, skip, intra, mask=None):
    """The live trade rule on these predictions: {date: % after costs} (0.5% stop on 5-minute candles)."""
    out = {}
    for j, d in enumerate(df.index.date):
        if tiers[j] not in tc.TRADE_TIERS or skip[j] or (mask is not None and not mask[j]):
            continue
        side = 1.0 if preds[j] > 0 else -1.0
        g = intra.get(d)
        if g is not None and len(g) > 60:
            out[d] = history_study.path(g, side)
        else:                                               # no candles (the May-Jul 2026 gap): open -> close, no stop
            o2c = (1 + df["day"].iloc[j]) / (1 + df["gap"].iloc[j]) - 1
            out[d] = side * o2c * 100 - tc.TRADE_COST_PCT
    return out


def summary(tr):
    ds = sorted(tr)
    r = stats(np.array([tr[d] for d in ds]))
    by = {}
    for d in ds:
        by.setdefault(d.year, []).append(tr[d])
    r["by_year_pct"] = {str(y): round(float(np.sum(v)), 1) for y, v in sorted(by.items())}
    full = {y: v for y, v in by.items() if 2015 < y < 2026}
    r["full_years_up"] = f"{sum(np.sum(v) > 0 for v in full.values())}/{len(full)}"
    return r


def main():
    try:
        od = os.environ.get("OVERNIGHT_DIR", "od")
        series = {k: overnight_data.load(od, k) for k in ("es", "nq", "nikkei", "hangseng")}
        for k, s in series.items():
            print(f"STUDY longsignal data {k}: {len(s)} hours, {s.index[0] if len(s) else '-'} to {s.index[-1] if len(s) else '-'}", flush=True)
        series.update({k: us_close_series(t) for k, t in (("hdb", "HDB"), ("ibn", "IBN"), ("infy", "INFY"))})
        nd = nifty_daily()
        df = tc.history(nd, series)
        end = min(series[k].index[-1] for k in ("es", "nq", "nikkei", "hangseng")).tz_convert(None).normalize()
        df = df[(df.index >= FIRST) & (df.index <= end)]     # Dukascopy publishes a month's file after it ends
        intra = intraday_data.load(os.environ.get("INTRADAY_DIR", "intra"), "nifty")
        o2c = ((1 + df["day"]) / (1 + df["gap"]) - 1).values
        skip = skip_days(df, nd)
        out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date()),
               "skipped_results_or_us": int(skip.sum())}

        # 1. data check against the Yahoo-built inputs of the last 2 years
        ys = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
        yd = tc.history(nd, ys)
        common = df.index.intersection(yd.index)
        out["data_check_corr"] = {k: round(float(np.corrcoef(df.loc[common, k], yd.loc[common, k])[0, 1]), 3)
                                  for k in LONG if k in yd.columns}
        out["data_check_days"] = len(common)

        # 2. the long signal over all years
        p_all, t_all = wf(df[LONG].values, o2c)
        out["long signal, all years"] = summary(trades(df, p_all, t_all, skip, intra))

        # 3. the last 2 years: long training, recent-window training, and the live signal (Yahoo inputs, 2 years)
        recent = np.zeros(len(df), bool)
        recent[-RECENT:] = True
        out["last 2 years: long signal, trained on all years"] = summary(trades(df, p_all, t_all, skip, intra, recent))
        p_win, t_win = wf(df[LONG].values, o2c, window=RECENT)
        out["last 2 years: long signal, latest 500 days only"] = summary(trades(df, p_win, t_win, skip, intra, recent))
        yo2c = ((1 + yd["day"]) / (1 + yd["gap"]) - 1).values
        p_live, t_live = wf(yd[tc.OPEN_FEATS].values, yo2c)
        yskip = skip_days(yd, nd)
        live = trades(yd, p_live, t_live, yskip, intra)
        start = df.index[-RECENT].date()
        out["last 2 years: live signal (Yahoo, 2 years)"] = summary({d: v for d, v in live.items()
                                                                    if start <= d <= df.index[-1].date()})

        a = out["long signal, all years"]
        out["works_on_11_years"] = bool(a.get("trades", 0) >= 50 and all(h is not None and h > 0 for h in a["avg_halves"])
                                        and int(a["full_years_up"].split("/")[0]) >= 7)
        lt, lv = out["last 2 years: long signal, trained on all years"], out["last 2 years: live signal (Yahoo, 2 years)"]
        out["switch_to_long_training"] = bool(lt.get("trades", 0) >= 20 and lv.get("trades", 0) and
                                              lt["total_pct"] > lv["total_pct"] and
                                              all(x > y for x, y in zip(lt["avg_halves"], lv["avg_halves"])))
        print("STUDY longsignal " + json.dumps(out), flush=True)
        return out
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY longsignal failed: {e!r}", flush=True)
