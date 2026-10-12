"""Recent news per instrument from NewsMCP (https://github.com/pranciskus/newsmcp, REST API https://newsmcp.io/v1).

Writes docs/data/news-<key>.json (headlines shown on the page) and appends one row per day to a history file in the
store, so that once enough days have accumulated the news signal can be backtested before it is ever used in a forecast.
NewsMCP has no historical archive, so it cannot be tested on the past and is deliberately NOT a model input yet.

Usage: python scripts/news.py <data_dir> <store_dir>      (standard library only; failures never break the pipeline)
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = os.environ.get("NEWS_API_BASE_URL", "https://newsmcp.io/v1").rstrip("/")
HOURS = 36
SHOW = 8
HISTORY_DAYS = 2000

# Small finance lexicon for a rough headline tone (+ / -). Recorded for later evaluation, not used in forecasts.
POS = {"surge", "surges", "rally", "rallies", "gain", "gains", "rise", "rises", "jump", "jumps", "record", "high", "boost",
       "growth", "beat", "beats", "upgrade", "strong", "recovery", "rebound", "eases", "easing", "cut", "cuts", "deal", "ceasefire"}
NEG = {"fall", "falls", "drop", "drops", "slump", "slumps", "plunge", "plunges", "crash", "loss", "losses", "weak", "fear",
       "fears", "war", "attack", "strike", "strikes", "sanction", "sanctions", "tariff", "tariffs", "recession", "inflation",
       "hike", "hikes", "downgrade", "default", "crisis", "selloff", "sell-off", "tension", "tensions", "conflict"}


def get(path, params, tries=3):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "commodities-trading"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            print(f"news: {url} failed ({e}), attempt {attempt + 1}/{tries}")
            time.sleep(3 * (attempt + 1))
    return None


def fetch_events(cfg):
    """Events for the configured topics/regions, merged and de-duplicated by id."""
    events = {}
    queries = [{"topics": t} for t in cfg.get("topics", ["economy"])] + [{"geo": g} for g in cfg.get("geo", [])]
    for q in queries:
        d = get("news/", {**q, "hours": HOURS, "per_page": 50, "order_by": "-impact_score"})
        for ev in (d or {}).get("events", []):
            events.setdefault(ev.get("id"), ev)
    return list(events.values())


def text_of(ev):
    titles = " ".join((e.get("title") or "") for e in ev.get("entries") or [])
    return f"{ev.get('summary') or ''} {titles}".lower()


def relevant(ev, cfg):
    """An event counts if it mentions an instrument keyword, or (for regional instruments) is tagged with the region."""
    txt = text_of(ev)
    if any(re.search(r"\b" + re.escape(k.lower()) + r"\b", txt) for k in cfg.get("keywords", [])):
        return True
    geo = {g.lower() for g in ev.get("geo") or []}
    return bool(geo & {g.lower().replace("-", " ") for g in cfg.get("geo", [])}) and "economy" in (ev.get("topics") or [])


def tone(ev):
    words = re.findall(r"[a-z\-]+", text_of(ev))
    p, n = sum(w in POS for w in words), sum(w in NEG for w in words)
    return 0.0 if p + n == 0 else round((p - n) / (p + n), 3)


def summarize(events, cfg):
    rel = [ev for ev in events if relevant(ev, cfg)]
    rel.sort(key=lambda e: (e.get("impact_score") or 0, e.get("sources_count") or 0), reverse=True)
    items = []
    for ev in rel[:SHOW]:
        entries = [e for e in ev.get("entries") or [] if (e.get("url") or "").startswith(("https://", "http://"))]
        items.append({"summary": (ev.get("summary") or "").strip()[:400], "impact": ev.get("impact_score"),
                      "sources": ev.get("sources_count"), "topics": ev.get("topics") or [],
                      "last_seen": ev.get("last_seen_at"), "tone": tone(ev),
                      "links": [{"title": (e.get("title") or e["domain"])[:160], "url": e["url"], "domain": e.get("domain", "")}
                                for e in entries[:3]]})
    w = [(ev.get("sources_count") or 1) for ev in rel]
    feat = {"events": len(rel), "sources": sum(w), "max_impact": max([ev.get("impact_score") or 0 for ev in rel], default=0),
            "tone": round(sum(tone(ev) * x for ev, x in zip(rel, w)) / sum(w), 3) if rel else 0.0}
    return items, feat


def append_history(path, day, feat):
    hist = json.load(open(path)) if os.path.exists(path) else []
    hist = [h for h in hist if h["d"] != day] + [{"d": day, **feat}]
    json.dump(hist[-HISTORY_DAYS:], open(path, "w"), separators=(",", ":"))


def main(data_dir, store_dir):
    insts = [i for i in json.load(open("scripts/instruments.json")) if i.get("news")]
    hist_dir = os.path.join(store_dir, "news")
    os.makedirs(hist_dir, exist_ok=True)
    now = datetime.now(timezone.utc)
    for inst in insts:
        events = fetch_events(inst["news"])
        if not events:
            print(f"news {inst['key']}: no data from the API, keeping the previous file")
            continue
        items, feat = summarize(events, inst["news"])
        json.dump({"updated": now.isoformat(timespec="seconds"), "hours": HOURS, "source": "NewsMCP (newsmcp.io)",
                   "stats": feat, "items": items},
                  open(os.path.join(data_dir, f"news-{inst['key']}.json"), "w"), separators=(",", ":"))
        append_history(os.path.join(hist_dir, f"{inst['key']}.json"), now.strftime("%Y-%m-%d"), feat)
        print(f"news {inst['key']}: {len(events)} events fetched, {feat['events']} relevant, tone {feat['tone']:+.2f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
