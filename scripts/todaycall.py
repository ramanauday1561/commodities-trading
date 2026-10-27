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
  past walk-forward calls); every other day is "no trade", and so is any day after heavyweight results
  (results_calendar.py) and, from 28 Oct 2026, any session after a US CPI / jobs report or Fed decision (us_since). Backtest with the fresh/stale split below (preopen_study.py, ~680 days): 83 trades, 52% won,
  +0.11% per trade after costs (t 1.0); leaving out the 8 trades after heavyweight results (-0.19% each): 74 trades,
  +0.15% each. Positive in both halves but not statistically proven, so it is scored from the open in the live record.
  Buying the open every day lost ~0.07%/day.
Fresh vs stale (studied after 19 Oct 2026, when NIFTY lost 1.1% on bank results while the overnight inputs pointed
  nowhere): the close call and the from-open signal split the US index futures move at the US cash close (16:00 New
  York) into the part during the US session, which the ADRs also saw, and the part after it, which they did not.
  Walk-forward (preopen_study.py, ~680 days): close call 61.6% -> 63.5% right (top 20%: 76.3% -> 78.4%), from-open
  top-20% trades +0.07% -> +0.11% per trade. Small gains; the gap call keeps its inputs (no gain there). India VIX,
  Bank Nifty, crude in the close call and ADRs split by weekend were tested too and did not help.
Tested on the from-open signal and not used (walk-forward, ~738 sessions, rule fixed before each run: more per trade
  than the live signal in both halves and in total, and skipped trades must lose):
  23 Oct 2026 (oct23_study): ADRs on their own results days, a 06:33 cutoff, Brent's 5-day move.
  25 Oct 2026 (results_size_study): the 5, 20 or 50 heaviest stocks for results days instead of 11.
  26 Oct 2026 (vix_study): India VIX as an input, or standing aside when it is high, up or down 5%. The signal's profit
    comes mostly from high-VIX sessions (47 of 77 trades, +0.26% each), so "stand aside when VIX is high" lost it all;
    "trade only when VIX is high" was seen after the fact and needs new data before it can be tested fairly.
  26 Oct 2026 (pcr_study): NIFTY's put-call ratio from NSE's F&O bhavcopy (previous close) as an input, or standing
    aside when it is high, low or jumped 15%, or trading only when its change agrees with the side. All earned less in
    total; the skipped trades made money.
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

import results_calendar as rc
import us_events
from calendars import is_session

NIFTY = "^NSEI"
IST = ZoneInfo("Asia/Kolkata")
OVERNIGHT = {"es": "ES=F", "nq": "NQ=F", "nikkei": "^N225", "kospi": "^KS11", "hangseng": "^HSI"}
FEATS = list(OVERNIGHT) + ["prev_day"]
INDIA = {"hdb": "HDB", "ibn": "IBN", "infy": "INFY", "crude": "CL=F", "usdinr": "INR=X"}
GAP_FEATS = FEATS + list(INDIA)                  # the close call keeps FEATS: the extra inputs did not help it
SPLIT = ("es", "nq")                             # US index futures, split at the US cash close
FRESH_FEATS = ["es_day", "es_night", "nq_day", "nq_night", "nikkei", "kospi", "hangseng", "prev_day"] + list(INDIA)
# The from-open signal leaves crude out: Yahoo's hourly CL=F jumps at every contract roll (18 Sep, 15 Oct 2026) and its
# weight is close to zero. Over 658 days (roll_study.py, 20 Oct 2026) its top-20% trades did better without it: 97 trades,
# 54.6% won, +0.110% each after costs (+0.105% / +0.115% in the two halves) vs 81 trades, 48.1%, +0.075% (+0.132% / +0.020%).
# The gap call (76.4% vs 75.4% right) and the close call (mixed halves) keep it.
# 26 Oct 2026 (streak_study, 738 sessions, same run): adding NIFTY's 3-day move to the previous close ("ret3") took the
# from-open trades from 80 at +0.112% each (+8.9% total; +0.201% / +0.023% in the two halves) to 79 at +0.131%
# (+10.3%; +0.212% / +0.052%). A small gain that passed the rule fixed before the run; the 5-day move and the run of
# down closes did similarly or worse. On its own, NIFTY did not bounce after 3+ down closes (open to close -0.03%, as on
# other days), so ret3 helps alongside the overnight inputs, not as a "buy after a fall" rule.
OPEN_FEATS = [k for k in FRESH_FEATS if k != "crude"] + ["ret3"]
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
STOP_PCT = 0.5                  # the stop against the trade from the open (same as status.STOP_PCT)


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
        f["ret3"] = nd["close"].iloc[i - 1] / nd["close"].iloc[i - 4] - 1 if i >= 4 else 0.0
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


