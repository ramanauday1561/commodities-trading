"""NIFTY trade status for the Status page (docs/status.html) and phone alerts: CALL, PUT, STAY, SELL or NOTHING.

Only the from-open signal decides a trade: it is the one call tested on what a trade from the 09:15 open earns
(top-20% most confident days, walk-forward, after costs: about 57% of trades won, +0.15% each; 22 Oct 2026). On every
other day the answer is NOTHING; the close call and the hourly checks are about the close vs yesterday, which is mostly
the opening gap, and were not worth trading from the open (open_study, hourly_study, review_study).
  CALL / PUT  buy an at-the-money NIFTY option at the 09:15 open (the signal is made at ~08:57)
  STAY        a trade is on: keep holding it (from the 09:15 open until the exit)
  SELL        time to exit: sell (square off) the option before 15:15 (from the last hourly check, ~14:50), or at
              once when NIFTY has moved 0.5% against the trade from the open (the stop, kind "stop")
  NOTHING     no trade today, before the 08:57 signal, or the market is closed
Each state also has a "kind" (call/put, hold, sell, no_trade, pending, closed); an alert goes out when either changes,
except before the signal ("pending") and at the close, which gets the day's summary instead.
Besides the alerts (26 Oct 2026, the user asked for updates as the day goes on):
  hourly update  each intraday run during the session sends a silent message: price, move, the hourly check, the
                 state and the newest headlines. It is information, not a trade signal: hourly forecasts and entries
                 after the open were tested and lost money after costs (hourly_study, open_study).
  summary        once after the close on every trading day: the close, the move from the open, how the pre-open
                 calls did and, on a trade day, what the trade made.
The "no signal" warning, sent when the 08:57 call is missing, is in keeper.py.
Stop (26 Oct 2026, exit_study): a stop 0.5% against the open made about the same as holding to the close (+12.2% vs
+12.6% over 77 trades) and cut the worst day from -2.1% to -0.5%. It failed the profit test, so it is risk control,
not an improvement: the user chose it. Every run checks the day's high / low against it, and on trade days keeper.py
looks at NIFTY every 5 minutes and starts a run as soon as the stop is reached, so the alert is minutes late at most.
A stop order in the broker app triggers sooner; the alert is the backup. The scored record stays open to close.
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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
CALL_FROM = (8, 40)          # earlier runs (the 06:30 forecast) use a stale overnight picture: no trade state yet
EXIT_FROM = (14, 40)         # the last hourly check of the day (~14:50) says square off
STOP_PCT = 0.5               # sell when NIFTY has moved this far (%) against the trade from the 09:15 open


def stop_level(side, opn):
    return opn * (1 - STOP_PCT / 100) if side == "CALL" else opn * (1 + STOP_PCT / 100)


def stop_hit(side, opn, high, low):
    """Has NIFTY reached the stop since the open? (side CALL / PUT; the day's high and low so far)"""
    if not opn or high is None or low is None:
        return False
    return low <= stop_level(side, opn) if side == "CALL" else high >= stop_level(side, opn)


def _stop_text(side, opn):
    return (f"Stop: sell if NIFTY goes {'below' if side == 'CALL' else 'above'} {stop_level(side, opn):,.2f} "
            f"({STOP_PCT}% against the open {opn:,.2f}).")


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
    i = today.get("intraday") or {}
    if today.get("status") == "closed" or _hm(now) >= (15, 30):
        rec = next((r for r in (today.get("record") or {}).get("recent", []) if r.get("d") == date), None)
        if trade and rec and rec.get("open") and rec.get("close"):
            move = (rec["close"] / rec["open"] - 1) * 100 * (1 if side == "CALL" else -1)
            if stop_hit(side, rec["open"], i.get("high"), i.get("low")):
                return {**base, "state": "NOTHING", "kind": "closed", "side": side,
                        "headline": f"Closed: today's {side} was stopped out",
                        "reason": f"NIFTY reached the stop {stop_level(side, rec['open']):,.2f} ({STOP_PCT}% against the "
                                  f"open {rec['open']:,.2f}): -{STOP_PCT:.2f}% for the {side} before costs. Held to the "
                                  f"close ({rec['close']:,.2f}) it would have made {move:+.2f}%."}
            return {**base, "state": "NOTHING", "kind": "closed", "headline": f"Closed: today's {side} {'won' if move > 0 else 'lost'}",
                    "reason": f"NIFTY {rec['open']:,.2f} at the open → {rec['close']:,.2f} at the close: "
                              f"{move:+.2f}% for the {side} side before costs."}
        return {**base, "state": "NOTHING", "kind": "closed", "headline": "Market closed", "reason": "No trade today."}
    if not p or _hm(now) < CALL_FROM:
        return {**base, "state": "NOTHING", "kind": "pending", "headline": "Wait for the 08:57 call", "reason": "Today's signal is made at about 08:57 IST."}
    if fo.get("skipped_for_results"):
        return {**base, "state": "NOTHING", "kind": "no_trade", "headline": "No trade today",
                "reason": "Heavyweight results came out since the last close; the signal stands aside on those days."}
    if fo.get("skipped_for_us_events"):
        return {**base, "state": "NOTHING", "kind": "no_trade", "headline": "No trade today",
                "reason": f"US news since the last close ({', '.join(fo.get('us_events') or []) or 'a US release'}); "
                          "the signal stands aside on the session after US inflation, jobs or Fed news."}
    if fo.get("no_call_before_open"):
        return {**base, "state": "NOTHING", "kind": "no_trade", "headline": "No trade today",
                "reason": "No call was made before the 09:15 open, so there is no trade to hold."}
    if not trade:
        lean = (p.get("close") or {})
        hint = (f" The close call leans {'higher' if lean.get('direction') == 'up' else 'lower'}, "
                f"but that is mostly the opening gap, not a trade.") if lean.get("tier") not in (None, "none") else ""
        return {**base, "state": "NOTHING", "kind": "no_trade", "headline": "No trade today",
                "reason": "Overnight markets give no edge from the open (the signal trades only its 20% most confident days)." + hint}
    opn = i.get("open")
    if after_open and stop_hit(side, opn, i.get("high"), i.get("low")):
        far = i["low"] if side == "CALL" else i["high"]
        return {**base, "state": "SELL", "kind": "stop", "side": side, "headline": f"Stop hit: sell the {side} now",
                "reason": f"NIFTY reached {far:,.2f}, past the stop {stop_level(side, opn):,.2f} ({STOP_PCT}% against "
                          f"the open {opn:,.2f}). Square off now; no new trade today."}
    if _hm(now) >= EXIT_FROM and today.get("status") == "open":
        return {**base, "state": "SELL", "kind": "sell", "side": side, "headline": f"Sell the {side} now",
                "reason": "Square off before 15:15. The signal holds from the open to the close only."}
    if after_open:
        return {**base, "state": "STAY", "kind": "hold", "side": side, "headline": f"Stay in the {side}",
                "reason": f"Keep holding the {side} bought at the 09:15 open; you get a SELL alert at about 14:50. "
                          + (_stop_text(side, opn) + " " if opn else "") + record}
    return {**base, "state": side, "kind": side.lower(), "side": side, "headline": f"Buy a NIFTY {side} at the open",
            "reason": f"At-the-money weekly option, bought at 09:15, held to the close (exit by 15:15). Stop: if NIFTY "
                      f"moves {STOP_PCT}% against the 09:15 open you get a STOP alert (the level comes after the open). "
                      f"{record}",
            "pred_pct": fo.get("pred_pct")}


TITLES = {"call": "NIFTY: BUY CALL", "put": "NIFTY: BUY PUT", "hold": "NIFTY: STAY in the {side}",
          "sell": "NIFTY: SELL the {side} now", "no_trade": "NIFTY: NOTHING today", "closed": "NIFTY: market closed",
          "test": "NIFTY: test alert", "info": "NIFTY update (info, not a trade signal)",
          "summary": "NIFTY: today's summary", "warning": "NIFTY: NO SIGNAL TODAY",
          "stop": "NIFTY: STOP HIT, SELL the {side} now", "move": "NIFTY: big move (info, not a trade signal)"}
ICONS = {"call": "\U0001F7E2", "put": "\U0001F534", "sell": "\u26A0\uFE0F", "hold": "\u23F3", "test": "\U0001F514",
         "info": "\u2139\uFE0F", "summary": "\U0001F4CA", "warning": "\U0001F6A8", "stop": "\U0001F6A8",
         "move": "\u26A1"}


def _title(status):
    return TITLES.get(status.get("kind", ""), "NIFTY").format(side=status.get("side", ""))


def _body(status):
    return status.get("body") or f"{status['headline']}. {status['reason']}"


def send_ntfy(status, topic, silent=False):
    """BUY / SELL are "urgent" (iOS: time-sensitive). No link: tapping just opens the alert."""
    kind = status.get("kind", "")
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=_body(status).encode(),
                                 headers={"Title": _title(status),
                                          "Priority": "low" if silent else
                                          "urgent" if kind in ("call", "put", "sell", "stop", "test", "warning") else "default",
                                          "Tags": {"call": "green_circle", "put": "red_circle", "sell": "warning", "stop": "rotating_light",
                                                   "hold": "hourglass", "test": "bell"}.get(kind, "white_circle")})
    urllib.request.urlopen(req, timeout=15).read()


