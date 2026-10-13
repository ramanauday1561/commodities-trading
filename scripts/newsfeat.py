"""News tone as a forecast input, tested before it is trusted.

For each trading session D the feature is the tone of the related headlines published in the 36 hours before the
*previous* session's close (cutoff). Anything written after that cutoff could already describe session D (live blogs
get retitled with the day's result), so it is never used. Live forecasts and the history use the same rule.

History: one row per session in <store>/news-daily/<key>.json, filled by `backfill` (Google News date search) and
then kept up to date by every forecast run.

Use: a walk-forward test regresses each session's return on the tone known before it (standardised with past data
only). The tone's effect is scaled by how much it actually helped in that test (0 = no help = no effect), and the
result shifts the best estimate. It has no effect at all below MIN_EVAL tested sessions, or if it cut the
walk-forward squared error by less than MIN_GAIN.

CLI:
  python scripts/newsfeat.py backfill <key> <store_dir> [days] [budget_seconds]
  python scripts/newsfeat.py merge <data_dir> <store_dir>      (deploy job: save the rows the forecast jobs fetched)
"""
import glob
import json
import os
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import news  # noqa: E402
from calendars import is_session, previous_session  # noqa: E402

WINDOW_H = 36
MIN_TRAIN = 40            # sessions before the first walk-forward prediction
MIN_EVAL = 60             # walk-forward predictions needed before the tone may move the forecast
MIN_GAIN = 0.01           # ...and it must cut the walk-forward squared error by at least 1%
CATCH_UP = 10             # sessions a forecast run fills in if the history has gaps


def history_path(store_dir, key):
    return os.path.join(store_dir, "news-daily", f"{key}.json")