def call_block(X, y, x_today, open_to_close=None, exclude=None):
    """Today's call for one target plus the walk-forward accuracy of each confidence tier (and, for the close call,
    what following it from the open earned). `exclude` drops days (e.g. after heavyweight results) from the tier
    statistics only."""
    wf = walk_forward(X, y)
    ok = ~np.isnan(wf) & (~np.asarray(exclude, bool) if exclude is not None else True)
    p, t = wf[ok], y[ok]
    pnl = np.sign(p) * np.asarray(open_to_close)[ok] if open_to_close is not None else None
    table = share_table(np.abs(p), (np.sign(p) == np.sign(t)).astype(float), (t > 0).astype(float),
                        levels=(1.0, 0.5, 0.2, 0.1), min_hist=20, pnl=pnl)
    tiers = {"very_strong": table["top_10pct"], "strong": table["top_20pct"], "lean": table["top_50pct"],
             "all_days": table["top_100pct"]}
    pred = ridge_predict(ridge_fit(X, y), x_today)
    return {"direction": "up" if pred > 0 else "down", "pred_pct": round(pred * 100, 3),
            "tier": tier_of(abs(pred), np.abs(p)), "tiers": tiers, "test_days": int(ok.sum())}


def from_open_block(X, o2c, x_today, results_hist=None, results_today=False, us_today=None):
    """The from-open signal: trained on open -> close, so its tier stats are what a trade from the open earned. It
    stands aside after heavyweight results (results_calendar), and its stats leave those sessions out too; and on the
    session after a US CPI / jobs report or Fed decision (us_today: those events, see us_since)."""
    c = call_block(X, o2c, x_today, o2c, exclude=results_hist)
    strong = c["tier"] in TRADE_TIERS
    c["trade"] = strong and not results_today and not us_today
    c["skipped_for_results"] = bool(results_today and strong)
    c["skipped_for_us_events"] = bool(us_today and strong and not results_today)
    if us_today:
        c["us_events"] = list(us_today)
    c["trade_stats"] = c["tiers"]["strong"]              # top 20% (cumulative): the days it trades
    return c


US_EVENT_NAMES = {"fomc": "Fed decision", "cpi": "US inflation (CPI)", "jobs": "US jobs report"}


def us_calendar(store_dir, today):
    """US CPI / jobs / Fed dates, refreshed once a day (federalreserve.gov's current calendar and FRED; the FRED_API_KEY
    secret is needed for CPI and jobs) and kept in store/events/us-recent.json; any source that fails keeps its last
    copy."""
    path = os.path.join(store_dir, "events", "us-recent.json")
    old = json.load(open(path)) if os.path.exists(path) else {}
    if old.get("fetched") == today.isoformat():
        return {k: [datetime.strptime(d, "%Y-%m-%d").date() for d in v] for k, v in old.items() if k in us_events.KINDS}
    ev = {}
    try:
        cur = us_events.parse_fomc_current(us_events._get(us_events.FOMC_CURRENT))
        ev["fomc"] = sorted(d for ds in cur.values() for d in ds)
    except Exception as e:
        print(f"us events: Fed calendar unavailable ({e!r})", flush=True)
    key = os.environ.get("FRED_API_KEY")
    for kind in ("cpi", "jobs"):
        try:
            if key:
                ev[kind] = [d for d in us_events.fetch_fred(kind, key) if d.year >= today.year - 1]
        except Exception as e:
            print(f"us events: FRED {kind} unavailable ({e!r})", flush=True)
    for kind in us_events.KINDS:
        if not ev.get(kind) and old.get(kind):
            ev[kind] = [datetime.strptime(d, "%Y-%m-%d").date() for d in old[kind]]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"fetched": today.isoformat() if ev.get("fomc") else old.get("fetched"),
               **{k: [d.isoformat() for d in v] for k, v in ev.items()}}, open(path, "w"))
    return ev


def us_since(ev, prev_day, today):
    """US events that hit today's session: released on a US date from the last session to yesterday. They come out
    after India's close (CPI / jobs 18:00-19:00 IST, the Fed about 23:30 IST), so NIFTY trades them the next session.
    28 Oct 2026 (history_study, 59 trades): the from-open trades on those sessions lost -2.18% in total (10 trades);
    the 49 others made +0.259% each against +0.178% for all. A small sample; adopted on the user's decision."""
    return [f"{US_EVENT_NAMES[k]} {d:%d %b}" for k in us_events.KINDS for d in ev.get(k, []) if prev_day <= d < today]


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


