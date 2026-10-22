"""NIFTY trade status for the Status page (docs/status.html) and phone alerts: CALL, PUT, STAY, SELL or NOTHING.

Only the from-open signal decides a trade: it is the one call tested on what a trade from the 09:15 open earns
(top-20% most confident days, walk-forward, after costs: about 57% of trades won, +0.15% each; 22 Oct 2026). On every
other day the answer is NOTHING; the close call and the hourly checks are about the close vs yesterday, which is mostly
the opening gap, and were not worth trading from the open (open_study, hourly_study, review_study).
  CALL / PUT  buy an at-the-money NIFTY option at the 09:15 open (the signal is made at ~08:57)
  STAY        a trade is on: keep holding it (from the 09:15 open until the exit)
  SELL        time to exit: sell (square off) the option before 15:15 (from the last hourly check, ~14:50)
  NOTHING     no trade today, before the 08:57 signal, or the market is closed
Each state also has a "kind" (call/put, hold, sell, no_trade, pending, closed); an alert goes out when either changes,
except before the signal ("pending") and at a close that followed a day without a trade.

Usage: python scripts/status.py <data_dir>   (reads today-nifty.json and the previous status.json, writes status.json)
A change of state is sent to the phone via ntfy.sh when NTFY_TOPIC is set (a GitHub secret; never in the repo).
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
CALL_FROM = (8, 40)          # earlier runs (the 06:30 forecast) use a stale overnight picture: no trade state yet
EXIT_FROM = (14, 40)         # the last hourly check of the day (~14:50) says square off
PAGE = "https://ramanauday1561.github.io/commodities-trading/status.html"


def _hm(t):
    return (t.hour, t.minute)


def decide(today, now):
    """today: today-nifty.json (or None); now: aware datetime in IST."""
    date = now.date().isoformat()
    base = {"date": date, "updated": now.isoformat(timespec="minutes")}
    if not today or today.get("status") == "holiday" or today.get("date") != date:
        why = "NSE holiday" if today and today.get("status") == "holiday" and today.get("date") == date else "No market today"
        return {**base, "state": "NOTHING", "kind": "closed", "headline": "Market closed", "reason": why}
    p = today.get("preopen") or {}
    fo = p.get("from_open") or {}
    trade = bool(fo.get("trade"))
    side = "CALL" if fo.get("direction") == "up" else "PUT"
    stats = fo.get("trade_stats") or {}
    o = stats.get("from_open") or {}
    record = (f"Past trades like this won {round(o['win_rate'] * 100)}% of the time, "
              f"{o['avg_pct_after_costs']:+.2f}% each after costs ({stats.get('days')} days)." if o else "")
    if today.get("status") == "closed" or _hm(now) >= (15, 30):
        rec = next((r for r in (today.get("record") or {}).get("recent", []) if r.get("d") == date), None)
        if trade and rec and rec.get("open") and rec.get("close"):
            move = (rec["close"] / rec["open"] - 1) * 100 * (1 if side == "CALL" else -1)
            return {**base, "state": "NOTHING", "kind": "closed", "headline": f"Closed: today's {side} {'won' if move > 0 else 'lost'}",
                    "reason": f"NIFTY {rec['open']:,.2f} at the open → {rec['close']:,.2f} at the close: "
                              f"{move:+.2f}% for the {side} side before costs."}
        return {**base, "state": "NOTHING", "kind": "closed", "headline": "Market closed", "reason": "No trade today."}
    if not p or _hm(now) < CALL_FROM:
        return {**base, "state": "NOTHING", "kind": "pending", "headline": "Wait for the 08:57 call", "reason": "Today's signal is made at about 08:57 IST."}
    if fo.get("skipped_for_results"):
        return {**base, "state": "NOTHING", "kind": "no_trade", "headline": "No trade today",
                "reason": "Heavyweight results came out since the last close; the signal stands aside on those days."}
    if not trade:
        lean = (p.get("close") or {})
        hint = (f" The close call leans {'higher' if lean.get('direction') == 'up' else 'lower'}, "
                f"but that is mostly the opening gap, not a trade.") if lean.get("tier") not in (None, "none") else ""
        return {**base, "state": "NOTHING", "kind": "no_trade", "headline": "No trade today",
                "reason": "Overnight markets give no edge from the open (the signal trades only its 20% most confident days)." + hint}
    if _hm(now) >= EXIT_FROM and today.get("status") == "open":
        return {**base, "state": "SELL", "kind": "sell", "side": side, "headline": f"Sell the {side} now",
                "reason": "Square off before 15:15. The signal holds from the open to the close only."}
    if _hm(now) >= (9, 15):
        return {**base, "state": "STAY", "kind": "hold", "side": side, "headline": f"Stay in the {side}",
                "reason": f"Keep holding the {side} bought at the 09:15 open; you get a SELL alert at about 14:50. {record}"}
    return {**base, "state": side, "kind": side.lower(), "side": side, "headline": f"Buy a NIFTY {side} at the open",
            "reason": f"At-the-money weekly option, bought at 09:15, held to the close (exit by 15:15). {record}",
            "pred_pct": fo.get("pred_pct")}


def notify(status, topic):
    kind = status.get("kind", "")
    title = {"call": "NIFTY: BUY CALL", "put": "NIFTY: BUY PUT", "hold": f"NIFTY: STAY in the {status.get('side', '')}",
             "sell": f"NIFTY: SELL the {status.get('side', '')} now", "no_trade": "NIFTY: NOTHING today", "closed": "NIFTY: market closed"}.get(kind, "NIFTY")
    urgent = kind in ("call", "put", "sell")
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=f"{status['headline']}. {status['reason']}".encode(),
                                 headers={"Title": title, "Click": PAGE, "Priority": "high" if urgent else "default",
                                          "Tags": {"call": "green_circle", "put": "red_circle", "sell": "warning",
                                                   "hold": "hourglass"}.get(kind, "white_circle")})
    urllib.request.urlopen(req, timeout=15).read()


def changed(prev, new):
    key = lambda s: (s.get("date"), s.get("state"), s.get("kind"))
    return not prev or key(prev) != key(new)


def main(data_dir, now=None):
    now = now or datetime.now(IST)
    load = lambda name: json.load(open(os.path.join(data_dir, name))) if os.path.exists(os.path.join(data_dir, name)) else None
    prev, today = load("status.json"), load("today-nifty.json")
    new = decide(today, now)
    if changed(prev, new):
        new["since"] = new["updated"]
        topic = os.environ.get("NTFY_TOPIC")
        quiet = new.get("kind") == "pending" or (new.get("kind") == "closed" and
                                                  (not prev or prev.get("kind") in ("closed", "no_trade", "pending")))
        if topic and not quiet:
            try:
                notify(new, topic)
                print("alert sent:", new["state"])
            except Exception as e:                      # an alert failing must not stop the page update
                print("alert failed:", repr(e))
    else:
        new["since"] = prev.get("since", new["updated"])
    json.dump(new, open(os.path.join(data_dir, "status.json"), "w"), separators=(",", ":"))
    print(json.dumps(new))
    return new


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "test":          # send one test alert (workflow "Status alert test")
        notify({"state": "NOTHING", "kind": "test", "headline": "Test alert from your NIFTY Status page",
                "reason": sys.argv[2] or "If you see this, alerts work."}, os.environ["NTFY_TOPIC"])
        print("test alert sent")
    else:
        main(sys.argv[1])
