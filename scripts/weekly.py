"""The Saturday summary to the phone (31 Oct 2026, asked by the user): the week in one message.

Usage: python scripts/weekly.py <data_dir> <store_dir>   (every forecast run; sends once a week, on Saturday or Sunday IST)
What it says, all information (no trade signal): NIFTY, gold, silver and crude over the week; how the 08:57 calls did
and any 09:15 trade; the track records (our model and the AI against "the price then", Grok's morning read); the
week on real option prices (an at-the-money CALL and PUT bought at each open); GIFT Nifty's expected open; and next
week's US releases, heavyweight results and the sessions the 09:15 signal stands aside on.
A marker in <store>/weekly/<Monday's date>.txt keeps it to one message a week.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import status
from calendars import next_sessions

IST = ZoneInfo("Asia/Kolkata")
NAMES = {"nifty": "NIFTY 50", "gold": "Gold", "silver": "Silver", "crude": "Crude"}
US = {"fomc": "Fed decision", "cpi": "US inflation (CPI)", "jobs": "US jobs report"}


def _load(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def week_move(candles, monday):
    """(last close, % over the week) from daily candles: the last close before this week to the latest one."""
    before = [c for c in candles if c["time"] < monday.isoformat()]
    this = [c for c in candles if c["time"] >= monday.isoformat()]
    if not before or not this:
        return None
    return this[-1]["close"], (this[-1]["close"] / before[-1]["close"] - 1) * 100


def rs(x):
    return f"{'+' if x > 0 else '-' if x < 0 else ''}Rs{abs(int(x)):,}"


def body(data_dir, store_dir, today, results=None):
    monday = today - timedelta(days=today.weekday())
    lines = []
    moves = []
    for k, name in NAMES.items():
        d = _load(os.path.join(data_dir, f"{k}.json")) or {}
        m = week_move(d.get("candles") or [], monday)
        if m:
            moves.append(f"{name} {m[0]:,.2f} ({m[1]:+.2f}%)")
    if moves:
        lines.append("Week: " + " · ".join(moves))

    t = _load(os.path.join(data_dir, "today-nifty.json")) or {}
    week = [r for r in (t.get("record") or {}).get("recent", []) if r.get("d", "") >= monday.isoformat()]
    if week:
        trades = [r for r in week if r.get("from_open_trade")]
        tr = (f"{len(trades)} trade(s): " + ", ".join(f"{r['d'][5:]} {'CALL' if r.get('from_open_dir') == 'up' else 'PUT'} "
                                                     f"{r['with_stop_pct']:+.2f}%" for r in trades if r.get("with_stop_pct") is not None)
              if trades else "no 09:15 trade")
        lines.append(f"08:57 calls: gap right {sum(bool(r.get('gap_hit')) for r in week)} of {len(week)}, close right "
                     f"{sum(bool(r.get('close_hit')) for r in week)} of {len(week)}; {tr}.")

    try:
        import live
        rec = live.track_record(store_dir)
    except Exception as e:
        print(f"weekly: track record failed: {e!r}", flush=True)
        rec = None
    if rec:
        share = lambda x: f"{x['closer']} of {x['n']}" if x["n"] else "-"
        m = rec["morning"]
        gone = [k for k, v in (rec.get("retired") or {}).items() if v]
        lines.append(f"Track record since {rec['since'][5:]}: nearer the close than 'the price then': model {share(rec['model'])}, "
                     f"AI {share(rec['ai'])}; morning read right {m['right']} of {m['calls']} days"
                     + (f"; retired: {', '.join(gone)}" if gone else "") + ".")

    o = _load(os.path.join(data_dir, "options-nifty.json")) or {}
    od = [x for x in o.get("days", []) if x.get("d", "") >= monday.isoformat()]
    if od:
        tot = lambda k: sum(x[k]["rs"] for x in od if x.get(k))
        app = [x["app"] for x in od if x.get("app")]
        lines.append(f"Real option prices, open to close, a lot ({len(od)} days): an at-the-money CALL every day {rs(tot('call'))}, "
                     f"a PUT {rs(tot('put'))}" + (f"; our trades {rs(sum(a['rs'] for a in app))}" if app else "") + ".")

    g = _load(os.path.join(data_dir, "gift-nifty.json")) or {}
    if g.get("gap_pct") is not None:
        lines.append(f"GIFT Nifty {g['price']:,.1f}: points to a Monday open {g['gap_pct']:+.2f}% from Friday's close "
                     f"(after its {g['premium']:+.0f}-point premium; weekend news can change it).")

    nxt = [d for d in next_sessions(today, 7, "XBOM") if d < monday + timedelta(days=14)][:5]
    n = _load(os.path.join(data_dir, "nifty.json")) or {}
    ev = [(date.fromisoformat(u["date"]), US.get(u["kind"], u["kind"])) for u in (n.get("us_events") or {}).get("upcoming", [])]
    res = [(date.fromisoformat(u["date"]), u["name"]) for u in (results or [])]
    if nxt:
        # the signal stands aside on the session after a release (US news comes after India's close; results too), so
        # Friday's releases matter for Monday and next Friday's for the Monday after
        after = lambda d: next_sessions(d, 1, "XBOM")[0]
        hits = sorted((d, name) for d, name in ev + res if nxt[0] <= after(d) <= after(nxt[-1]))
        aside = sorted({after(d) for d, _ in hits})
        lines.append("Next week: " + (", ".join(f"{d:%a %d %b} {name}" for d, name in hits) if hits else "no US releases or heavyweight results")
                     + (f". The 09:15 signal stands aside on {', '.join(f'{d:%a %d %b}' for d in aside)}." if aside else "."))
    lines.append("Info only, not a trade signal.")
    return "\n".join(lines)


def main(data_dir, store_dir, now=None, results=None):
    now = now or datetime.now(IST)
    today = now.date()
    if today.weekday() < 5:                         # Saturday or Sunday only
        return None
    monday = today - timedelta(days=today.weekday())
    mark = os.path.join(store_dir, "weekly", f"{monday.isoformat()}.txt")
    if os.path.exists(mark) or not status.channels():
        return None
    if results is None:
        try:
            import results_calendar as rc
            results = rc.upcoming(rc.fetch(os.path.join(store_dir, "results", "nifty.json")), today - timedelta(days=3), n=12)
        except Exception as e:
            print(f"weekly: results calendar failed: {e!r}", flush=True)
            results = []
    text = body(data_dir, store_dir, today, results)
    sent = status.notify({"kind": "weekly", "body": text})
    print("weekly:", sent, "\n" + text, flush=True)
    if any(v == "sent" for v in sent.values()):
        os.makedirs(os.path.dirname(mark), exist_ok=True)
        open(mark, "w").write(now.isoformat(timespec="minutes") + "\n")
    return text


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
