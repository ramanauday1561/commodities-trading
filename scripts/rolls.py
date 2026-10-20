"""Futures contract rolls in Yahoo's continuous series (CL=F, GC=F, SI=F).

Yahoo's continuous futures price jumps from one contract to the next without adjusting the earlier prices. On 20 Oct
2026 WTI moved from the November to the December contract, which traded 4.9% lower (steep backwardation), so the daily
history showed a 7% fall on a day crude fell about 2%, and the forecast started from the expired November price. All
models read the history as one price, so each roll is measured and the prices before it are rescaled to the contract
that trades now (a back-adjusted continuous series): every daily return is then real, the roll day included.

How a roll is found (experiment mode "rollprobe", 20 Oct 2026): Yahoo deletes a contract once it expires, but the
contract the continuous series follows now still has its own daily history. Walking back from the newest candle, the
first day on which that contract's close differs from the continuous close (two days in a row) is the last day on the
old contract, and the ratio of the two closes that day is the roll (WTI 20 Oct: -4.94%; the opening gap said -5.23%).
Only the latest roll can be measured this way, so every roll found is stored (store/rolls/<key>.json on the scoreboard
branch, saved by the deploy job) and stays applied after the contract that measured it expires. Rolls before 20 Oct
2026 cannot be measured any more and stay as Yahoo has them (typically 0.2-1%, the latest ones much larger).
"""
import glob
import json
import os
import sys
from datetime import date

import pandas as pd

CODES = "FGHJKMNQUVXZ"
ROOTS = {"CL=F": ("CL", "NYM"), "GC=F": ("GC", "CMX"), "SI=F": ("SI", "CMX")}
PRICES = ["open", "high", "low", "close"]
TOL = 0.0015            # closes within 0.15% are the same contract (both series are fetched minutes apart)
LOOKBACK = 130          # trading days searched for the last roll (gold stays on one contract for ~4 months)
MAX_ROLL = 0.15         # a "roll" larger than 15% is a data error, not a roll
MIN_APART = 10          # a roll found within 10 trading days of a stored one is that same roll


def candidates(root, ex, today, months=6):
    """Dated tickers for this month and the next `months - 1` (e.g. CLZ26.NYM); ones Yahoo does not list just fail."""
    out = []
    for k in range(months):
        m = (today.month - 1 + k) % 12
        y = today.year + (today.month - 1 + k) // 12
        out.append(f"{root}{CODES[m]}{y % 100:02d}.{ex}")
    return out


def detect(cont, dated, tol=TOL, lookback=LOOKBACK):
    """The latest roll in `cont` (continuous closes, oldest first) using `dated` ({ticker: closes}).

    Returns {"date": first day on the current contract, "ratio": current / old contract on the day before,
    "contract": ticker} or None (no roll within `lookback` days, or no dated contract matches any of the last 3 closes)."""
    t, anchor = None, None
    for a in range(len(cont) - 1, max(len(cont) - 4, -1), -1):     # the newest of the last 3 closes a contract matches
        day = cont.index[a]                                         # (a live close may move between the two downloads)
        devs = {k: abs(s.loc[day] / cont.iloc[a] - 1) for k, s in dated.items() if day in s.index and s.loc[day] > 0}
        if devs and min(devs.values()) <= tol:
            t, anchor = min(devs, key=devs.get), a
            break
    if t is None:
        return None
    dev = (dated[t].reindex(cont.index) / cont - 1).values          # NaN where the dated contract has no price
    idx, first = cont.index, anchor                                 # first: earliest day seen on the current contract
    for i in range(anchor, max(len(idx) - 1 - lookback, -1), -1):
        if dev[i] != dev[i]:
            continue
        if abs(dev[i]) <= tol:
            first = i
            continue
        j = i - 1
        while j >= 0 and dev[j] != dev[j]:
            j -= 1
        if j >= 0 and abs(dev[j]) > tol and (dev[j] > 0) == (dev[i] > 0):   # two days off in the same direction
            if abs(dev[i]) > MAX_ROLL:
                return None
            return {"date": idx[first].strftime("%Y-%m-%d"), "ratio": round(float(1 + dev[i]), 6), "contract": t}
    return None


def adjust(df, rolls):
    """Prices before each roll multiplied by its ratio (all rolls compound), so the history reads as today's contract."""
    out = df.copy()
    for r in rolls:
        before = out.index < pd.Timestamp(r["date"])
        if before.any() and not before.all():
            out.loc[before, PRICES] = out.loc[before, PRICES] * r["ratio"]
    return out


def merge_log(log, new, index):
    """`log` plus `new` unless a stored roll is within MIN_APART trading days of it (then it is that roll)."""
    if not new:
        return sorted(log, key=lambda r: r["date"])
    pos = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(index)}
    for r in log:
        a, b = pos.get(r["date"]), pos.get(new["date"])
        if r["date"] == new["date"] or (a is not None and b is not None and abs(a - b) < MIN_APART):
            return sorted(log, key=lambda r: r["date"])
    return sorted(log + [new], key=lambda r: r["date"])


def load_log(path):
    try:
        return json.load(open(path)) if path and os.path.exists(path) else []
    except (OSError, ValueError):
        return []


def _closes(ticker, period="1y"):
    import yfinance as yf
    raw = yf.download(ticker, period=period, interval="1d", auto_adjust=False, progress=False)
    if raw is None or not len(raw):
        return None
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    s = raw["Close"].dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s if len(s) else None


def update(ticker, full, log_path, today=None):
    """Stored rolls plus the latest one found now, for the continuous `ticker` with raw daily candles `full`."""
    log = load_log(log_path)
    if ticker not in ROOTS:
        return log
    try:
        dated = {}
        for t in candidates(*ROOTS[ticker], today or date.today()):
            try:
                s = _closes(t)
            except Exception:
                s = None
            if s is not None:
                dated[t] = s
        new = detect(full["close"], dated)
        if new:
            print(f"{ticker}: on {new['contract']} since {new['date']} (roll {(new['ratio'] - 1) * 100:+.2f}%)")
        else:
            print(f"{ticker}: no roll found in the last {LOOKBACK} days (dated contracts: {sorted(dated)})")
        return merge_log(log, new, full.index)
    except Exception as e:                                # never block the forecast
        print(f"{ticker}: roll check failed ({e!r})")
        return log


def merge(data_dir, store_dir):
    """Deploy job: save the rolls each forecast used into store/rolls/<key>.json."""
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        try:
            d = json.load(open(path))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or not d.get("rolls"):
            continue
        out = os.path.join(store_dir, "rolls", f"{d['key']}.json")
        known = {r["date"]: r for r in load_log(out)}
        for r in d["rolls"]:
            known.setdefault(r["date"], r)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump(sorted(known.values(), key=lambda r: r["date"]), open(out, "w"), separators=(",", ":"))
        print(f"{d['key']}: {len(known)} rolls stored")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3])
