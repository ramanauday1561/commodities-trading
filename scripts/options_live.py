"""Live NIFTY option prices from Kite Connect, every 10 minutes (4 Nov 2026, asked by the user).

Usage: python scripts/options_live.py snap <dir> <data_dir>   (each 10-minute run; dir = a copy of the options-live branch)
       python scripts/options_live.py close <dir>             (after the close: the day's 5-minute option candles)
Until now real option prices came only from NSE's bhavcopy, the evening after (option_record.py). With the morning
Kite login, each run records the quotes of NIFTY options near the money (5 strikes around NIFTY now and the strike
at the open, CALL and PUT, the two nearest expiries after today) and writes options-live.json for the Live page:
the at-the-money CALL and PUT at NIFTY's open (next expiry after today, as option_record.py and option_study.py),
bought at the contract's first price of the day and worth its last price now, per lot after costs; and on a
09:15-signal trade day, that side. Information, like the rest of the money box.
Files: <dir>/snapshots/<date>.csv (one row per contract per run), <dir>/candles/<date>.csv (5-minute candles of the
contracts recorded that day, written after the close): our own intraday option history from 4 Nov 2026.
"""
import csv
import glob
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import kite

IST = ZoneInfo("Asia/Kolkata")
STEP, AROUND, EXPIRIES = 50, 2, 2
LOT, COST = 65, 1.85                     # option_study.py: NIFTY's lot, and ~Rs120 a lot of costs in premium points
SNAP_FROM, SNAP_TO = time(9, 16), time(15, 35)
FIELDS = ["at", "tradingsymbol", "expiry", "strike", "type", "ltp", "open", "high", "low", "prev_close", "volume", "oi",
          "bid", "ask", "spot"]


def chain(d, now, fetch=None):
    """NIFTY options of the next three expiries from Kite's NFO instrument list, cached for the day in <d>."""
    path = os.path.join(d, f"instruments-{now.date().isoformat()}.json")
    if os.path.exists(path):
        return json.load(open(path))
    rows = (fetch or (lambda: kite.instruments("NFO")))()
    opts = [r for r in rows if r.get("name") == "NIFTY" and r.get("segment") == "NFO-OPT" and r.get("expiry", "") >= now.date().isoformat()]
    keep = sorted({r["expiry"] for r in opts})[:3]
    out = [{"token": int(r["instrument_token"]), "symbol": r["tradingsymbol"], "expiry": r["expiry"],
            "strike": float(r["strike"]), "type": r["instrument_type"], "lot": int(float(r.get("lot_size") or LOT))}
           for r in opts if r["expiry"] in keep]
    os.makedirs(d, exist_ok=True)
    for old in glob.glob(os.path.join(d, "instruments-*.json")):
        os.remove(old)
    json.dump(out, open(path, "w"), separators=(",", ":"))
    return out


def atm(x):
    return round(x / STEP) * STEP


def pick(ch, today, strikes):
    """The contracts to record: these strikes, CALL and PUT, the two nearest expiries after today."""
    exps = sorted({c["expiry"] for c in ch if c["expiry"] > today.isoformat()})[:EXPIRIES]
    return [c for c in ch if c["expiry"] in exps and c["strike"] in strikes], exps


def leg(q, cost=COST, lot=LOT):
    """Bought at the contract's first price today, worth its last price now: points and rupees per lot after costs."""
    o, ltp = (q.get("ohlc") or {}).get("open"), q.get("last_price")
    if not o or not ltp:
        return None
    pts = ltp - o - cost
    return {"open": round(o, 2), "now": round(ltp, 2), "pts": round(pts, 2), "rs": int(round(pts * lot))}


