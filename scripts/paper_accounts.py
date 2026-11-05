"""Paper accounts on real option prices (5 Nov 2026, asked by the user): what each of the app's ideas would have made,
Rs 2 lakh each from 4 Nov 2026, one lot a trade, scored every day at the close. No money is ever traded.

Usage: python scripts/paper_accounts.py <options_live_dir> <data_dir> [YYYY-MM-DD ...]   (the close run; dates to rescore)
Until now the Next 10 page priced each lean as "the option moves half as much as NIFTY, minus Rs120". Since 4 Nov the
app saves Kite's real option quotes every 10 minutes (options_live.py), so each lean is now priced as a trader would
have done it: buy the at-the-money option of the lean's side (the next expiry after today; the strike nearest NIFTY
when the lean was made) at its price in the run that made the lean, sell it at its price in the next run (~10 minutes
later), 1.85 option points of costs (about Rs120 a lot, as option_study.py). Where no snapshot run is there (snapshots
began at 11:45 on 4 Nov; a run can be late), the option's own 5-minute Kite candles stand in: the close of the candle
ending at the lean's time and of the candle ending 10 minutes later, the strike from NIFTY's close at the lean's time.
Accounts:
  leans        every Next 10 lean
  leans_star   only the more confident (top-20%) leans
  straddle     the paper short straddle (options_live.paper: the 50%-stop straddle from the open)
  signal_lean  the 09:15 signal's lean every day, the at-the-money option on its side from the open to the close
Files: <options_live_dir>/paper/accounts.json (every day), <data_dir>/paper-accounts.json (the pages).
Backtest on the first two days (run 5 Nov 2026 on the options-live branch's quotes and candles; Rs a lot after costs):
              4 Nov                  5 Nov                  balance
  every lean  -5,714 (14/34 won)     -8,407 (9/34 won)      1,85,879   (the half-delta estimate said -5,094 and -6,256)
  * leans     -1,294 (2/4)           +488 (6/12)            1,99,194
  straddle    +4,081                 +4,833                 2,08,914
  09:15 lean  -9,425 (put, down)     -8,401 (put, down)     1,82,174   (NIFTY rose on both days)
Real prices cost the leans more than the estimate: an at-the-money option moved less than half of NIFTY's move in ten
minutes and lost time value, so the leans stay information only.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
START, CAPITAL, LOT, COST, STEP = "2026-11-04", 200000, 65, 1.85, 50
NAMES = {"leans": "Next 10: every lean", "leans_star": "Next 10: ★ leans only", "straddle": "Paper short straddle (50% stops)",
         "signal_lean": "09:15 signal's lean, every day"}


def _mins(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def load_snapshots(path):
    """{run time 'HH:MM': {(expiry, strike, type): ltp}, ...} and {run time: spot}."""
    runs, spot = {}, {}
    if not os.path.exists(path):
        return runs, spot
    for r in csv.DictReader(open(path)):
        try:
            ltp = float(r["ltp"])
        except (TypeError, ValueError):
            continue
        runs.setdefault(r["at"], {})[(r["expiry"], float(r["strike"]), r["type"])] = ltp
        if r.get("spot"):
            spot[r["at"]] = float(r["spot"])
    return runs, spot


def load_candles(path):
    """{(expiry, strike, type): {'HH:MM' the candle ends: close}} from the day's 5-minute option candles."""
    out = {}
    if not os.path.exists(path):
        return out
    for r in csv.DictReader(open(path)):
        try:
            end = _mins(r["datetime"][11:16]) + 5
            out.setdefault((r["expiry"], float(r["strike"]), r["type"]), {})[f"{end // 60:02d}:{end % 60:02d}"] = float(r["close"])
        except (KeyError, ValueError):
            continue
    return out