def load_rows(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return []


def merge_rows(old, new):
    by_d = {r["d"]: r for r in old}
    by_d.update({r["d"]: r for r in new})
    return [by_d[d] for d in sorted(by_d)]


def cutoff(session, inst):
    """UTC time after which news may describe `session`: the close of the trading day before it."""
    prev = previous_session(session, inst.get("calendar"))
    h, m = map(int, inst["close"].split(":"))
    return datetime.combine(prev, dtime(h, m), ZoneInfo(inst["tz"])).astimezone(timezone.utc)


def session_row(inst, session):
    """Tone of the headlines in the WINDOW_H hours before the cutoff. None if the source could not be reached."""
    end = cutoff(session, inst)
    start = end - timedelta(hours=WINDOW_H)
    window = ((start - timedelta(days=1)).date().isoformat(), (end + timedelta(days=1)).date().isoformat())
    arts = news.from_google(inst["news"]["query"], window)
    if arts is None:
        return None
    lo, hi = start.strftime("%Y%m%dT%H%M%SZ"), end.strftime("%Y%m%dT%H%M%SZ")
    inside = [a for a in arts if a.get("seendate") and lo <= a["seendate"] <= hi]
    _, feat = news.summarize(inside)
    return {"d": session.isoformat(), "tone": feat["tone"], "stories": feat["stories"], "n": feat["articles"]}


def fill(inst, rows, sessions, now=None):
    """Fetch the sessions that are missing and whose cutoff has passed. Returns the new rows."""
    now = now or datetime.now(timezone.utc)
    have = {r["d"] for r in rows}
    new = []
    for s in sessions:
        if s.isoformat() in have or cutoff(s, inst) > now:
            continue
        r = session_row(inst, s)
        if r is None:          # source down or out of time budget: try again next run
            break
        new.append(r)
    return new


def evaluate(rows, closes):
    """Walk-forward test of tone -> next-session return. `closes` maps 'YYYY-MM-DD' -> close, in date order.
    Returns stats plus what is needed to turn today's tone into an adjustment."""
    dates = list(closes)
    ret = {d: closes[d] / closes[p] - 1 for p, d in zip(dates, dates[1:])}
    pairs = [(r["tone"], ret[r["d"]]) for r in sorted(rows, key=lambda r: r["d"]) if r.get("n") and r["d"] in ret]
    out = {"sessions": len(pairs), "tested": 0, "shrink": 0.0, "slope": 0.0, "mean": 0.0, "sd": 0.0}
    if len(pairs) < MIN_TRAIN + 5:
        return out
    x, y = np.array(pairs).T
    preds, targets, hits = [], [], []
    for i in range(MIN_TRAIN, len(x)):
        mx, sx, my = x[:i].mean(), x[:i].std(), y[:i].mean()
        if sx < 1e-9:
            continue
        z = (x[:i] - mx) / sx
        b = float((z * (y[:i] - my)).sum() / (z * z).sum())
        p, t = b * (x[i] - mx) / sx, y[i] - my
        preds.append(p)
        targets.append(t)
        if p != 0:
            hits.append(np.sign(p) == np.sign(y[i]))
    p, t = np.array(preds), np.array(targets)
    shrink = float(np.clip((t * p).sum() / max((p * p).sum(), 1e-18), 0.0, 1.0)) if len(p) else 0.0
    sx = x.std()
    out.update({"tested": len(p), "shrink": round(shrink, 3),
                "mean": float(x.mean()), "sd": float(sx),
                "slope": float(((x - x.mean()) / sx * (y - y.mean())).sum() / (((x - x.mean()) / sx) ** 2).sum()) if sx > 1e-9 else 0.0,
                "corr": round(float(np.corrcoef(x, y)[0, 1]), 3) if sx > 1e-9 else 0.0,
                "direction_accuracy": round(float(np.mean(hits)), 3) if hits else None,
                "up_rate": round(float(np.mean(y[MIN_TRAIN:] > 0)), 3),
                "mse_ratio": round(float(((t - shrink * p) ** 2).mean() / max((t ** 2).mean(), 1e-18)), 4) if len(p) else 1.0})
    return out


def adjustment(stats, tone_today):
    """Return to add to the best estimate's 1-day return (0 until the tone has proven itself)."""
    if tone_today is None or stats["tested"] < MIN_EVAL or stats["sd"] < 1e-9 or stats.get("mse_ratio", 1.0) > 1 - MIN_GAIN:
        return 0.0
    return stats["shrink"] * stats["slope"] * (tone_today - stats["mean"]) / stats["sd"]


def run(inst, full, target, store_dir):
    """Forecast-time entry point. `full` = completed daily candles, `target` = first forecast session (date)."""
    news.reset_budget(90)
    rows = load_rows(history_path(store_dir, inst["key"]))
    recent = [d.date() for d in full.index[-CATCH_UP:]] + [target]
    new = fill(inst, rows, recent)
    rows = merge_rows(rows, new)
    closes = {d.strftime("%Y-%m-%d"): float(c) for d, c in full["close"].items()}
    stats = evaluate(rows, closes)
    today = next((r for r in rows if r["d"] == target.isoformat()), None)
    adj = adjustment(stats, today["tone"] if today and today.get("n") else None)
    status = ("active" if adj != 0 else "no effect") if stats["tested"] >= MIN_EVAL else "collecting"
    print(f"news feature: {json.dumps(stats)} today={today} adj={adj:+.5f} ({status})", flush=True)
    return {"rows_new": new, "today": today, "stats": stats, "adj_pct": round(adj * 100, 3), "status": status,
            "cutoff": cutoff(target, inst).isoformat(timespec="minutes"), "min_eval": MIN_EVAL}


def apply(forecast, adj, last_close, prob_fn):
    """Shift a forecast path by `adj` (a 1-day return carried to every later day) and recompute P(up)."""
    if not adj:
        return forecast
    for k, r in enumerate(forecast, start=1):
        base_ret = r["close"] / last_close - 1
        for f in ("open", "high", "low", "close", "close_p10", "close_p90", "cal_p10", "cal_p90"):
            if f in r and not (k == 1 and f == "open"):
                r[f] = round(r[f] * (1 + adj), 2)
        r["prob_up"] = round(prob_fn(base_ret + adj, k), 3)
    return forecast


def backfill(key, store_dir, days=365, budget=1500):
    inst = next(i for i in json.load(open("scripts/instruments.json")) if i["key"] == key)
    news.reset_budget(budget)
    path = history_path(store_dir, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = load_rows(path)
    today = datetime.now(timezone.utc).date()
    sessions = [today - timedelta(days=i) for i in range(days, -1, -1)]
    sessions = [s for s in sessions if is_session(s, inst.get("calendar"))]
    have = {r["d"] for r in rows}
    todo = [s for s in sessions if s.isoformat() not in have]
    print(f"{key}: {len(have)} sessions stored, {len(todo)} to fetch", flush=True)
    done = 0
    for s in todo:
        r = session_row(inst, s) if cutoff(s, inst) <= datetime.now(timezone.utc) else None
        if r is None:
            if cutoff(s, inst) <= datetime.now(timezone.utc):
                print(f"{key}: stopped at {s} (source unavailable or time budget used)", flush=True)
                break
            continue
        rows = merge_rows(rows, [r])
        done += 1
        if done % 20 == 0:
            json.dump(rows, open(path, "w"), separators=(",", ":"))
            print(f"{key}: {done}/{len(todo)} fetched", flush=True)
    json.dump(rows, open(path, "w"), separators=(",", ":"))
    print(f"{key}: {len(rows)} sessions stored ({done} new)", flush=True)


def merge(data_dir, store_dir):
    for path in glob.glob(os.path.join(data_dir, "*.json")):
        name = os.path.basename(path)[:-5]
        if name == "index" or "-" in name:
            continue
        nf = (json.load(open(path)).get("news_feature") or {})
        if nf.get("rows_new"):
            hp = history_path(store_dir, name)
            os.makedirs(os.path.dirname(hp), exist_ok=True)
            rows = merge_rows(load_rows(hp), nf["rows_new"])
            json.dump(rows, open(hp, "w"), separators=(",", ":"))
            print(f"{name}: +{len(nf['rows_new'])} news sessions ({len(rows)} stored)")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "backfill":
        backfill(sys.argv[2], sys.argv[3], *(int(a) for a in sys.argv[4:6]))
    elif cmd == "merge":
        merge(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