def snap(d, data_dir, now=None, quote=None, fetch=None, today_json=None):
    """One run's quotes, appended to the day's snapshot file; options-live.json for the pages. None outside the
    session or without a Kite login."""
    now = now or datetime.now(IST)
    s = kite.session()
    if not s:
        print("options live: no Kite login today", flush=True)
        return None
    if not SNAP_FROM <= now.time() <= SNAP_TO:
        return None
    q = quote or (lambda syms: kite.quote(s[0], s[1], syms))
    idx = q(["NSE:NIFTY 50"]).get("NSE:NIFTY 50") or {}
    spot, day_open = idx.get("last_price"), (idx.get("ohlc") or {}).get("open")
    if not spot or not day_open:
        print("options live: no NIFTY quote", flush=True)
        return None
    ch = chain(d, now, fetch)
    strikes = {atm(spot) + STEP * k for k in range(-AROUND, AROUND + 1)} | {atm(day_open)}
    want, exps = pick(ch, now.date(), strikes)
    if not want:
        print("options live: no contracts found", flush=True)
        return None
    quotes = q([f"NFO:{c['symbol']}" for c in want])
    rows = []
    for c in want:
        x = quotes.get(f"NFO:{c['symbol']}") or {}
        depth = x.get("depth") or {}
        best = lambda side: ((depth.get(side) or [{}])[0] or {}).get("price")
        rows.append({"at": now.strftime("%H:%M"), "tradingsymbol": c["symbol"], "expiry": c["expiry"], "strike": c["strike"],
                     "type": c["type"], "ltp": x.get("last_price"), "open": (x.get("ohlc") or {}).get("open"),
                     "high": (x.get("ohlc") or {}).get("high"), "low": (x.get("ohlc") or {}).get("low"),
                     "prev_close": (x.get("ohlc") or {}).get("close"), "volume": x.get("volume"), "oi": x.get("oi"),
                     "bid": best("buy"), "ask": best("sell"), "spot": spot})
    os.makedirs(os.path.join(d, "snapshots"), exist_ok=True)
    path = os.path.join(d, "snapshots", f"{now.date().isoformat()}.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    near = exps[0]
    by = {(c["strike"], c["type"]): quotes.get(f"NFO:{c['symbol']}") or {} for c in want if c["expiry"] == near}
    k0, k1 = atm(day_open), atm(spot)
    out = {"date": now.date().isoformat(), "at": now.strftime("%H:%M"), "spot": spot, "open": day_open, "expiry": near,
           "lot": LOT, "basis": "Kite live prices: bought at the contract's first price today, worth its last price now, per lot after about Rs120 of costs",
           "call": {"strike": k0, **(leg(by.get((k0, "CE"), {})) or {})}, "put": {"strike": k0, **(leg(by.get((k0, "PE"), {})) or {})},
           "atm_now": {"strike": k1, "call": (by.get((k1, "CE")) or {}).get("last_price"), "put": (by.get((k1, "PE")) or {}).get("last_price")}}
    t = today_json or {}
    fo = (((t.get("preopen") or {}).get("recorded") or {}).get("from_open") or {})
    if t.get("date") == out["date"] and fo.get("trade"):
        side = "call" if fo.get("direction") == "up" else "put"
        out["app"] = {"side": side.upper(), **out[side]}
    json.dump(out, open(os.path.join(data_dir, "options-live.json"), "w"), separators=(",", ":"))
    print(f"options live: {len(rows)} contracts at {out['at']}, NIFTY {spot:,.2f}; ATM {k0:.0f} CALL {out['call'].get('rs')} PUT {out['put'].get('rs')} Rs a lot",
          flush=True)
    return out


def close(d, now=None, history=None):
    """After the close: the day's 5-minute candles of every contract recorded today."""
    now = now or datetime.now(IST)
    s = kite.session()
    path = os.path.join(d, "snapshots", f"{now.date().isoformat()}.csv")
    if not s or not os.path.exists(path) or now.time() < time(15, 31):
        print("options live close: nothing to do (no login, no snapshots today, or before 15:31)", flush=True)
        return None
    syms = sorted({r["tradingsymbol"] for r in csv.DictReader(open(path))})
    ch = {c["symbol"]: c for c in chain(d, now)}
    hist = history or (lambda tok: kite.history(s[0], s[1], tok, "5minute", datetime.combine(now.date(), time(9, 15)),
                                                datetime.combine(now.date(), time(15, 30)), max_days=1))
    out = []
    for sym in syms:
        c = ch.get(sym)
        if not c:
            continue
        try:
            for t, o, h, lo, cl, v in hist(c["token"]):
                out.append({"datetime": t.strftime("%Y-%m-%d %H:%M"), "tradingsymbol": sym, "expiry": c["expiry"],
                            "strike": c["strike"], "type": c["type"], "open": o, "high": h, "low": lo, "close": cl, "volume": v})
        except Exception as e:
            print(f"options live close: {sym} failed ({e})", flush=True)
    if out:
        os.makedirs(os.path.join(d, "candles"), exist_ok=True)
        with open(os.path.join(d, "candles", f"{now.date().isoformat()}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)
    print(f"options live close: {len(out)} candles for {len(syms)} contracts", flush=True)
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["snap"]:
        tj = os.path.join(sys.argv[3], "today-nifty.json")
        snap(sys.argv[2], sys.argv[3], today_json=json.load(open(tj)) if os.path.exists(tj) else None)
    if sys.argv[1:2] == ["close"]:
        close(sys.argv[2])
