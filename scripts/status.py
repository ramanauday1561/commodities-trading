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
From the 09:15 open the trade is the one recorded before the open (preopen.recorded, the call that is scored): later runs
recompute the pre-open call, and Yahoo's revisions of overnight prices can move it (23 Oct 2026: "no trade" at 08:57,
"down, lean" at 09:51, "up" by 12:35), which must never turn into a STAY for an option that was never bought.

Usage: python scripts/status.py <data_dir> [store_dir]   (reads today-nifty.json and the previous status.json, writes
status.json). With store_dir, every run is also appended to <store>/journal/<date>.json (scoreboard branch): what the
page said, why, the pre-open calls and the price at that moment, and whether an alert went out, so each day can be
checked and the rules improved from it.
A change of state is sent to the phone through every channel whose GitHub secrets are set (never in the repo):
  Telegram  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (a bot made with @BotFather; workflow "Telegram setup" finds the
            chat ID). Added 22 Oct 2026: ntfy messages reached the app but iOS never showed them as notifications.
  ntfy.sh   NTFY_TOPIC
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
    rec_fo = (p.get("recorded") or {}).get("from_open")
    after_open = _hm(now) >= (9, 15)
    if after_open and rec_fo:
        fo = {**fo, "trade": rec_fo.get("trade"), "direction": rec_fo.get("direction"), "pred_pct": rec_fo.get("pred_pct")}
    elif after_open and p:
        fo = {**fo, "trade": False, "no_call_before_open": True}
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
    if fo.get("no_call_before_open"):
        return {**base, "state": "NOTHING", "kind": "no_trade", "headline": "No trade today",
                "reason": "No call was made before the 09:15 open, so there is no trade to hold."}
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


TITLES = {"call": "NIFTY: BUY CALL", "put": "NIFTY: BUY PUT", "hold": "NIFTY: STAY in the {side}",
          "sell": "NIFTY: SELL the {side} now", "no_trade": "NIFTY: NOTHING today", "closed": "NIFTY: market closed",
          "test": "NIFTY: test alert"}
ICONS = {"call": "\U0001F7E2", "put": "\U0001F534", "sell": "\u26A0\uFE0F", "hold": "\u23F3", "test": "\U0001F514"}


def _title(status):
    return TITLES.get(status.get("kind", ""), "NIFTY").format(side=status.get("side", ""))


def send_ntfy(status, topic):
    """BUY / SELL are "urgent" (iOS: time-sensitive). No link: tapping just opens the alert."""
    kind = status.get("kind", "")
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=f"{status['headline']}. {status['reason']}".encode(),
                                 headers={"Title": _title(status),
                                          "Priority": "urgent" if kind in ("call", "put", "sell", "test") else "default",
                                          "Tags": {"call": "green_circle", "put": "red_circle", "sell": "warning",
                                                   "hold": "hourglass", "test": "bell"}.get(kind, "white_circle")})
    urllib.request.urlopen(req, timeout=15).read()


def send_telegram(status, token, chat_id):
    icon = ICONS.get(status.get("kind", ""), "\u26AA")
    text = f"{icon} {_title(status)}\n{status['headline']}. {status['reason']}"
    data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                 headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if not out.get("ok"):
        raise RuntimeError(f"telegram: {out.get('description')}")


def channels():
    env = os.environ
    out = []
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        out.append(("telegram", lambda st: send_telegram(st, env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"])))
    if env.get("NTFY_TOPIC"):
        out.append(("ntfy", lambda st: send_ntfy(st, env["NTFY_TOPIC"])))
    return out


def notify(status):
    """Send through every configured channel; one failing does not stop the others. Returns {channel: result}."""
    res = {}
    for name, send in channels():
        try:
            send(status)
            res[name] = "sent"
        except Exception as e:
            res[name] = f"failed: {e!r}"
    return res


def changed(prev, new):
    key = lambda s: (s.get("date"), s.get("state"), s.get("kind"))
    return not prev or key(prev) != key(new)


def journal_row(new, today, alert):
    p = (today or {}).get("preopen") or {}
    i = (today or {}).get("intraday") or {}
    calls = {k: {x: (p.get(k) or {}).get(x) for x in ("direction", "pred_pct", "tier", "trade")} for k in ("gap", "close", "from_open")}
    return {"at": new["updated"], "state": new["state"], "kind": new.get("kind"), "side": new.get("side"),
            "headline": new["headline"], "reason": new["reason"], "alert": alert, "calls": calls if p else None,
            "price": i.get("price"), "move_pct": i.get("move_pct"), "hourly_check": i.get("direction"),
            "hourly_accuracy": i.get("accuracy")}


def save_journal(store_dir, row, day):
    path = os.path.join(store_dir, "journal", f"{day}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        rows = json.load(open(path))
    except (OSError, ValueError):
        rows = []
    json.dump(rows + [row], open(path, "w"), separators=(",", ":"))


def main(data_dir, now=None, store_dir=None):
    now = now or datetime.now(IST)
    load = lambda name: json.load(open(os.path.join(data_dir, name))) if os.path.exists(os.path.join(data_dir, name)) else None
    prev, today = load("status.json"), load("today-nifty.json")
    new = decide(today, now)
    alert = None
    if changed(prev, new):
        new["since"] = new["updated"]
        quiet = new.get("kind") == "pending" or (new.get("kind") == "closed" and
                                                  (not prev or prev.get("kind") in ("closed", "no_trade", "pending")))
        if channels() and not quiet:
            alert = notify(new)                         # never raises: the page update always goes on
            print("alert:", new["state"], alert)
    else:
        new["since"] = prev.get("since", new["updated"])
    json.dump(new, open(os.path.join(data_dir, "status.json"), "w"), separators=(",", ":"))
    if store_dir:
        save_journal(store_dir, journal_row(new, today, alert), new["date"])
    print(json.dumps(new))
    return new


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "test":          # send one test alert (workflow "Status alert test")
        res = notify({"state": "NOTHING", "kind": "test", "headline": "Test alert from your NIFTY Status page",
                      "reason": sys.argv[2] or "If you see this, alerts work."})
        print("test alert:", res or "no channel configured")
        if not res or not any(v == "sent" for v in res.values()):
            sys.exit(1)
    else:
        main(sys.argv[1], store_dir=sys.argv[2] if len(sys.argv) > 2 else None)
