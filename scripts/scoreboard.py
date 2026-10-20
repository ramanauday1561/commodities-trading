"""Live scoreboard: remember every forecast the page publishes, fill in the real close once it is known, and score it.

Usage: python scripts/scoreboard.py <store_dir> <data_dir>
  store_dir  persistent per-instrument records (kept on the `scoreboard` branch): <key>.json
  data_dir   docs/data: reads <key>.json (fresh forecasts + candles) and writes scoreboard-<key>.json for the page
"""
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

from evalutil import summarize

KEEP_DAYS = 450
RECENT = 20


def update_records(records, d):
    """Merge the new first-day forecast of every model, then fill in actual closes that are now known."""
    made = d["updated"]
    by_key = {(r["m"], r["d"]): r for r in records}
    stale = (d.get("data_check") or {}).get("stale")
    for m, info in ({} if stale else d["models"]).items():     # a forecast built on out-of-date data is not a real forecast
        f0 = info["forecast"][0]
        by_key[(m, f0["time"])] = {"m": m, "d": f0["time"], "f": made, "l": d["last_close"], "p": f0["close"],
                                   "r": round(f0["close"] / d["last_close"] - 1, 6)}
    # Futures prices on Yahoo are first the last trade and later the official settlement, so recent closes can still
    # change: refresh both the actual close and the previous close from the newest data on every run. Past futures
    # prices are also rescaled at every contract roll (rolls.py), so a forecast is kept as the move it predicted ("r")
    # and its price is rebuilt from the refreshed previous close.
    for r in by_key.values():
        if "r" not in r and r.get("l"):
            r["r"] = round(r["p"] / r["l"] - 1, 6)
    candles = d["candles"]
    actual = {c["time"]: c["close"] for c in candles}
    prev = {b["time"]: a["close"] for a, b in zip(candles, candles[1:])}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    out = []
    for r in by_key.values():
        if r["d"] < cutoff:
            continue
        if r["d"] in actual:
            r["a"] = actual[r["d"]]
            r["l"] = prev.get(r["d"], r["l"])
            if "r" in r:
                r["p"] = round(r["l"] * (1 + r["r"]), 4)
        out.append(r)
    return sorted(out, key=lambda r: (r["d"], r["m"]))


def stats(recs):
    done = [r for r in recs if "a" in r]
    if not done:
        return {"days": 0}
    rows = np.array([[0, r["l"], r["a"], r["p"]] for r in done], float)
    s = summarize(rows)
    s["bias_pct"] = round(float(((rows[:, 3] - rows[:, 2]) / rows[:, 2]).mean() * 100), 3)
    return s


def board(records):
    models = sorted({r["m"] for r in records})
    out = {"models": {}}
    for m in models:
        mine = [r for r in records if r["m"] == m and "a" in r]
        out["models"][m] = {"all": stats(mine), "recent": stats(mine[-RECENT:])}
    dates = sorted({r["d"] for r in records if "a" in r})[-12:]
    out["rows"] = []
    for dt in reversed(dates):
        rs = [r for r in records if r["d"] == dt]
        first = rs[0]
        out["rows"].append({"d": dt, "l": first["l"], "a": first.get("a"), "p": {r["m"]: r["p"] for r in rs}})
    return out


def main(store_dir, data_dir):
    os.makedirs(store_dir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        name = os.path.basename(path)[:-5]
        if name == "index" or name.startswith(("scoreboard-", "intraday-", "news-", "today-")):
            continue
        d = json.load(open(path))
        if "models" not in d:
            continue
        spath = os.path.join(store_dir, f"{name}.json")
        records = json.load(open(spath)) if os.path.exists(spath) else []
        records = update_records(records, d)
        json.dump(records, open(spath, "w"), separators=(",", ":"))
        b = board(records)
        b["updated"] = d["updated"]
        json.dump(b, open(os.path.join(data_dir, f"scoreboard-{name}.json"), "w"), separators=(",", ":"))
        resolved = sum("a" in r for r in records)
        print(f"{name}: {len(records)} records, {resolved} scored")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