def send_telegram(status, token, chat_id, silent=False):
    """silent: delivered without sound or vibration (hourly updates)."""
    icon = ICONS.get(status.get("kind", ""), "\u26AA")
    text = f"{icon} {_title(status)}\n{_body(status)}"
    data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True,
                       "disable_notification": bool(silent)}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                 headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if not out.get("ok"):
        raise RuntimeError(f"telegram: {out.get('description')}")


def channels():
    env = os.environ
    out = []
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        out.append(("telegram", lambda st, q=False: send_telegram(st, env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"], q)))
    if env.get("NTFY_TOPIC"):
        out.append(("ntfy", lambda st, q=False: send_ntfy(st, env["NTFY_TOPIC"], q)))
    return out


def notify(status, silent=False):
    """Send through every configured channel; one failing does not stop the others. Returns {channel: result}."""
    res = {}
    for name, send in channels():
        try:
            send(status, silent)
            res[name] = "sent"
        except Exception as e:
            res[name] = f"failed: {e!r}"
    return res


def changed(prev, new):
    key = lambda s: (s.get("date"), s.get("state"), s.get("kind"))
    return not prev or key(prev) != key(new)


INFO_FROM, INFO_TO = (9, 30), (15, 20)
INFO_GAP_MIN = 55                       # runs come every 10 minutes (27 Oct 2026); the silent update stays about hourly


def _pct(x):
    return f"{x:+.2f}%"


def headlines(news, since=None, n=2):
    """The newest headlines (news-nifty.json), only those first seen after `since` (ISO time) when given."""
    items = sorted((news or {}).get("items") or [], key=lambda x: x.get("seen", ""), reverse=True)
    if since:
        items = [x for x in items if x.get("seen", "") > since]
    return [x["title"].strip() for x in items[:n] if x.get("title")]


def info_update(today, new, news=None, since=None, daylike_line=""):
    """The hourly update during the session (None outside it). daylike_line: daylike.line() for now, if any."""
    i = (today or {}).get("intraday") or {}
    if (today or {}).get("status") != "open" or not i.get("price"):
        return None
    price, move, opn = i["price"], i.get("move_pct"), i.get("open")
    lines = [f"{price:,.2f}" + (f" ({_pct(move)} vs yesterday)" if move is not None else "")
             + (f" · open {opn:,.2f}, {_pct((price / opn - 1) * 100)} since" if opn else "")]
    if i.get("direction"):
        acc = i.get("accuracy")
        hint = "" if acc is None else (f", {round(acc * 100)}% of moves like this held" if acc >= 0.65
                                       else f", {round(acc * 100)}%: too small a move to call")
        lines.append(f"Hourly check: closes {'above' if i['direction'] == 'up' else 'below'} yesterday{hint}")
    trade = ""
    if new.get("kind") == "stop":
        trade = f" (stopped out at -{STOP_PCT:.2f}%)"
    elif new.get("side") and opn:
        trade = f" ({_pct((price / opn - 1) * 100 * (1 if new['side'] == 'CALL' else -1))} for the {new['side']} since the open)"
    lines.append(f"Status: {new['state']}, {new['headline'][0].lower() + new['headline'][1:]}{trade}")
    if daylike_line:
        lines.append(daylike_line)
    news_now = headlines(news, since)
    lines.append("News: " + (" | ".join(news_now) if news_now else "no new headlines"))
    return {"kind": "info", "body": "\n".join(lines)}


def summary(today, new):
    """The day's summary after the close (None until the close is known)."""
    rec = next((r for r in ((today or {}).get("record") or {}).get("recent", []) if r.get("d") == new["date"]), None)
    if not rec or not rec.get("close") or not rec.get("prev_close"):
        return None
    c, pc, o = rec["close"], rec["prev_close"], rec.get("open")
    lines = [f"Closed {c:,.2f} ({_pct((c / pc - 1) * 100)})" + (f" · open {o:,.2f}, {_pct((c / o - 1) * 100)} from the open" if o else "")]
    tick = lambda h: "right" if h else "wrong" if h is not None else "not scored"
    calls = []
    if rec.get("gap"):
        calls.append(f"gap {rec['gap']} ({tick(rec.get('gap_hit'))})")
    if rec.get("close_call"):
        calls.append(f"close {rec['close_call']} ({tick(rec.get('close_hit'))})")
    if calls:
        lines.append("Pre-open calls: " + ", ".join(calls))
    lines.append(f"{new['headline']}. {new['reason']}" if new.get("headline", "").startswith("Closed:") else "No trade today.")
    return {"kind": "summary", "body": "\n".join(lines)}


def trade_box(new, today):
    """The Status page's trade box on a trade day after the open: entry, stop, NIFTY now, the trade so far."""
    i = (today or {}).get("intraday") or {}
    side, opn, price = new.get("side"), i.get("open"), i.get("price")
    if not side or not opn or not price or new.get("kind") not in ("hold", "sell", "stop", "closed"):
        return None
    pct = -STOP_PCT if new.get("kind") == "stop" or (new.get("kind") == "closed" and "stopped" in new.get("headline", "")) \
        else (price / opn - 1) * 100 * (1 if side == "CALL" else -1)
    return {"side": side, "entry": opn, "stop": round(stop_level(side, opn), 2), "price": price, "pct": round(pct, 2)}


def grok_morning(live, day):
    """Grok's morning read for the 08:57 alert (live.py morning), or ''."""
    m = (live or {}).get("morning") if (live or {}).get("date") == day else None
    if not m:
        return ""
    word = {-2: "very bearish", -1: "bearish", 0: "neutral", 1: "bullish", 2: "very bullish"}.get(m.get("score"), "")
    return (f"\n\U0001F916 Grok's morning read (info only, not part of the signal): {m['score']:+d} {word}. "
            + "; ".join(m.get("reasons") or []) + (f". Big event: {m['event']}" if m.get("big_event") and m.get("event") else ""))


def gift_morning(g, day):
    """GIFT Nifty for the 08:57 alert (gift_record.py), or ''. Its own change includes its premium over NIFTY, so only
    the premium-adjusted gap is called NIFTY's expected gap (29 Oct 2026: -0.27% own change, NIFTY opened -0.04%)."""
    if not g or not str(g.get("fetched", "")).startswith(day) or not g.get("price"):
        return ""
    if g.get("gap_pct") is not None:
        return (f"\nGIFT Nifty {g['price']:,.1f} at {str(g.get('quote_time', ''))[-5:]}: points to a NIFTY open "
                f"{g['gap_pct']:+.2f}% from yesterday's close (after its {g['premium']:+.0f}-point premium). Info only.")
    return (f"\nGIFT Nifty {g['price']:,.1f} at {str(g.get('quote_time', ''))[-5:]} ({g.get('change_pct')}% on its own close, "
            "which includes its premium over NIFTY: not NIFTY's gap). Info only.")


def grok_close(live, day):
    """The day's scorecard and Grok's why (live.py close) for the summary, or ''."""
    c = (live or {}).get("card") if (live or {}).get("date") == day else None
    if not c:
        return ""
    parts = []
    if c.get("call_close") is not None:
        parts.append(f"08:57 call: close {c['call_close']:,.2f} ({'right' if c.get('call_right') else 'wrong'} side, "
                     f"{c['call_miss_pct']:.2f}% off)")
    if c.get("runs"):
        parts.append(f"{c['runs']} intraday predictions, {c['avg_miss_pct']:.2f}% off on average"
                     + (f", right side from {c['right_side_since'][11:16]}" if c.get("right_side_since") else ""))
    return ("\n" + "; ".join(parts) if parts else "") + (f"\n\U0001F916 Why (Grok): {c['note']}" if c.get("note") else "")


def journal_row(new, today, alert, extra=None):
    p = (today or {}).get("preopen") or {}
    i = (today or {}).get("intraday") or {}
    calls = {k: {x: (p.get(k) or {}).get(x) for x in ("direction", "pred_pct", "tier", "trade")} for k in ("gap", "close", "from_open")}
    return {"at": new["updated"], "state": new["state"], "kind": new.get("kind"), "side": new.get("side"),
            "headline": new["headline"], "reason": new["reason"], "alert": alert, "calls": calls if p else None,
            "price": i.get("price"), "move_pct": i.get("move_pct"), "hourly_check": i.get("direction"),
            "hourly_accuracy": i.get("accuracy"), **(extra or {})}


def save_journal(store_dir, row, day):
    path = os.path.join(store_dir, "journal", f"{day}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        rows = json.load(open(path))
    except (OSError, ValueError):
        rows = []
    json.dump(rows + [row], open(path, "w"), separators=(",", ":"))
    return rows + [row]


def _daylike(load, today, now):
    """The 'days like today' line (daylike.py) for the hourly update; empty when unavailable."""
    try:
        import daylike
        return daylike.line(daylike.for_today(load("daylike-nifty.json"), today, now))
    except Exception as e:                                   # never stops the update
        print(f"daylike: {e!r}", flush=True)
        return ""


def main(data_dir, now=None, store_dir=None):
    now = now or datetime.now(IST)
    load = lambda name: json.load(open(os.path.join(data_dir, name))) if os.path.exists(os.path.join(data_dir, name)) else None
    prev, today = load("status.json"), load("today-nifty.json")
    new = decide(today, now)
    same_day = prev if prev and prev.get("date") == new["date"] else {}
    for k in ("info_at", "summary_sent"):
        if same_day.get(k):
            new[k] = same_day[k]
    alert, extra = None, {}
    if changed(prev, new):
        new["since"] = new["updated"]
        quiet = new.get("kind") in ("pending", "closed")          # the close gets the summary below instead
        if channels() and not quiet:
            line = (grok_morning(load("live-nifty.json"), new["date"]) + gift_morning(load("gift-nifty.json"), new["date"])
                    if new.get("kind") in ("call", "put", "no_trade") else "")
            alert = notify({**new, "reason": new["reason"] + line})   # never raises: the page update always goes on
            print("alert:", new["state"], alert)
    else:
        new["since"] = prev.get("since", new["updated"])
    if channels() and new.get("kind") == "closed" and (today or {}).get("status") == "closed" and not new.get("summary_sent"):
        msg = summary(today, new)
        if msg:
            msg["body"] += grok_close(load("live-nifty.json"), new["date"])
            extra["summary"] = notify(msg)
            new["summary_sent"] = True
            print("summary:", extra["summary"])
    elif channels() and not alert and INFO_FROM <= _hm(now) < INFO_TO and (
            not new.get("info_at") or now - datetime.fromisoformat(new["info_at"]) >= timedelta(minutes=INFO_GAP_MIN)):
        nx = ((load("live-nifty.json") or {}).get("next") or {}) if (load("live-nifty.json") or {}).get("date") == new["date"] else {}
        nline = (f"Next 10 min (from {nx['at']}): model leans {nx['lean']} ({nx['pts']:+.0f} pts). Info only: "
                 f"{nx['record']['text']}." if nx.get("lean") else "")
        msg = info_update(today, new, load("news-nifty.json"), new.get("info_at"),
                          "\n".join(x for x in (_daylike(load, today, now), nline) if x))
        if msg:
            extra["info"] = notify(msg, silent=True)
            new["info_at"] = now.isoformat(timespec="minutes")
            print("info:", extra["info"])
    if (today or {}).get("next_session"):
        new["next_session"] = today["next_session"]
    box = trade_box(new, today)
    if box:
        new["trade"] = box
    json.dump(new, open(os.path.join(data_dir, "status.json"), "w"), separators=(",", ":"))
    if store_dir:
        rows = save_journal(store_dir, journal_row(new, today, alert, extra), new["date"])
        sent = lambda r: any(v == "sent" for v in (r.get("alert") or r.get("summary") or {}).values())
        today_rows = [{"at": r["at"][11:16], "state": r["state"], "headline": r["headline"], "price": r.get("price"),
                       "move_pct": r.get("move_pct"), "alert": sent(r)} for r in rows]
        json.dump({"date": new["date"], "rows": today_rows},           # the Status page's "Today" timeline
                  open(os.path.join(data_dir, "status-today.json"), "w"), separators=(",", ":"))
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