def band_accuracy(row, b):
    """How often moves of this size (from bucket b up to the next bucket) held, rather than moves at least this big.
    21 Oct 2026: at 10:30 NIFTY was +0.16% and the page said "moves like this held 76%", the rate for all moves,
    which is lifted by the large ones; it closed -0.34%."""
    above = [x for x in BUCKETS if x > b and x in row]
    if not above:
        return row[b]["accuracy"]
    nb = above[0]
    n_b, n_nb = row[b]["share"], row[nb]["share"]
    if n_b - n_nb <= 0:
        return row[b]["accuracy"]
    return round((row[b]["accuracy"] * n_b - row[nb]["accuracy"] * n_nb) / (n_b - n_nb), 3)


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
            if {"high", "low"} <= set(nd.columns):     # the History page: what the trade made with the stop
                hi, lo = nd["high"].iloc[i], nd["low"].iloc[i]
                stopped = bool(lo <= o * (1 - STOP_PCT / 100)) if side > 0 else bool(hi >= o * (1 + STOP_PCT / 100))
                r["result"]["stopped"] = stopped
                r["result"]["with_stop_pct"] = round(-STOP_PCT - TRADE_COST_PCT, 3) if stopped else r["result"]["from_open_pct"]
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
                      "from_open_trade": bool((r.get("from_open") or {}).get("trade")),
                      "from_open_dir": (r.get("from_open") or {}).get("direction"), **r["result"]}
                     for r in record if "result" in r][-60:][::-1]                          # the History page
    return out


# ---------------------------------------------------------------- main
def daily():
    raw = yf.download(NIFTY, period="5y", interval="1d", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "Close"])
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    return raw.rename(columns=str.lower)[["open", "high", "low", "close"]]


def run(store_dir="store", out_dir="docs/data", now=None):
    now = now or datetime.now(IST)
    today = now.date()
    nd_all = daily()
    rec_path = os.path.join(store_dir, "calls", "nifty.json")
    record = resolve(load_record(rec_path), nd_all, today, now)
    out = {"key": "nifty", "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "date": today.isoformat()}
    nxt = today + timedelta(days=1)
    while not is_session(nxt, "XBOM"):
        nxt += timedelta(days=1)
    out["next_session"] = nxt.isoformat()               # the Status page knows a holiday is not a missing call
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
        f["ret3"] = nd["close"].iloc[-1] / nd["close"].iloc[-4] - 1                 # NIFTY's 3-day move (OPEN_FEATS)
        x_gap, x_fresh = np.array([f[k] for k in GAP_FEATS]), np.array([f[k] for k in FRESH_FEATS])
        x_open = np.array([f[k] for k in OPEN_FEATS])
        cal = rc.fetch(os.path.join(store_dir, "results", "nifty.json"))
        res_hist = rc.flags(nd.index, cal).reindex(df.index).fillna(False).values.astype(bool) if cal else None
        res_now = rc.since(cal, prev_day, today) if cal else []
        try:
            ev = us_calendar(store_dir, today)
        except Exception as e:                              # no calendar: trade as before rather than not at all
            print(f"us events: {e!r}", flush=True)
            ev = {}
        us_now = us_since(ev, prev_day, today)
        pre = {"cutoff_ist": cutoff.tz_convert(IST).strftime("%H:%M"), "prev_close": round(float(nd["close"].iloc[-1]), 2),
               "moves_pct": {k: round(v * 100, 2) for k, v in f.items()},
               "gap": call_block(df[GAP_FEATS].values, gap, x_gap), "close": call_block(df[FRESH_FEATS].values, day, x_fresh, (1 + day) / (1 + gap) - 1),
               "from_open": from_open_block(df[OPEN_FEATS].values, o2c, x_open, res_hist, bool(res_now), us_now),
               "since": str(df.index[0].date())}
        if cal and res_hist is not None and res_hist.any():
            big = np.abs(day) > 0.01                        # how often NIFTY moved more than 1% after results vs not
            pre["results"] = {"since": res_now, "upcoming": rc.upcoming(cal, today),
                              "big_day_pct": {"results": round(float(big[res_hist].mean()) * 100),
                                              "other": round(float(big[~res_hist].mean()) * 100),
                                              "results_days": int(res_hist.sum())}}
        pre["us_events"] = {"since": us_now, "upcoming": [{"date": u["date"], "name": US_EVENT_NAMES[u["kind"]]}
                                                          for u in us_events.upcoming(ev, today - timedelta(days=1), 3)]}
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
                        "open": round(float(todays["Open"].iloc[0]), 2),
                        "high": round(float(todays["High"].max()), 2), "low": round(float(todays["Low"].min()), 2)}
                if hm and out["status"] == "open":
                    row = table[hm[-1]]
                    b = max(x for x in BUCKETS if x in row and abs(move) > x) if any(
                        x in row and abs(move) > x for x in BUCKETS) else None
                    if b is not None:
                        intr.update({"checkpoint": utc_at(today, hm[-1]).tz_convert(IST).strftime("%H:%M"),
                                     "accuracy": band_accuracy(row, b), "at_least_accuracy": row[b]["accuracy"],
                                     "share": row[b]["share"],
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
