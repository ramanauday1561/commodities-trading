"""NIFTY "Today's call": direction calls that use information arriving overnight and during the session.

Pre-open (from US index futures, Nikkei, KOSPI and Hang Seng between NIFTY's previous close and 09:10 IST; the gap
call also uses the New York-listed Indian ADRs HDB/IBN/INFY, crude oil and USD/INR, which lifted its walk-forward
accuracy from 71% to 76% of all days, see accuracy_study.extreme_days):
  * the opening gap: will NIFTY open above or below yesterday's close?
  * today's close: will it close above or below yesterday's close?
  A ridge regression refitted on the past ~2.5 years makes each call; its confidence is ranked against its own past
  walk-forward calls, and the page shows only the accuracy of that confidence tier in the walk-forward test.
From-open signal: for trading from the 09:15 open. A ridge on the overnight inputs trained on the move from the open to
  the close (not vs yesterday's close), and a trade only on its top-20% most confident days (ranked against its own
  past walk-forward calls); every other day is "no trade". Backtest with the fresh/stale split below (preopen_study.py,
  ~680 days): 82 trades, 52% won, +0.12% per trade after costs, positive in both halves but not statistically proven
  (t 1.1), so it is recorded and scored from the open in the live record. Buying the open every day lost ~0.07%/day.
Fresh vs stale (after 19 Oct 2026, when Friday's ADR rise cancelled the weekend's fall in US futures and NIFTY lost
  1.1%): the close call and the from-open signal split the US index futures move at the US cash close (16:00 New
  York) into the part during the US session, which the ADRs also saw, and the part after it, which they did not.
  Walk-forward (preopen_study.py, ~680 days): close call 61.7% -> 63.5% right (top 20%: 76.5% -> 77.5%), from-open
  top-20% trades +0.08% -> +0.12% per trade. Small gains; the gap call keeps its inputs (no gain there).
During the session (from 10:15 IST): today's close direction from the move so far, with the historical accuracy of
  "the sign of the move at this time of day, for moves at least this big".

Each day's pre-open call is recorded only if it is made before the 09:15 open (a later pre-open run replaces an
earlier one), and scored once the day has closed,
so the live record cannot be flattered by late calls. Study behind it: scripts/accuracy_study.py.

Usage: python scripts/todaycall.py [store_dir] [out_dir]
"""
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from calendars import is_session

NIFTY = "^NSEI"
IST = ZoneInfo("Asia/Kolkata")
OVERNIGHT = {"es": "ES=F", "nq": "NQ=F", "nikkei": "^N225", "kospi": "^KS11", "hangseng": "^HSI"}
FEATS = list(OVERNIGHT) + ["prev_day"]
INDIA = {"hdb": "HDB", "ibn": "IBN", "infy": "INFY", "crude": "CL=F", "usdinr": "INR=X"}
GAP_FEATS = FEATS + list(INDIA)                  # the close call keeps FEATS: the extra inputs did not help it
SPLIT = ("es", "nq")                             # US index futures, split at the US cash close
FRESH_FEATS = ["es_day", "es_night", "nq_day", "nq_night", "nikkei", "kospi", "hangseng", "prev_day"] + list(INDIA)
NY = ZoneInfo("America/New_York")
CUTOFF = (3, 40)                 # 09:10 IST in UTC: the latest information a pre-open call may use
PREV_CLOSE = (10, 0)             # 15:30 IST in UTC
OPEN_IST = (9, 15)
CHECKPOINTS = [(4, 45), (5, 45), (6, 45), (7, 45), (8, 45)]       # 10:15 ... 14:15 IST (UTC bar ends)
BUCKETS = (0.0, 0.0025, 0.005, 0.0075, 0.01)
TIERS = (("very_strong", 0.10), ("strong", 0.20), ("lean", 0.50))
TRADE_TIERS = ("very_strong", "strong")          # from-open signal: trade only on the top-20% most confident days
RIDGE = 5.0
MIN_HIST = 60


