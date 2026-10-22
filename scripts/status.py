"""NIFTY trade status for the Status page (docs/status.html) and phone alerts: CALL, PUT, WAIT, EXIT or CLOSED.

Only the from-open signal decides a trade: it is the one call tested on what a trade from the 09:15 open earns
(top-20% most confident days, walk-forward, after costs: about 57% of trades won, +0.15% each; 22 Oct 2026). On every
other day the answer is WAIT; the close call and the hourly checks are about the close vs yesterday, which is mostly
the opening gap, and were not worth trading from the open (open_study, hourly_study, review_study).
  CALL / PUT  buy an at-the-money NIFTY option at the 09:15 open (the signal is made at ~08:57)
  EXIT        from the last hourly check (~14:50): square off before 15:15
  PENDING     before ~08:40 (no alert)
  WAIT        no trade today (no edge or heavyweight results)
  CLOSED      after the close, with how the day's trade did

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
        return {**base, "state": "CLOSED", "headline": "Market closed", "reason": why}
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
            return {**base, "state": "CLOSED", "headline": f"Closed: today's {side} {'won' if move > 0 else 'lost'}",
                    "reason": f"NIFTY {rec['open']:,.2f} at the open → {rec['close']:,.2f} at the close: "
                              f"{move:+.2f}% for the {side} side before costs."}
        return {**base, "state": "CLOSED", "headline": "Market closed", "reason": "No trade today."}
    if not p or _hm(now) < CALL_FROM:
        return {**base, "state": "PENDING", "headline": "Wait for the 08:57 call", "reason": "Today's signal is made at about 08:57 IST."}
    if fo.get("skipped_for_results"):
        return {**base, "state": "WAIT", "headline": "No trade today",
                "reason": "Heavyweight results came out since the last close; the signal stands aside on those days."}
    if not trade:
        lean = (p.get("close") or {})
        hint = (f" The close call leans {'higher' if lean.get('direction') == 'up' else 'lower'}, "
                f"but that is mostly the opening gap, not a trade.") if lean.get("tier") not in (None, "none") else ""
        return {**base, "state": "WAIT", "headline": "No trade today",
                "reason": "Overnight markets give no edge from the open (the signal trades only its 20% most confident days)." + hint}
    if _hm(now) >= EXIT_FROM and today.get("status") == "open":
        return {**base, "state": "EXIT", "side": side, "headline": f"Exit the {side} now",
                "reason": "Square off before 15:15. The signal holds from the open to the close only."}
    return {**base, "state": side, "side": side, "headline": f"Buy a NIFTY {side} at the open",
            "reason": f"At-the-money weekly option, bought at 09:15, held to the close (exit by 15:15). {record}",
            "pred_pct": fo.get("pred_pct")}


def notify(status, topic):
    title = {"CALL": "NIFTY: BUY CALL", "PUT": "NIFTY: BUY PUT", "EXIT": "NIFTY: EXIT NOW",
             "WAIT": "NIFTY: NO TRADE", "CLOSED": "NIFTY: market closed", "PENDING": "NIFTY: waiting"}[status["state"]]
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=f"{status['headline']}. {status['reason']}".encode(),
                                 headers={"Title": title, "Click": PAGE,
                                          "Priority": "high" if status["state"] in ("CALL", "PUT", "EXIT") else "default",
                                          "Tags": {"CALL": "green_circle", "PUT": "red_circle", "EXIT": "warning"}.get(status["state"], "white_circle")})
    urllib.request.urlopen(req, timeout=15).read()


def changed(prev, new):
    return not prev or (prev.get("date"), prev.get("state")) != (new["date"], new["state"])


def main(data_dir, now=None):
    now = now or datetime.now(IST)
    load = lambda name: json.load(open(os.path.join(data_dir, name))) if os.path.exists(os.path.join(data_dir, name)) else None
    prev, today = load("status.json"), load("today-nifty.json")
    new = decide(today, now)
    if changed(prev, new):
        new["since"] = new["updated"]
        topic = os.environ.get("NTFY_TOPIC")
        quiet = new["state"] == "PENDING" or (new["state"] == "CLOSED" and (not prev or prev.get("state") in ("CLOSED", "WAIT", "PENDING")))
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
        notify({"state": "WAIT", "headline": "Test alert from your NIFTY Status page",
                "reason": sys.argv[2] or "If you see this, alerts work."}, os.environ["NTFY_TOPIC"])
        print("test alert sent")
    else:
        main(sys.argv[1])