def nifty_spot(candles):
    """{'HH:MM' a candle ends: NIFTY close} from the Next 10 page's candles (the chart's times: IST clock time as UTC)."""
    out = {}
    for c in candles or []:
        try:
            t = datetime.fromtimestamp(c["time"], timezone.utc)
            end = t.hour * 60 + t.minute + 10                          # the page's candles are 10 minutes
            out[f"{end // 60:02d}:{end % 60:02d}"] = float(c["close"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _from_runs(l, runs, spot, times, day):
    made = _mins(l.get("made") or l["at"])
    t0 = next((t for t in times if made <= _mins(t) <= made + 4), None)          # the run that made the lean
    if t0 is None or t0 not in spot:
        return None
    t1 = next((t for t in times if _mins(t) >= _mins(t0) + 8), None)              # the next run, ~10 minutes on
    if t1 is None or _mins(t1) > _mins(t0) + 14:
        return None
    exps = sorted({k[0] for k in runs[t0] if k[0] > day})
    if not exps:
        return None
    k = round(spot[t0] / STEP) * STEP
    key = (exps[0], float(k), "CE" if l["lean"] == "up" else "PE")
    if key not in runs[t0] or key not in runs[t1]:
        return None
    return key, runs[t0][key], runs[t1][key], t0, t1, "quotes"


def _from_candles(l, candles, nspot, day):
    t0, at = l["at"], _mins(l["at"])                                  # the candle boundary the lean is for
    t1 = f"{(at + 10) // 60:02d}:{(at + 10) % 60:02d}"
    if t0 not in nspot:
        return None
    exps = sorted({k[0] for k in candles if k[0] > day})
    if not exps:
        return None
    key = (exps[0], float(round(nspot[t0] / STEP) * STEP), "CE" if l["lean"] == "up" else "PE")
    c = candles.get(key, {})
    if t0 not in c or t1 not in c:
        return None
    return key, c[t0], c[t1], t0, t1, "candles"


def price_leans(leans, runs, spot, day, candles=None, nspot=None):
    """Each lean on real prices: [{at, lean, confident, strike, entry, exit, pts, rs, by}] (leans without prices left out)."""
    times = sorted(runs, key=_mins)
    out = []
    for l in leans:
        got = _from_runs(l, runs, spot, times, day) or (_from_candles(l, candles, nspot, day) if candles and nspot else None)
        if not got:
            continue
        key, entry, exit_, t0, t1, by = got
        pts = exit_ - entry - COST
        out.append({"at": l["at"], "lean": l["lean"], "confident": bool(l.get("confident")), "size": l.get("size"),
                    "typical": l.get("typical"), "strike": key[1], "type": key[2], "entry": entry, "exit": exit_,
                    "from": t0, "to": t1, "by": by, "pts": round(pts, 2), "rs": int(round(pts * LOT))})
    return out


def signal_lean(candles_path, direction, nifty_open, day):
    """The 09:15 lean's side, the at-the-money option of the next expiry, from the open to the close (Rs a lot)."""
    if not direction or not nifty_open or not os.path.exists(candles_path):
        return None
    rows = list(csv.DictReader(open(candles_path)))
    exps = sorted({r["expiry"] for r in rows if r["expiry"] > day})
    if not exps:
        return None
    k, typ = round(nifty_open / STEP) * STEP, "CE" if direction == "up" else "PE"
    c = sorted((r for r in rows if r["expiry"] == exps[0] and float(r["strike"]) == k and r["type"] == typ), key=lambda r: r["datetime"])
    if not c:
        return None
    pts = float(c[-1]["close"]) - float(c[0]["open"]) - COST
    return {"side": typ, "strike": k, "entry": float(c[0]["open"]), "exit": float(c[-1]["close"]), "pts": round(pts, 2), "rs": int(round(pts * LOT))}


def day_result(d, day, leans, record_row, straddle_rows, nspot=None):
    runs, spot = load_snapshots(os.path.join(d, "snapshots", f"{day}.csv"))
    priced = price_leans(leans, runs, spot, day, load_candles(os.path.join(d, "candles", f"{day}.csv")), nspot)
    star = [x for x in priced if x["confident"]]
    acc = {"leans": {"rs": sum(x["rs"] for x in priced), "trades": len(priced), "won": sum(x["rs"] > 0 for x in priced),
                     "of": len(leans)},
           "leans_star": {"rs": sum(x["rs"] for x in star), "trades": len(star), "won": sum(x["rs"] > 0 for x in star)}}
    st = next((x for x in straddle_rows if x["d"] == day and x.get("final")), None)
    if st:
        acc["straddle"] = {"rs": st["rs"], "trades": 1, "won": int(st["rs"] > 0)}
    if record_row:
        sl = signal_lean(os.path.join(d, "candles", f"{day}.csv"), record_row.get("from_open_dir"), record_row.get("open"), day)
        if sl:
            acc["signal_lean"] = {"rs": sl["rs"], "trades": 1, "won": int(sl["rs"] > 0), **{k: sl[k] for k in ("side", "strike", "entry", "exit")}}
    return {"d": day, "accounts": acc, "leans": priced}


def update(d, data_dir, days=None, now=None):
    now = now or datetime.now(IST)
    path = os.path.join(d, "paper", "accounts.json")
    book = json.load(open(path)) if os.path.exists(path) else {"start": START, "capital": CAPITAL, "days": []}
    nxt = _load(os.path.join(data_dir, "next-nifty.json")) or {}
    today = _load(os.path.join(data_dir, "today-nifty.json")) or {}
    recent = {r["d"]: r for r in (today.get("record") or {}).get("recent", [])}
    straddle_rows = _load(os.path.join(d, "paper", "straddle.json")) or []
    lean_book, spot_book = book.setdefault("leans_by_day", {}), book.setdefault("spot_by_day", {})
    if nxt.get("date"):
        lean_book[nxt["date"]] = nxt.get("leans", [])                 # the day's leans and NIFTY, kept for rescoring
        spot_book[nxt["date"]] = nifty_spot(nxt.get("candles"))
    want = days or ([nxt["date"]] if nxt.get("date") else [])
    for day in want:
        if day < START or not any(os.path.exists(os.path.join(d, k, f"{day}.csv")) for k in ("snapshots", "candles")):
            continue
        res = day_result(d, day, lean_book.get(day, []), recent.get(day), straddle_rows, spot_book.get(day))
        book["days"] = sorted([x for x in book["days"] if x["d"] != day] + [res], key=lambda x: x["d"])
    totals = {}
    for x in book["days"]:
        for k, v in x["accounts"].items():
            t = totals.setdefault(k, {"rs": 0, "days": 0, "up_days": 0, "trades": 0, "won": 0})
            t["rs"] += v["rs"]; t["days"] += 1; t["up_days"] += int(v["rs"] > 0); t["trades"] += v["trades"]; t["won"] += v["won"]
    book["totals"] = {k: {**v, "balance": CAPITAL + v["rs"], "name": NAMES.get(k, k)} for k, v in totals.items()}
    book["updated"] = now.isoformat(timespec="minutes")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(book, open(path, "w"), indent=0)
    page = {"updated": book["updated"], "start": START, "capital": CAPITAL, "totals": book["totals"],
            "days": [{"d": x["d"], "accounts": x["accounts"]} for x in book["days"][-15:]],
            "today_leans": book["days"][-1]["leans"] if book["days"] else [],
            "basis": "Kite's real option quotes: each lean bought at its at-the-money option's price in the run that made it, sold in the next run (~10 min), about Rs120 a lot of costs; paper only"}
    json.dump(page, open(os.path.join(data_dir, "paper-accounts.json"), "w"), separators=(",", ":"))
    for k, v in book["totals"].items():
        print(f"paper {k}: {v['days']} days, Rs {v['rs']:+,} -> balance Rs {v['balance']:,}", flush=True)
    return book


def _load(p):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    update(sys.argv[1], sys.argv[2], sys.argv[3:] or None)
