"""Usage: python scripts/predict.py <key>   (keys in scripts/instruments.json)

Fetch the complete daily history (Yahoo Finance) and forecast the next 4 candles with several models:
  * base: Kronos-base, reads the latest 512 candles
  * gbm : LightGBM trained on the complete history (+ overnight/global context features)
  * blend: backtest-weighted combination of the above ("best estimate")
Every model is walk-forward backtested across the whole history; the backtest errors calibrate ranges and
probabilities, so the numbers shown on the page reflect how the models actually performed.

Environment knobs (used for A/B experiments in CI):
  KRONOS_T       sampling temperature (default 0.6)
  KRONOS_SAMPLES forecast paths per Kronos model (default 30)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import torch
import yfinance as yf

sys.path.append("Kronos")  # cloned by the workflow
from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

from blend import blend_forecast, fit_blend, platt_fit, platt_prob  # noqa: E402
from calendars import next_sessions  # noqa: E402
from dailyfill import append_day, daily_from_intraday  # noqa: E402
from evalutil import backtest_indices, expected_last_session, full_stats  # noqa: E402
from exo import load_exo  # noqa: E402
from gbm import run_gbm  # noqa: E402
import us_events  # noqa: E402
import newsfeat  # noqa: E402

COLS = ["open", "high", "low", "close"]
MODELS = {
    "base": {"label": "Kronos-base", "model": "NeoQuasar/Kronos-base",
             "tokenizer": "NeoQuasar/Kronos-Tokenizer-base", "context": 512},
}
BACKTEST_START = 2048     # first candle of the shared backtest days
HORIZON = 4               # working days to forecast
SAMPLES = int(os.environ.get("KRONOS_SAMPLES") or 30)
TEMP = float(os.environ.get("KRONOS_T") or 0.6)   # A/B on NIFTY: lower average miss than 1.0 (-8% miss)
BT_SAMPLES = 3            # samples averaged per backtest prediction
BT_BATCH = 8


def _download(symbol):
    raw = yf.download(symbol, period="max", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    # Just after a session ends Yahoo can list it with Open/High/Low but a NaN Close; take the close from the last intraday bar
    last = raw.iloc[-1]
    if pd.isna(last["Close"]) and last[["Open", "High", "Low"]].notna().all():
        try:
            intra = yf.download(symbol, period="5d", interval="15m", auto_adjust=False, progress=False)
            intra.columns = [c[0] if isinstance(c, tuple) else c for c in intra.columns]
            intra = intra.dropna(subset=["Close"])
            if len(intra) and pd.Timestamp(intra.index[-1]).tz_localize(None).normalize() == raw.index[-1].normalize():
                raw.iloc[-1, raw.columns.get_loc("Close")] = float(intra["Close"].iloc[-1])
                print(f"{symbol}: latest close filled from last 15m bar")
        except Exception as e:
            print(f"{symbol}: could not fill latest close ({e})")
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    return raw


def load_history(symbol, expected, tries=3, wait=20, session=None):
    """Daily candles. Yahoo occasionally omits the latest session, so retry until it appears. If it never does, build
    that session from the 15-minute bars (session = (tz, close_h, close_m, calendar)). Returns (candles, filled)."""
    full = None
    for attempt in range(tries):
        full = _download(symbol).rename(columns=str.lower)[COLS + ["volume"]].fillna(0.0)
        if full.index[-1].date() >= expected:
            return full, False
        print(f"latest session {expected} missing from Yahoo (last candle {full.index[-1].date()}), retry {attempt + 1}/{tries}")
        if attempt < tries - 1:
            time.sleep(wait)
    if session:
        try:
            bars = yf.download(symbol, period="5d", interval="15m", auto_adjust=False, progress=False)
            bars.columns = [c[0] if isinstance(c, tuple) else c for c in bars.columns]
            row = daily_from_intraday(bars.rename(columns=str.lower), expected, *session)
            if row:
                print(f"{symbol}: session {expected} built from 15m bars (close {row['close']:.2f})")
                return append_day(full, expected, row), True
            print(f"{symbol}: 15m bars do not cover the {expected} session yet")
        except Exception as e:
            print(f"{symbol}: could not build {expected} from 15m bars ({e!r})")
    return full, False


def usd_inr():
    """Latest USD/INR rate (for showing dollar prices in rupees). None if unavailable."""
    try:
        fx = yf.download("USDINR=X", period="10d", interval="1d", auto_adjust=False, progress=False)
        fx.columns = [c[0] if isinstance(c, tuple) else c for c in fx.columns]
        fx = fx.dropna(subset=["Close"])
        return {"rate": round(float(fx["Close"].iloc[-1]), 4), "date": fx.index[-1].strftime("%Y-%m-%d")}
    except Exception as e:
        print("USD/INR unavailable:", repr(e))
        return None


def forecast(predictor, full, context, future):
    ctx = full.tail(context)
    df, x_ts, y_ts = ctx.reset_index(drop=True), pd.Series(ctx.index), pd.Series(future)
    paths = []
    for i in range(SAMPLES):
        torch.manual_seed(i)
        p = predictor.predict(df=df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=len(future),
                              T=TEMP, top_p=0.9, sample_count=1, verbose=False)
        paths.append(p[COLS].values)
    return np.array(paths), len(df)                       # (samples, horizon, 4)


def backtest(predictor, full, context, indices):
    """Walk-forward 1-day-ahead predictions. Returns rows of (day index, previous close, actual close, predicted close)."""
    rows = []
    for s in range(0, len(indices), BT_BATCH):
        chunk = indices[s:s + BT_BATCH]
        dfs, xs, ys = [], [], []
        for t in chunk:
            w = full.iloc[t - context:t]
            dfs.append(w.reset_index(drop=True))
            xs.append(pd.Series(w.index))
            ys.append(pd.Series([full.index[t]]))
        torch.manual_seed(s)
        outs = predictor.predict_batch(dfs, xs, ys, pred_len=1, T=TEMP, top_p=0.9,
                                       sample_count=BT_SAMPLES, verbose=False)
        for t, o in zip(chunk, outs):
            rows.append((t, float(full["close"].iloc[t - 1]), float(full["close"].iloc[t]), float(o["close"].iloc[0])))
    return np.array(rows)


def build_forecast(paths, future, last_close, cal):
    mean, closes = paths.mean(axis=0), paths[:, :, 3]
    out = []
    for k, day in enumerate(future):
        o, h, l, c = (round(float(v), 2) for v in mean[k])
        row = {"time": day.strftime("%Y-%m-%d"), "open": o, "high": max(h, o, c), "low": min(l, o, c), "close": c,
               "close_p10": round(float(np.percentile(closes[:, k], 10)), 2),
               "close_p90": round(float(np.percentile(closes[:, k], 90)), 2),
               "prob_up": round(float((closes[:, k] > last_close).mean()), 3)}      # raw share of paths ending higher
        if cal:   # historical error quantiles of this model, widened with sqrt(days ahead)
            w = (k + 1) ** 0.5
            row["cal_p10"], row["cal_p90"] = round(c * (1 + cal[0] * w), 2), round(c * (1 + cal[1] * w), 2)
        out.append(row)
    return out


def calibrate_probabilities(models, rows_by_model, last_close):
    """Replace the raw 'share of paths higher' with a probability mapped from past backtest outcomes (Platt scaling)."""
    for m, rows in rows_by_model.items():
        s = rows[:, 3] / rows[:, 1] - 1
        y = rows[:, 2] > rows[:, 1]
        if len(rows) < 30:
            continue
        cal = platt_fit(s, y)
        for k, row in enumerate(models[m]["forecast"], start=1):
            row["prob_up_raw"] = row["prob_up"]
            row["prob_up"] = round(platt_prob(cal, (row["close"] / last_close - 1) / k ** 0.5), 3)


def main(key):
    inst = next(i for i in json.load(open("scripts/instruments.json")) if i["key"] == key)
    now_ex = datetime.now(ZoneInfo(inst["tz"]))
    close_h, close_m = map(int, inst["close"].split(":"))
    expected = expected_last_session(now_ex, close_h, close_m, inst.get("calendar"))
    full, filled = load_history(inst["ticker"], expected,
                                session=(inst["tz"], close_h, close_m, inst.get("calendar")) if inst.get("intraday_fill") else None)
    stale = bool(full.index[-1].date() < expected)       # newest data is older than the last finished session
    if stale:
        print(f"WARNING: data is stale (last candle {full.index[-1].date()}, expected {expected})")

    # Forecast starts from *today* (exchange time): while the session is open, today's candle is incomplete,
    # so keep it out of the model input and predict it instead.
    today_live, last_d = None, full.index[-1].date()
    if last_d > now_ex.date() or (last_d == now_ex.date() and (now_ex.hour, now_ex.minute) < (close_h, close_m)):
        row = full.iloc[-1]
        today_live = {"time": full.index[-1].strftime("%Y-%m-%d"), **{c: round(float(row[c]), 2) for c in COLS}}
        full = full.iloc[:-1]
    print(f"history: {len(full)} candles, {full.index[0].date()} -> {full.index[-1].date()}")

    future = pd.DatetimeIndex(next_sessions(full.index[-1].date(), HORIZON, inst.get("calendar")))  # exchange trading days
    last_close = float(full["close"].iloc[-1])
    n = len(full)
    models, backtests, rows_by_model = {}, {}, {}

    # Test days: 150 spread over the history after the first 2,048 candles (+ the latest), plus 40 earlier ones. These are
    # the same days used while Kronos-mini (2,048-candle context) was part of the blend, so dropping it (Oct 2026: blend
    # weight at most 3% on every instrument, error 2-3x that of "no change") did not change how the others are scored.
    core = backtest_indices(n, BACKTEST_START)
    early = np.linspace(MODELS["base"]["context"], BACKTEST_START - 1, 40).astype(int).tolist()
    wide = sorted(set((core or []) + early)) if core else backtest_indices(n, MODELS["base"]["context"])

    for mkey, m in MODELS.items():
        if n < 300:
            continue
        ctx_len = min(m["context"], n)
        predictor = KronosPredictor(Kronos.from_pretrained(m["model"]), KronosTokenizer.from_pretrained(m["tokenizer"]),
                                    device="cpu", max_context=m["context"])
        idx = wide
        bt, cal = {"days": 0}, None
        try:
            if idx:
                rows = backtest(predictor, full, m["context"], idx)
                bt, cal = full_stats(rows, n, full.index)
                rows_by_model[mkey] = rows
        except Exception as e:  # backtest is a bonus; never block the forecast
            print(f"{mkey} backtest failed:", repr(e))
        paths, used = forecast(predictor, full, ctx_len, future)
        models[mkey] = {"label": m["label"], "context": used, "forecast": build_forecast(paths, future, last_close, cal)}
        backtests[mkey] = bt
        print(mkey, json.dumps(bt))

    # LightGBM: trained on the complete history (+ overnight/global context), scored on the same days as Kronos-base.
    exp_range, n_exo, half_widths, risk, range_info = None, 0, None, None, None
    events, ev_next = {}, {}
    try:
        events = us_events.fetch_all(os.path.join("store", "events", "us.json"))
    except Exception as e:
        print("events unavailable:", repr(e))
    try:
        exo = load_exo(inst.get("exo"), full.index)
        # US CPI / jobs / Fed decisions between a close and the next one (scheduled ahead, so no lookahead)
        ev = us_events.features(full.index, future[0], events, inst.get("event_timing", "after_close"))
        if len(ev.columns):
            ev_next = {c[3:]: bool(ev[c].iloc[-1]) for c in ev.columns if c != "ev_any"}
            if inst.get("event_inputs"):                 # only where the backtest showed a gain (experiment mode "events")
                exo = ev if exo is None else pd.concat([exo, ev], axis=1)
        n_exo = 0 if exo is None else exo.shape[1]
        res = run_gbm(full, future, last_close, wide, exo, inst.get("big_move_pct"))
        half_widths, risk = res["half_widths"], res["risk"]
        range_info = {"scale": res["range_scale"], "days": res["range_coverage_days"]}
        models["gbm"] = {"label": "LightGBM", "context": res["rows_used"], "ctx_text": f"all {res['rows_used']:,} days",
                         "forecast": res["forecast"]}
        backtests["gbm"] = res["backtest"]
        exp_range = res["exp_range"]
        if res["rows"] is not None:
            rows_by_model["gbm"] = res["rows"]
        print("gbm", json.dumps(res["backtest"]), f"features={res['n_features']} (exo {n_exo})")
        print("risk", json.dumps(risk), "range", json.dumps(range_info), "half-widths %",
              [round(h * 100, 3) for h in half_widths])
    except Exception as e:  # never block the Kronos forecasts
        print("gbm failed:", repr(e))

    # Best estimate: backtest-weighted blend (models that do not help get weight 0; the rest shrinks toward "no change").
    blend_info = None
    try:
        fit = fit_blend(rows_by_model, n, full.index) if len(rows_by_model) >= 2 else None
        if fit:
            models["blend"] = {"label": "Best estimate", "context": fit["days"], "ctx_text": "weighted blend",
                               "forecast": blend_forecast(models, fit, future, last_close, exp_range, half_widths)}
            backtests["blend"] = fit["stats"]
            blend_info = {"weights": fit["weights"], "naive_weight": fit["naive_weight"], "days": fit["days"]}
            print("blend", json.dumps(blend_info), json.dumps(fit["stats"]["all"]))
    except Exception as e:
        print("blend failed:", repr(e))

    # News tone: tested walk-forward against past sessions; shifts the best estimate only as much as it has helped.
    news_feature = None
    if inst.get("news"):
        try:
            news_feature = newsfeat.run(inst, full, future[0].date(), os.environ.get("NEWS_STORE", "store"))
            if "blend" in models and news_feature["adj_pct"]:
                platt = fit["platt"]["blend"]
                newsfeat.apply(models["blend"]["forecast"], news_feature["adj_pct"] / 100, last_close,
                               lambda ret, k: platt_prob(platt, ret / k ** 0.5))
        except Exception as e:  # never block the forecast
            print("news feature failed:", repr(e))

    calibrate_probabilities({k: v for k, v in models.items() if k != "blend"}, rows_by_model, last_close)

    candles = [{"time": d.strftime("%Y-%m-%d"), **{c: round(float(r[c]), 2) for c in COLS}}
               for d, (_, r) in zip(full.index, full.iterrows())]
    out = {
        "key": key, "symbol": inst["name"], "ticker": inst["ticker"], "unit": inst["unit"], "group": inst["group"],
        "starts_today": bool(future[0].date() == now_ex.date()),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_close": round(last_close, 2), "last_date": full.index[-1].strftime("%Y-%m-%d"),
        "history_start": full.index[0].strftime("%Y-%m-%d"), "samples": SAMPLES,
        "default_model": "blend" if "blend" in models else "base",
        "data_check": {"stale": stale, "expected": expected.isoformat(), "last_date": full.index[-1].strftime("%Y-%m-%d"),
                       "from_intraday": filled},
        "blend": blend_info, "expected_range_pct": None if exp_range is None else round(exp_range * 100, 3),
        "settings": {"kronos_t": TEMP, "n_exo": n_exo},
        "news_feature": news_feature, "risk": risk, "range_method": range_info,
        "us_events": {"before_next_close": ev_next, "in_model": bool(inst.get("event_inputs")),
                      "upcoming": us_events.upcoming(events, full.index[-1].date()) if events else []},
        "inr": ({**inst["inr"], **fx} if inst.get("inr") and (fx := usd_inr()) else None),
        "candles": candles, "models": models, "backtest": backtests, "today_live": today_live,
    }
    os.makedirs("docs/data", exist_ok=True)
    with open(f"docs/data/{key}.json", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(json.dumps({k: v["forecast"][0] for k, v in models.items()}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
