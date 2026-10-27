"""Replay a finished day as if it were live: every 10 minutes, a prediction of the close from what was known then.

Usage: python scripts/replay.py <data_dir> <store_dir> [YYYY-MM-DD]   (default: today, IST; run after the close)
Asked by the user on 27 Oct 2026: "assume today's data is not available, do the predictions for every 10 minutes
with the news and Grok, and finally analyse with the actual data". At each step 09:25 ... 15:25 only these are used:
  - NIFTY's 5-minute candles that had finished by then (Yahoo), yesterday's close and the 08:57 call (our record)
  - the headlines Google News dated before that moment (searched for the day afterwards, filtered by their time)
  - the AI (grok.py: the key decides xAI Grok or Groq) asked for the close, a direction, a confidence and why
Two plain baselines are scored beside it: "the close = the price now" and "the close ends on the side of yesterday's
close where it trades now" (the hourly check). The AI model's training ends long before this day, so it cannot
know the outcome; headline times come from Google and can be off by a few minutes.
Writes <data_dir>/replay-nifty-<date>.json for the Live page (live.html?replay=<date>).
"""
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import grok
import live

IST = ZoneInfo("Asia/Kolkata")
QUERIES = ["Nifty", "Sensex", "Indian stock market", "Dalal Street"]
MAX_CALLS = 40
GAP_S = 2.5                                   # stay well inside the AI service's per-minute limit


