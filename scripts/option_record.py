"""Each session on real NIFTY option prices, for the Live page's "Rs2 lakh" box and the History page (31 Oct 2026).

Usage: python scripts/option_record.py <store_dir> <data_dir> <opt_dir>[,<opt_dir>...]
The money box priced options as half NIFTY's move minus a fixed cost. NSE's bhavcopy (option_data.py) has the real
premiums but comes out in the evening, so the 04:00 IST run adds the sessions before it. For each session: the
at-the-money CALL and PUT nearest NIFTY's official open (this week's expiry; next week's on an expiry day, as
option_study.py found better), bought at the open and sold at the close, after about Rs120 a lot of costs; and on
days the 09:15 signal traded, its side. All open to close with no stop: the bhavcopy has no 15:15 or intraday prices.
Writes <data_dir>/options-nifty.json with the last 60 sessions.
"""
import json
import os
import sys

import pandas as pd

import option_data
import option_study as ost

KEEP = 60


def leg(o):
    pts = float(o["close"]) - float(o["open"]) - ost.COST
    return {"strike": float(o["strike"]), "expiry": str(o["expiry"]), "open": float(o["open"]), "close": float(o["close"]),
            "pts": round(pts, 2), "rs": int(round(pts * ost.LOT))}


def build(opt, calls):
    """calls: store/calls/nifty.json (each with the day's official open and the 09:15 signal)."""
    by_day = {d: g for d, g in opt.groupby("d")}
    out = []
    for c in calls:
        d, opn = pd.Timestamp(c["d"]).date(), (c.get("result") or {}).get("open")
        ch = by_day.get(d)
        if not opn or ch is None:
            continue
        row = {"d": c["d"], "open": opn}
        for typ, key in (("CE", "call"), ("PE", "put")):
            o = ost.pick(ch, d, float(opn), typ, "no_expiry_day")
            if o is not None:
                row[key] = leg(o)
        fo = c.get("from_open") or {}
        side = "call" if fo.get("direction") == "up" else "put"
        if fo.get("trade") and row.get(side):
            row["app"] = {"side": side.upper(), **row[side]}
        out.append(row)
    return out[-KEEP:]


def main(store_dir, data_dir, dirs):
    calls_path = os.path.join(store_dir, "calls", "nifty.json")
    calls = json.load(open(calls_path)) if os.path.exists(calls_path) else []
    opt = option_data.load(dirs)
    days = build(opt, calls) if len(opt) else []
    json.dump({"updated": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(timespec="minutes"), "lot": ost.LOT,
               "basis": "real NSE option prices (bhavcopy), bought at the open and sold at the close, no stop, about Rs120 a lot of costs",
               "days": days}, open(os.path.join(data_dir, "options-nifty.json"), "w"), separators=(",", ":"))
    print(f"option record: {len(days)} sessions, last {days[-1]['d'] if days else '-'}", flush=True)
    return days


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3].split(","))
