"""The live NIFTY chart (docs/live.html): today in 10-minute candles, our prediction at every run, alerts, big moves.

Usage: python scripts/live.py <data_dir> <store_dir> morning|run|close
  morning  (08:40-09:15, before status.py) Grok's read of the overnight news and X: a score from -2 (very bearish)
           to +2 (very bullish), three reasons and a big-event flag. Information only: the 08:57 alert shows it.
  run      (every intraday run, after status.py) adds this run's prediction (where today should close, with the
           likely range, from intraday.py, and the hourly check), rebuilds today's 10-minute candles from 5-minute
           ones, finds big moves (NIFTY 0.4% or more within 20 minutes) and sends each new one to the phone with
           Grok's note on why.
  close    (the post-close run, before status.py) the day's scorecard (how far the 08:57 call and each prediction were
           from the close, from when they stayed on the right side, and how often each line was nearer the close than
           "the close = the price then") and Grok's note on why the day moved.
Every run also publishes the track record over all stored days (track_record): our model and the AI against "the
price then", and Grok's morning read against the day's move (29 Oct 2026, after a day both lines only followed the
price and the bearish morning read met a +1.05% day).
Everything is kept in <store>/live/<date>.json (scoreboard branch) and published as <data_dir>/live-nifty.json.
Times on the chart are IST clock times written as if UTC, as in hourly.py.
"""
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import daymoney
import grok
import status

IST = ZoneInfo("Asia/Kolkata")
MOVE_PCT, MOVE_MIN = 0.4, 20            # a big move: this many % within this many minutes
MOVE_GAP_MIN = 30                       # one note per direction per half hour
OPEN = (9, 15)