def day_bars(day):
    import pandas as pd
    import yfinance as yf
    raw = yf.download("^NSEI", period="5d", interval="5m", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
    idx = pd.DatetimeIndex(raw.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    return [(t.to_pydatetime(), float(r.Open), float(r.High), float(r.Low), float(r.Close))
            for t, r in zip(idx, raw.itertuples()) if t.tz_convert(IST).date() == day]


def prev_close(day):
    import yfinance as yf
    d = yf.download("^NSEI", period="1mo", interval="1d", auto_adjust=False, progress=False)
    d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    closes = [(i.date(), float(c)) for i, c in d["Close"].dropna().items()]
    return [c for dd, c in closes if dd < day][-1]


def headlines(day):
    """The day's market headlines with their times (from the previous evening to the close)."""
    import news
    news.reset_budget(90)
    seen, out = set(), []
    window = ((day - timedelta(days=1)).isoformat(), (day + timedelta(days=1)).isoformat())
    for q in QUERIES:
        for a in news.from_google(q, window) or []:
            k = news._norm(a["title"])
            t = news._iso(a.get("seendate"))
            if not t or k in seen:
                continue
            seen.add(k)
            out.append({"at": datetime.fromisoformat(t), "title": a["title"], "src": a.get("domain", "")})
    start = datetime.combine(day - timedelta(days=1), datetime.min.time(), IST).replace(hour=15, minute=30)
    end = datetime.combine(day, datetime.min.time(), IST).replace(hour=15, minute=30)
    return sorted((h for h in out if start <= h["at"] <= end), key=lambda h: h["at"])


def step_prompt(day, t, pc, opn, price, hi, lo, closes, call, heads):
    hl = "\n".join(f"- {h['at'].astimezone(IST):%H:%M} IST {h['title']}" for h in heads[-15:]) or "- (none yet)"
    path = ", ".join(f"{c:,.0f}" for c in closes[-8:])
    return (f"It is {t:%H:%M} IST on {day:%d %b %Y}, during the Indian market session (09:15-15:30). You do not know "
            f"anything after {t:%H:%M}.\nNIFTY 50: yesterday's close {pc:,.2f}; opened {opn:,.2f}; now {price:,.2f} "
            f"({(price / pc - 1) * 100:+.2f}%); day's high {hi:,.2f}, low {lo:,.2f}; last 10-minute closes: {path}.\n"
            f"Our models' call at 08:57: {call or 'none'}.\nHeadlines so far today:\n{hl}\n\n"
            "Predict where NIFTY 50 closes today at 15:30. Answer with only a JSON object: {\"close\": number, "
            "\"direction\": \"up\" or \"down\" (vs yesterday's close), \"confidence\": 0-100, \"why\": \"one short sentence\"}")


def summarize(steps, close, pc):
    up = close > pc
    rows = [s for s in steps if s.get("ai_close")]
    if not rows:
        return {"close": close}
    err = lambda k: round(sum(abs(s[k] / close - 1) for s in rows) / len(rows) * 100, 3)
    hit = lambda k: round(sum((s[k] > pc) == up for s in rows) / len(rows), 3)
    return {"close": close, "move_pct": round((close / pc - 1) * 100, 2), "steps": len(rows),
            "ai_avg_miss_pct": err("ai_close"), "now_avg_miss_pct": err("price"),
            "ai_side_right": hit("ai_close"), "now_side_right": hit("price"),
            "ai_closer": sum(abs(s["ai_close"] - close) < abs(s["price"] - close) for s in rows)}


def main(data_dir, store_dir, day=None, ask=None, bars=None, heads=None, pc=None):
    day = day or datetime.now(IST).date()
    ask = ask or grok.ask
    b = bars if bars is not None else day_bars(day)
    if not b:
        print(f"replay: no candles for {day}", flush=True)
        return None
    pc = pc or prev_close(day)
    heads = heads if heads is not None else headlines(day)
    rec = next((r for r in json.load(open(os.path.join(store_dir, "calls", "nifty.json")))
                if r["d"] == day.isoformat()), {}) if os.path.exists(os.path.join(store_dir, "calls", "nifty.json")) else {}
    call = (f"close {rec['close']['direction']} ({rec['close']['pred_pct']:+.2f}%), from-open trade: "
            f"{'yes' if (rec.get('from_open') or {}).get('trade') else 'no'}") if rec.get("close") else None
    ends = [(t.astimezone(IST) + timedelta(minutes=5), o, h, l, c) for t, o, h, l, c in sorted(b)]
    steps, calls = [], 0
    t = datetime.combine(day, datetime.min.time(), IST).replace(hour=9, minute=25)
    last = datetime.combine(day, datetime.min.time(), IST).replace(hour=15, minute=25)
    while t <= last:
        done = [x for x in ends if x[0] <= t]
        if done:
            price, opn = done[-1][4], done[0][1]
            hi, lo = max(x[2] for x in done), min(x[3] for x in done)
            closes = [x[4] for x in done][1::2]                        # roughly one per 10 minutes
            known = [h for h in heads if h["at"] <= t]
            s = {"at": t.isoformat(timespec="minutes"), "time": live.ist_epoch(t), "price": round(price, 2),
                 "heads": len(known), "latest": [h["title"] for h in known[-3:]],
                 "check": "up" if price > pc else "down"}
            if calls < MAX_CALLS:
                calls += 1
                r = grok.json_from(ask(step_prompt(day, t, pc, opn, price, hi, lo, closes, call, known), search=False,
                                       max_tokens=220))
                if r and isinstance(r.get("close"), (int, float)):
                    s.update({"ai_close": round(float(r["close"]), 2), "ai_dir": r.get("direction"),
                              "ai_conf": r.get("confidence"), "why": str(r.get("why") or "")[:240]})
                time.sleep(GAP_S if ask is grok.ask else 0)
            steps.append(s)
        t += timedelta(minutes=10)
    close = ends[-1][4]
    out = {"date": day.isoformat(), "prev_close": round(pc, 2), "call": call, "close": round(close, 2),
           "candles": live.candles10(b), "steps": steps, "summary": summarize(steps, close, pc),
           "headlines": [{"at": h["at"].astimezone(IST).isoformat(timespec="minutes"), "title": h["title"]} for h in heads],
           "made": datetime.now(timezone.utc).isoformat(timespec="minutes"), "ai_calls": calls}
    path = os.path.join(data_dir, f"replay-nifty-{day.isoformat()}.json")
    json.dump(out, open(path, "w"), separators=(",", ":"))
    print("replay", day, json.dumps(out["summary"]), f"headlines {len(heads)}, AI calls {calls}", flush=True)
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None)