# ---------------------------------------------------------------- data helpers (also used by accuracy_study.py)
def hourly(symbol, period="730d"):
    raw = yf.download(symbol, period=period, interval="1h", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Close"])
    idx = pd.to_datetime(raw.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return pd.Series(raw["Close"].values, index=idx + pd.Timedelta(hours=1)).sort_index()   # indexed by bar END


def value_at(series, t):
    """Last price known at time t (bar end <= t)."""
    s = series.loc[:t]
    return float(s.iloc[-1]) if len(s) else np.nan


def utc_at(day, hm):
    return pd.Timestamp(day).tz_localize("UTC") + pd.Timedelta(hours=hm[0], minutes=hm[1])


TRADE_COST_PCT = 0.03           # round trip for NIFTY futures (brokerage, STT, fees, slippage), approximate


def share_table(conf, correct, up, levels=(1.0, 0.5, 0.3, 0.2, 0.1), min_hist=60, pnl=None):
    """Accuracy when only the most confident calls are made. The cut-off for day i is the (1-c) quantile of the
    confidence of days before i, so it never looks ahead. With pnl (what following the call from the 09:15 open earned,
    as a fraction), each level also reports how that trade did after costs: being right about the close vs
    yesterday is mostly the opening gap, which cannot be traded (strong calls: 77% right, but 49% from the open)."""
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
        if pnl is not None and n:
            net = np.asarray(pnl)[take] * 100 - TRADE_COST_PCT
            out[f"top_{int(c * 100)}pct"]["from_open"] = {"win_rate": round(float((net > 0).mean()), 3),
                                                          "avg_pct_after_costs": round(float(net.mean()), 3)}
    return out


def us_close(day):
    """16:00 New York on `day`, in UTC (the US cash close; 20:00 or 21:00 UTC)."""
    return pd.Timestamp(datetime.combine(day, time(16, 0), NY)).tz_convert("UTC")


def overnight_features(series, prev_day, day, cutoff, prev_ret):
    t_prev, f = utc_at(prev_day, PREV_CLOSE), {}
    for k, s in series.items():
        a, b = value_at(s, t_prev), value_at(s, cutoff)
        f[k] = b / a - 1 if a and np.isfinite(a) and np.isfinite(b) else 0.0
    t_us = min(us_close(prev_day), cutoff)
    for k in SPLIT:                     # NIFTY close -> US close (the ADRs saw it), US close -> cutoff (they did not)
        s = series.get(k)
        a, m, b = (value_at(s, t) for t in (t_prev, t_us, cutoff)) if s is not None else (np.nan,) * 3
        ok = all(np.isfinite(v) and v for v in (a, m, b))
        f[f"{k}_day"], f[f"{k}_night"] = (m / a - 1, b / m - 1) if ok else (0.0, 0.0)
    f["prev_day"] = prev_ret
    return f


def history(nd, series):
    """One row per past NIFTY session: overnight features, opening gap and close-to-close move."""
    start = min(s.index[0] for s in series.values() if len(s))
    rows, days = [], nd.index
    for i in range(2, len(days)):
        d, prev = days[i].date(), days[i - 1].date()
        if utc_at(prev, PREV_CLOSE) < start:
            continue
        f = overnight_features(series, prev, d, utc_at(d, CUTOFF), nd["close"].iloc[i - 1] / nd["close"].iloc[i - 2] - 1)
        rows.append({"d": days[i], **f, "gap": nd["open"].iloc[i] / nd["close"].iloc[i - 1] - 1,
                     "day": nd["close"].iloc[i] / nd["close"].iloc[i - 1] - 1})
    df = pd.DataFrame(rows).set_index("d").replace([np.inf, -np.inf], np.nan)
    cols = [c for c in df.columns if c not in ("gap", "day")]
    df[cols] = df[cols].fillna(0.0)
    return df[df["gap"].abs() > 1e-6]                   # days where Yahoo's open equals the previous close are unusable


def ridge_fit(X, y):
    mu, sd = X.mean(0), X.std(0) + 1e-12
    Z = (X - mu) / sd
    w = np.linalg.solve(Z.T @ Z + RIDGE * np.eye(X.shape[1]), Z.T @ (y - y.mean()))
    return mu, sd, w, y.mean()


def ridge_predict(m, x):
    mu, sd, w, ym = m
    return float(ym + ((x - mu) / sd) @ w)


def walk_forward(X, y):
    preds = np.full(len(y), np.nan)
    for i in range(MIN_HIST, len(y)):
        preds[i] = ridge_predict(ridge_fit(X[:i], y[:i]), X[i])
    return preds


def tier_of(conf, past_conf):
    for name, top in TIERS:
        if conf >= np.quantile(past_conf, 1 - top):
            return name
    return "none"


def call_block(X, y, x_today, open_to_close=None):
    """Today's call for one target plus the walk-forward accuracy of each confidence tier (and, for the close call,
    what following it from the open earned)."""
    wf = walk_forward(X, y)
    ok = ~np.isnan(wf)
    p, t = wf[ok], y[ok]
    pnl = np.sign(p) * np.asarray(open_to_close)[ok] if open_to_close is not None else None
    table = share_table(np.abs(p), (np.sign(p) == np.sign(t)).astype(float), (t > 0).astype(float),
                        levels=(1.0, 0.5, 0.2, 0.1), min_hist=20, pnl=pnl)
    tiers = {"very_strong": table["top_10pct"], "strong": table["top_20pct"], "lean": table["top_50pct"],
             "all_days": table["top_100pct"]}
    pred = ridge_predict(ridge_fit(X, y), x_today)
    return {"direction": "up" if pred > 0 else "down", "pred_pct": round(pred * 100, 3),
            "tier": tier_of(abs(pred), np.abs(p)), "tiers": tiers, "test_days": int(ok.sum())}


def from_open_block(X, o2c, x_today):
    """The from-open signal: trained on open -> close, so its tier stats are what a trade from the open earned."""
    c = call_block(X, o2c, x_today, o2c)
    c["trade"] = c["tier"] in TRADE_TIERS
    c["trade_stats"] = c["tiers"]["strong"]              # top 20% (cumulative): the days it trades
    return c


def intraday_table(nd, bars):
    """Accuracy of 'today closes on the side of yesterday's close where it trades now', by time and move size."""
    prev_close = nd["close"].shift(1)
    out = {}
    for hm in CHECKPOINTS:
        moves, final = [], []
        for d in nd.index:
            t = utc_at(d.date(), hm)
            day_bars = bars.loc[utc_at(d.date(), (0, 0)):t]
            if len(day_bars) == 0 or pd.isna(prev_close.loc[d]):
                continue
            moves.append(float(day_bars.iloc[-1]) / prev_close.loc[d] - 1)
            final.append(nd["close"].loc[d] / prev_close.loc[d] - 1)
        m, f = np.array(moves), np.array(final)
        out[hm] = {b: {"accuracy": round(float((np.sign(m[np.abs(m) > b]) == np.sign(f[np.abs(m) > b])).mean()), 3),
                       "share": round(float((np.abs(m) > b).mean()), 3)} for b in BUCKETS if (np.abs(m) > b).any()}
        out[hm]["days"] = len(m)
    return out


# ---------------------------------------------------------------- live record
def load_record(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return []


def resolve(record, nd, today, now):
    """Score recorded calls whose day has finished."""
    for r in record:
        if "result" in r:
            continue
        d = pd.Timestamp(r["d"])
        if d not in nd.index or (d.date() == today and (now.hour, now.minute) < (15, 45)):
            continue
        i = nd.index.get_loc(d)
        if i == 0:
            continue
        pc, o, c = nd["close"].iloc[i - 1], nd["open"].iloc[i], nd["close"].iloc[i]
        r["result"] = {"open": round(float(o), 2), "close": round(float(c), 2), "prev_close": round(float(pc), 2),
                       "gap_hit": bool((o > pc) == (r["gap"]["direction"] == "up")),
                       "close_hit": bool((c > pc) == (r["close"]["direction"] == "up"))}
        fo = r.get("from_open")
        if fo and fo.get("trade"):                      # scored the way it is traded: 09:15 open to close, after costs
            side = 1 if fo["direction"] == "up" else -1
            r["result"]["from_open_pct"] = round(side * (c / o - 1) * 100 - TRADE_COST_PCT, 3)
    return record


def summarize_record(record):
    out = {}
    for kind in ("gap", "close"):
        by = {}
        for r in record:
            if "result" not in r:
                continue
            t = r[kind]["tier"]
            by.setdefault(t, {"calls": 0, "hits": 0})
            by[t]["calls"] += 1
            by[t]["hits"] += int(r["result"][f"{kind}_hit"])
        out[kind] = by
    trades = [r["result"]["from_open_pct"] for r in record if "from_open_pct" in r.get("result", {})]
    out["from_open"] = {"trades": len(trades), "wins": sum(x > 0 for x in trades),
                        "total_pct": round(float(sum(trades)), 3), "days": sum("result" in r and "from_open" in r for r in record)}
    out["days"] = sum("result" in r for r in record)
    out["recent"] = [{"d": r["d"], "gap": r["gap"]["direction"], "gap_tier": r["gap"]["tier"],
                      "close_call": r["close"]["direction"], "close_tier": r["close"]["tier"],   # "close" is the price
                      "from_open_trade": bool((r.get("from_open") or {}).get("trade")), **r["result"]}
                     for r in record if "result" in r][-10:][::-1]
    return out


# ---------------------------------------------------------------- main
def daily():
    raw = yf.download(NIFTY, period="5y", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    return raw.rename(columns=str.lower)[["open", "close"]]


def run(store_dir="store", out_dir="docs/data", now=None):
    now = now or datetime.now(IST)
    today = now.date()
    nd_all = daily()
    rec_path = os.path.join(store_dir, "calls", "nifty.json")
    record = resolve(load_record(rec_path), nd_all, today, now)
    out = {"key": "nifty", "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "date": today.isoformat()}
    if not is_session(today, "XBOM"):
        out["status"] = "holiday"
    else:
        nd = nd_all[nd_all.index.date < today]                             # completed sessions only
        series = {k: hourly(t) for k, t in {**OVERNIGHT, **INDIA}.items()}
        df = history(nd, series)
        gap, day = df["gap"].values, df["day"].values
        o2c = (1 + day) / (1 + gap) - 1                                      # 09:15 open -> close
        cutoff = min(pd.Timestamp(now).tz_convert("UTC"), utc_at(today, CUTOFF))
        prev_day = nd.index[-1].date()
        f = overnight_features(series, prev_day, today, cutoff, nd["close"].iloc[-1] / nd["close"].iloc[-2] - 1)
        x_gap, x_fresh = np.array([f[k] for k in GAP_FEATS]), np.array([f[k] for k in FRESH_FEATS])
        pre = {"cutoff_ist": cutoff.tz_convert(IST).strftime("%H:%M"), "prev_close": round(float(nd["close"].iloc[-1]), 2),
               "moves_pct": {k: round(v * 100, 2) for k, v in f.items()},
               "gap": call_block(df[GAP_FEATS].values, gap, x_gap), "close": call_block(df[FRESH_FEATS].values, day, x_fresh, (1 + day) / (1 + gap) - 1),
               "from_open": from_open_block(df[FRESH_FEATS].values, o2c, x_fresh),
               "since": str(df.index[0].date())}
        out["preopen"] = pre
        made_before_open = (now.hour, now.minute) < OPEN_IST
        if made_before_open:                                # the latest call made before the open is the one scored
            record = [r for r in record if r["d"] != today.isoformat()]
            record.append({"d": today.isoformat(), "made_at": now.strftime("%H:%M"), "cutoff": pre["cutoff_ist"],
                           "gap": {k: pre["gap"][k] for k in ("direction", "tier", "pred_pct")},
                           "close": {k: pre["close"][k] for k in ("direction", "tier", "pred_pct")},
                           "from_open": {k: pre["from_open"][k] for k in ("direction", "tier", "pred_pct", "trade")}})
        out["status"] = "pre_open" if made_before_open else ("open" if (now.hour, now.minute) < (15, 30) else "closed")
        rec_today = next((r for r in record if r["d"] == today.isoformat()), None)
        if rec_today:                                       # the call that is scored: the last one made before 09:15
            pre["recorded"] = {"made_at": rec_today["made_at"], "final": not made_before_open,
                               "gap": rec_today["gap"], "close": rec_today["close"],
                               "from_open": rec_today.get("from_open")}
        # during the session: the move so far
        if out["status"] in ("open", "closed"):
            bars = hourly(NIFTY)
            live = yf.download(NIFTY, period="5d", interval="15m", auto_adjust=False, progress=False)
            live.columns = [c[0] if isinstance(c, tuple) else c for c in live.columns]
            live = live.dropna(subset=["Close"])
            li = pd.to_datetime(live.index)
            li = li.tz_localize("UTC") if li.tz is None else li.tz_convert("UTC")
            live.index = li
            todays = live[live.index.tz_convert(IST).date == today]
            if len(todays):
                price = float(todays["Close"].iloc[-1])
                move = price / pre["prev_close"] - 1
                asof = (todays.index[-1] + pd.Timedelta(minutes=15)).tz_convert(IST)
                table = intraday_table(nd, bars)
                hm = [c for c in CHECKPOINTS if utc_at(today, c) <= asof.tz_convert("UTC")]
                intr = {"asof": min(asof, pd.Timestamp(datetime.combine(today, datetime.min.time()), tz=IST)
                                    + timedelta(hours=15, minutes=30)).strftime("%H:%M"),
                        "price": round(price, 2), "move_pct": round(move * 100, 3),
                        "direction": "up" if move > 0 else "down",
                        "open": round(float(todays["Open"].iloc[0]), 2)}
                if hm and out["status"] == "open":
                    row = table[hm[-1]]
                    b = max(x for x in BUCKETS if x in row and abs(move) > x) if any(
                        x in row and abs(move) > x for x in BUCKETS) else None
                    if b is not None:
                        intr.update({"checkpoint": utc_at(today, hm[-1]).tz_convert(IST).strftime("%H:%M"),
                                     "accuracy": row[b]["accuracy"], "share": row[b]["share"],
                                     "bucket_pct": round(b * 100, 2), "all_moves_accuracy": row[0.0]["accuracy"],
                                     "test_days": row["days"]})
                out["intraday"] = intr
    out["record"] = summarize_record(record)
    os.makedirs(os.path.dirname(rec_path), exist_ok=True)
    json.dump(record, open(rec_path, "w"), separators=(",", ":"))
    os.makedirs(out_dir, exist_ok=True)
    json.dump(out, open(os.path.join(out_dir, "today-nifty.json"), "w"), separators=(",", ":"))
    print(json.dumps({k: out.get(k) for k in ("status", "date")}),
          json.dumps({k: (v.get("direction"), v.get("tier")) for k, v in (out.get("preopen") or {}).items()
                      if isinstance(v, dict) and "tier" in v}), json.dumps(out.get("intraday")), flush=True)
    return out


if __name__ == "__main__":
    run(*sys.argv[1:3])