def _load(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def ist_epoch(t):
    """An aware time -> seconds of its IST clock time as if UTC (what the chart shows)."""
    t = t.astimezone(IST)
    return int(datetime(t.year, t.month, t.day, t.hour, t.minute, tzinfo=timezone.utc).timestamp())


def candles10(bars):
    """bars: [(aware start time, open, high, low, close)] in 5 minutes, one day -> 10-minute candles from 09:15."""
    out = {}
    for t, o, h, l, c in sorted(bars):
        t = t.astimezone(IST)
        mins = (t.hour * 60 + t.minute) - (OPEN[0] * 60 + OPEN[1])
        if mins < 0:
            continue
        start = t.replace(second=0, microsecond=0) - timedelta(minutes=mins % 10)
        k = ist_epoch(start)
        if k not in out:
            out[k] = {"time": k, "open": o, "high": h, "low": l, "close": c}
        else:
            b = out[k]
            b["high"], b["low"], b["close"] = max(b["high"], h), min(b["low"], l), c
    return [{**b, **{x: round(b[x], 2) for x in ("open", "high", "low", "close")}} for _, b in sorted(out.items())]


def find_moves(bars, known=()):
    """Moves of MOVE_PCT% or more between a 5-minute close and the close MOVE_MIN minutes earlier; at most one per
    direction per MOVE_GAP_MIN minutes. bars as in candles10. Returns all of today's, oldest first."""
    pts = sorted((t.astimezone(IST) + timedelta(minutes=5), c) for t, o, h, l, c in bars)   # close time, close
    moves = list(known)
    for i, (t, c) in enumerate(pts):
        back = [p for p in pts[:i] if t - p[0] <= timedelta(minutes=MOVE_MIN)]
        if not back:
            continue
        t0, c0 = back[0]
        pct = (c / c0 - 1) * 100
        if abs(pct) < MOVE_PCT:
            continue
        d = "up" if pct > 0 else "down"
        if any(m["dir"] == d and abs(t - datetime.fromisoformat(m["at"])) < timedelta(minutes=MOVE_GAP_MIN) for m in moves):
            continue
        moves.append({"at": t.isoformat(timespec="minutes"), "from_at": t0.isoformat(timespec="minutes"), "dir": d,
                      "pct": round(pct, 2), "from": round(c0, 2), "to": round(c, 2)})
    return sorted(moves, key=lambda m: m["at"])


def scorecard(preds, prev_close, close, call_pct=None):
    """How the predictions did once the close is known."""
    if not preds or not prev_close or not close:
        return None
    up = close > prev_close
    miss = [abs(p["pred"] / close - 1) * 100 for p in preds if p.get("pred")]
    side = [(p["at"], (p["pred"] > prev_close) == up) for p in preds if p.get("pred")]
    since = None
    for at, ok in reversed(side):
        if not ok:
            break
        since = at
    out = {"close": close, "move_pct": round((close / prev_close - 1) * 100, 2), "runs": len(miss),
           "avg_miss_pct": round(sum(miss) / len(miss), 2) if miss else None, "right_side_since": since}
    if call_pct is not None:
        target = prev_close * (1 + call_pct / 100)
        out.update({"call_close": round(target, 2), "call_miss_pct": round(abs(target / close - 1) * 100, 2),
                    "call_right": (call_pct > 0) == up})
    return out


def closer(preds, key, close):
    """How often a predicted close (key) was nearer the real close than "the close = the price then", ties left out.
    (29 Oct 2026: the model line was off 0.38% on average, the same as just taking the price then, and nearer in only
    12 of 34 runs; the AI was nearer in 7 of 15. An average miss alone made both look useful.)"""
    rows = [(abs(p[key] - close), abs(p["price"] - close)) for p in preds if p.get(key) and p.get("price")]
    rows = [(a, b) for a, b in rows if round(a, 2) != round(b, 2)]
    return sum(a < b for a, b in rows), len(rows)


def day_record(st):
    """One finished day from its store file: our lines against "the price then", and Grok's morning read."""
    card = (st or {}).get("card") or {}
    close, move = card.get("close"), card.get("move_pct")
    if not close or move is None:
        return None
    preds = st.get("preds", [])
    (mb, mn), (ab, an) = closer(preds, "pred", close), closer(preds, "ai_close", close)
    score = (st.get("morning") or {}).get("score")
    return {"move_pct": move, "model_closer": mb, "model_n": mn, "ai_closer": ab, "ai_n": an, "morning": score,
            "morning_right": None if not score or not move else (score > 0) == (move > 0)}


def track_record(store_dir, keep=20):
    """Every finished day in <store>/live: the last `keep` days and the totals since the first."""
    days = []
    for f in sorted(glob.glob(os.path.join(store_dir, "live", "*.json"))):
        r = day_record(_load(f, {}))
        if r:
            days.append({"d": os.path.basename(f)[:-5], **r})
    if not days:
        return None
    tot = lambda k: sum(x[k] for x in days)
    calls = [x for x in days if x["morning_right"] is not None]
    return {"days": days[-keep:], "since": days[0]["d"],
            "model": {"closer": tot("model_closer"), "n": tot("model_n"), "days": sum(1 for x in days if x["model_n"])},
            "ai": {"closer": tot("ai_closer"), "n": tot("ai_n"), "days": sum(1 for x in days if x["ai_n"])},
            "morning": {"right": sum(x["morning_right"] for x in calls), "calls": len(calls),
                        "neutral": sum(1 for x in days if x["morning"] == 0)}}


def morning_prompt(today, news, record):
    p = (today or {}).get("preopen") or {}
    rows = [f"{r['d']}: gap call {r['gap']} ({'right' if r.get('gap_hit') else 'wrong'}), close call {r['close_call']} "
            f"({'right' if r.get('close_hit') else 'wrong'}), close {r.get('close')}" for r in (record or [])[:8]]
    heads = [x["title"] for x in sorted((news or {}).get("items", []), key=lambda x: x.get("seen", ""), reverse=True)[:12]]
    return ("It is before the 09:15 IST open of the Indian market today. Read the latest news and X posts about NIFTY 50, "
            "its heaviest stocks (HDFC Bank, ICICI Bank, Reliance, Infosys, TCS, Bharti Airtel, L&T, ITC, Kotak, Axis, "
            "SBI), oil, the rupee and global markets overnight.\n"
            f"Overnight moves (%): {json.dumps(p.get('moves_pct', {}))}\n"
            f"Our models' pre-open calls: gap {(p.get('gap') or {}).get('direction')}, close "
            f"{(p.get('close') or {}).get('direction')} ({(p.get('close') or {}).get('pred_pct')}%), heavyweight results "
            f"since the last close: {((p.get('results') or {}).get('since')) or 'none'}\n"
            f"Our recent record:\n" + "\n".join(rows) + "\nRecent headlines we saw:\n- " + "\n- ".join(heads) +
            "\n\nAnswer with only a JSON object: {\"score\": integer from -2 (very bearish) to 2 (very bullish) for "
            "NIFTY today, \"reasons\": [three short reasons], \"big_event\": true or false (a result surprise, policy, "
            "war or similar that can move NIFTY more than 1%), \"event\": \"one line or empty\"}")


def headlines_text(news, n=12):
    items = sorted((news or {}).get("items", []), key=lambda x: x.get("seen", ""), reverse=True)[:n]
    return "\nOur latest headlines (newest first):\n- " + "\n- ".join(f"{x.get('seen', '')[11:16]} UTC {x['title']}" for x in items) if items else ""


def move_prompt(m, today_str, news=None):
    return (f"On {today_str}, NIFTY 50 moved {m['pct']:+.2f}% between {m['from_at'][11:16]} and {m['at'][11:16]} IST "
            f"(from {m['from']:,.2f} to {m['to']:,.2f}). Using news and X posts from today, in at most two short sentences: "
            "what most likely drove this move? If nothing clear, say 'no clear news'." + headlines_text(news))


def close_prompt(card, today_str, moves, morning, news=None):
    mv = "; ".join(f"{m['at'][11:16]} {m['pct']:+.2f}%" for m in moves) or "none"
    return (f"NIFTY 50 closed {today_str} at {card['close']:,.2f} ({card['move_pct']:+.2f}%). Big moves during the day: "
            f"{mv}. The morning read was: {json.dumps(morning or {})}. In at most three short sentences, why did NIFTY "
            "move the way it did today? Use today's news and X posts; say 'no clear news' where unsure." + headlines_text(news))


AI_RUNS = 40                         # AI close predictions a day (one per 10-minute run, 09:25-15:25)


def ai_prompt(day, now, pc, opn, price, hi, lo, closes, call, news=None):
    """The AI's prediction of today's close at this run (same question as replay.py), with our latest headlines."""
    path = ", ".join(f"{c:,.0f}" for c in closes[-8:])
    return (f"It is {now:%H:%M} IST on {day}, during the Indian market session (09:15-15:30). NIFTY 50: yesterday's "
            f"close {pc:,.2f}; opened {opn:,.2f}; now {price:,.2f} ({(price / pc - 1) * 100:+.2f}%); day's high {hi:,.2f}, "
            f"low {lo:,.2f}; last 10-minute closes: {path}. Our models' call at 08:57: {call or 'none'}."
            + headlines_text(news) + "\n\nPredict where NIFTY 50 closes today at 15:30. Answer with only a JSON object: "
            "{\"close\": number, \"direction\": \"up\" or \"down\" (vs yesterday's close), \"confidence\": 0-100, "
            "\"why\": \"one short sentence\"}")


def bars5():
    """Today's 5-minute NIFTY candles [(aware start, o, h, l, c)], or []."""
    import pandas as pd
    import yfinance as yf
    raw = yf.download("^NSEI", period="1d", interval="5m", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    idx = pd.DatetimeIndex(raw.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    today = datetime.now(IST).date()
    return [(t.to_pydatetime(), float(r.Open), float(r.High), float(r.Low), float(r.Close))
            for t, r in zip(idx, raw.itertuples()) if t.tz_convert(IST).date() == today]


def marks(store_dir, day):
    """Alerts and state changes from the day's journal, for the chart."""
    rows, out, last = _load(os.path.join(store_dir, "journal", f"{day}.json"), []), [], None
    for r in rows:
        key = (r.get("state"), r.get("kind"))
        sent = any(v == "sent" for v in (r.get("alert") or {}).values())
        if key != last or sent:
            t = datetime.fromisoformat(r["at"])
            out.append({"at": r["at"], "time": ist_epoch(t), "state": r["state"], "kind": r.get("kind"),
                        "headline": r.get("headline"), "alert": sent})
        last = key
    return [m for m in out if m["kind"] not in ("pending",)]


def _daylike(data_dir, today, now):
    """What NIFTY did from here to the close on past days like today so far (daylike.py), or None."""
    try:
        import daylike
        return daylike.for_today(_load(os.path.join(data_dir, "daylike-nifty.json")), today, now)
    except Exception as e:
        print(f"live: daylike failed: {e!r}", flush=True)
        return None


def _next(data_dir, today, now):
    """The model's lean for the next 10-minute candle (nextcandle.py), information only, or None."""
    if (today or {}).get("status") != "open":
        return None
    try:
        import nextcandle
        return nextcandle.lean(data_dir, now)
    except Exception as e:
        print(f"live: next candle failed: {e!r}", flush=True)
        return None


def main(data_dir, store_dir, mode, now=None, get_bars=bars5):
    now = now or datetime.now(IST)
    day = now.date().isoformat()
    today = _load(os.path.join(data_dir, "today-nifty.json"), {}) or {}
    if today.get("date") != day or today.get("status") == "holiday":
        print("live: no session today", flush=True)
        return None
    path = os.path.join(store_dir, "live", f"{day}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    st = _load(path, {}) or {}
    budget = grok.Budget(st)
    pre = today.get("preopen") or {}
    prev_close = pre.get("prev_close")
    hm = (now.hour, now.minute)

    if mode == "morning" and (8, 40) <= hm < OPEN and not st.get("morning"):
        r = grok.json_from(budget.ask(morning_prompt(today, _load(os.path.join(data_dir, "news-nifty.json")),
                                                     (today.get("record") or {}).get("recent"))))
        if r and isinstance(r.get("score"), (int, float)):
            st["morning"] = {"at": now.isoformat(timespec="minutes"), "score": max(-2, min(2, int(r["score"]))),
                             "reasons": [str(x) for x in (r.get("reasons") or [])][:3],
                             "big_event": bool(r.get("big_event")), "event": str(r.get("event") or "")}

    if mode == "run" and today.get("status") == "open":
        i, n = today.get("intraday") or {}, _load(os.path.join(data_dir, "intraday-nifty.json"), {}) or {}
        if i.get("price"):
            pt = {"at": now.isoformat(timespec="minutes"), "time": ist_epoch(now), "price": i["price"],
                  "pred": n.get("pred_close") or i["price"], "lo": n.get("p10"), "hi": n.get("p90"),
                  "check": i.get("direction"), "check_acc": i.get("accuracy")}
            st["preds"] = [p for p in st.get("preds", []) if p["at"][:16] != pt["at"][:16]] + [pt]
        try:
            b = get_bars()
        except Exception as e:
            print(f"live: 5-minute candles failed: {e!r}", flush=True)
            b = []
        if b:
            st["candles"] = candles10(b)
            last = (st.get("preds") or [None])[-1]
            asked = sum(1 for p in st.get("preds", []) if p.get("ai_asked"))
            if last and last["at"][:16] == now.isoformat(timespec="minutes")[:16] and asked < AI_RUNS and prev_close:
                last["ai_asked"] = True                     # the AI's own prediction of the close, beside our model's
                rc = (pre.get("recorded") or {}).get("close") or {}
                call = f"close {rc.get('direction')} ({rc.get('pred_pct')}%)" if rc else None
                r = grok.json_from(budget.ask(ai_prompt(day, now, prev_close, b[0][1], b[-1][4], max(x[2] for x in b),
                                                        min(x[3] for x in b), [c["close"] for c in st["candles"]], call,
                                                        _load(os.path.join(data_dir, "news-nifty.json"))),
                                              search=False, max_tokens=220))
                if r and isinstance(r.get("close"), (int, float)) and abs(r["close"] / b[-1][4] - 1) < 0.015:
                    last.update({"ai_close": round(float(r["close"]), 2), "ai_conf": r.get("confidence"),
                                 "ai_why": str(r.get("why") or "")[:200]})
            old = {m["at"] for m in st.get("moves", [])}
            moves = find_moves(b, st.get("moves", []))
            for m in moves:
                if m["at"] in old:
                    continue
                fresh = now - datetime.fromisoformat(m["at"]) <= timedelta(minutes=MOVE_MIN + 10)
                if fresh:                                   # older ones (a late or first run) are kept, not alerted
                    m["note"] = budget.ask(move_prompt(m, day, _load(os.path.join(data_dir, "news-nifty.json"))), max_tokens=160)
                    m["alert"] = status.notify({"kind": "move", "body": (
                        f"{'🔻' if m['dir'] == 'down' else '🔺'} NIFTY {m['pct']:+.2f}% in {MOVE_MIN} min "
                        f"({m['from']:,.2f} → {m['to']:,.2f}, {m['from_at'][11:16]}-{m['at'][11:16]})"
                        + (f"\nWhy (Grok): {m['note']}" if m.get("note") else "") + "\nInfo, not a trade signal.")})
            st["moves"] = moves

    if mode == "close" and not st.get("card"):
        rec = next((r for r in (today.get("record") or {}).get("recent", []) if r.get("d") == day), None)
        call_pct = ((pre.get("recorded") or {}).get("close") or {}).get("pred_pct")
        card = scorecard(st.get("preds", []), (rec or {}).get("prev_close") or prev_close, (rec or {}).get("close"), call_pct)
        ai = [p for p in st.get("preds", []) if p.get("ai_close")]
        if card and ai:                                     # the AI's predictions scored the same way as our model's
            pc0 = (rec or {}).get("prev_close") or prev_close
            card["ai_runs"] = len(ai)
            card["ai_avg_miss_pct"] = round(sum(abs(p["ai_close"] / card["close"] - 1) for p in ai) / len(ai) * 100, 2)
            card["ai_side_right"] = round(sum((p["ai_close"] > pc0) == (card["close"] > pc0) for p in ai) / len(ai), 2)
        if card:
            card["model_closer"], card["model_n"] = closer(st.get("preds", []), "pred", card["close"])
            card["ai_closer"], card["ai_n"] = closer(st.get("preds", []), "ai_close", card["close"])
        if not st.get("money"):                              # the "₹2 lakh today" box (daymoney.py)
            try:
                rec_fo = {"from_open": (pre.get("recorded") or {}).get("from_open")}
                st["money"] = daymoney.money(get_bars(), (rec or {}).get("prev_close") or prev_close,
                                             *daymoney.sides(rec_fo))
            except Exception as e:
                print(f"live: money box failed: {e!r}", flush=True)
        if card:
            card["note"] = budget.ask(close_prompt(card, day, st.get("moves", []), st.get("morning"),
                                                   _load(os.path.join(data_dir, "news-nifty.json"))), max_tokens=220)
            st["card"] = card

    if mode == "run":                                       # the next-candle page (next.html), separate from Live
        nx = _next(data_dir, today, now)
        if nx:
            st["leans"] = [x for x in st.get("leans", []) if x["at"] != nx["at"]] + [
                {"made": now.strftime("%H:%M"), **{k: nx[k] for k in ("at", "lean", "pts", "confident")}}]
    json.dump(st, open(path, "w"), separators=(",", ":"))
    meta = _load(os.path.join(data_dir, "nextcandle-meta.json"), {}) or {}
    json.dump({"date": day, "updated": now.isoformat(timespec="minutes"), "status": today.get("status"),
               "prev_close": prev_close, "candles": st.get("candles", []), "leans": st.get("leans", []),
               "record": meta.get("record"), "trained_until": meta.get("trained_until")},
              open(os.path.join(data_dir, "next-nifty.json"), "w"), separators=(",", ":"))
    rc = (pre.get("recorded") or {})
    fo, cl = rc.get("from_open") or {}, rc.get("close") or {}
    i = today.get("intraday") or {}
    side = ("CALL" if fo.get("direction") == "up" else "PUT") if fo.get("trade") else None
    out = {"date": day, "updated": now.isoformat(timespec="minutes"), "status": today.get("status"),
           "prev_close": prev_close, "price": i.get("price"), "move_pct": i.get("move_pct"),
           "call": {"made_at": rc.get("made_at"), "dir": cl.get("direction"), "pred_pct": cl.get("pred_pct"),
                    "target": round(prev_close * (1 + cl["pred_pct"] / 100), 2) if prev_close and cl.get("pred_pct") is not None else None},
           "trade": {"side": side, "entry": i.get("open"), "stop": round(status.stop_level(side, i["open"]), 2)}
                    if side and i.get("open") else None,
           "candles": st.get("candles", []), "preds": st.get("preds", []), "moves": st.get("moves", []),
           "marks": marks(store_dir, day), "morning": st.get("morning"), "card": st.get("card"),
           "money": st.get("money"), "daylike": _daylike(data_dir, today, now), "record": track_record(store_dir)}
    json.dump(out, open(os.path.join(data_dir, "live-nifty.json"), "w"), separators=(",", ":"))
    print(f"live {mode}: {len(out['candles'])} candles, {len(out['preds'])} predictions, {len(out['moves'])} moves, "
          f"grok calls today {st.get('grok_calls', 0)}", flush=True)
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
