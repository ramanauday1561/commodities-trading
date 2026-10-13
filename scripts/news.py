"""Recent news per instrument: GDELT DOC 2.0 API (https://www.gdeltproject.org), with Google News RSS as fallback.
Both are free and need no key.

Writes docs/data/news-<key>.json (headlines shown on the page) and appends one row per day to a history file in the
store, so that once enough days have accumulated the news signal can be backtested before it is ever used in a forecast.
News is deliberately NOT a model input yet.

(NewsMCP was the first choice, but its service was shut down in October 2026: every request returns HTTP 410.)

Usage: python scripts/news.py <data_dir> <store_dir>      (standard library only; failures never break the pipeline)
"""
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

API = os.environ.get("NEWS_API_URL", "https://api.gdeltproject.org/api/v2/doc/doc")
RSS = "https://news.google.com/rss/search"
HOURS = 36
SHOW = 8
HISTORY_DAYS = 2000
BUDGET_S = 120            # whole run; the page keeps the previous news if the API is slow or down
GAP_S = 6                 # GDELT asks for at most one request every 5 seconds
GOOGLE_GAP_S = 2

# Small finance lexicon for a rough headline tone (+ / -). Recorded for later evaluation, not used in forecasts.
POS = {"surge", "surges", "rally", "rallies", "gain", "gains", "rise", "rises", "jump", "jumps", "record", "high", "boost",
       "growth", "beat", "beats", "upgrade", "strong", "recovery", "rebound", "eases", "easing", "cut", "cuts", "deal", "ceasefire"}
NEG = {"fall", "falls", "drop", "drops", "slump", "slumps", "plunge", "plunges", "crash", "loss", "losses", "weak", "fear",
       "fears", "war", "attack", "strike", "strikes", "sanction", "sanctions", "tariff", "tariffs", "recession", "inflation",
       "hike", "hikes", "downgrade", "default", "crisis", "selloff", "sell-off", "tension", "tensions", "conflict"}

_start, _last, _down = time.monotonic(), 0.0, set()


def reset_budget(seconds=None):
    """Start a fresh time budget (and forget failed hosts), e.g. when news is fetched late in a long job."""
    global _start, BUDGET_S
    _start = time.monotonic()
    _down.clear()
    if seconds is not None:
        BUDGET_S = seconds


def _timeout(signum, frame):
    raise TimeoutError("request took too long")


signal.signal(signal.SIGALRM, _timeout)


def fetch(url, tries=2):
    """GET a URL as text. If the network or server fails every attempt, that host is treated as down for the run."""
    global _last
    host = urllib.parse.urlsplit(url).netloc
    for attempt in range(tries):
        left = BUDGET_S - (time.monotonic() - _start)
        if host in _down or left < 5:
            return None
        gap = GAP_S if "gdelt" in host else GOOGLE_GAP_S
        time.sleep(max(0.0, min(gap - (time.monotonic() - _last), left - 5)))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; commodities-trading)"})
            signal.alarm(int(min(30, left)))           # hard limit: urlopen's timeout is per read, not per request
            with urllib.request.urlopen(req, timeout=min(20, left)) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"news: {host} failed ({e}), attempt {attempt + 1}/{tries}", flush=True)
        finally:
            signal.alarm(0)
            _last = time.monotonic()
    _down.add(host)
    return None


def from_gdelt(query):
    # one attempt: GDELT often rate-limits GitHub's shared runner addresses (429), and Google News is the fallback
    body = fetch(f"{API}?" + urllib.parse.urlencode({"query": query, "mode": "artlist", "format": "json", "maxrecords": 75,
                                                     "timespan": f"{HOURS}h", "sort": "datedesc"}), tries=1)
    if body is None:
        return []
    try:
        arts = json.loads(body).get("articles") or []
    except (ValueError, AttributeError):
        arts = []
    if not arts:
        print(f"news: GDELT gave no articles: {body[:200]!r}", flush=True)
    return arts


def from_google(query, window=None):
    """Google News RSS search, over the last HOURS or a (after, before) date window. Titles end in " - Outlet";
    links point to Google's redirect to the article. Returns None if the request failed (not the same as no news)."""
    q = re.sub(r"\s*sourcelang:\w+", "", query)
    q += f" after:{window[0]} before:{window[1]}" if window else f" when:{max(1, HOURS // 24)}d"
    body = fetch(f"{RSS}?" + urllib.parse.urlencode({"q": q, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}))
    if body is None:
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        print(f"news: Google News answer is not RSS: {body[:200]!r}", flush=True)
        return None
    out = []
    for it in root.iter("item"):
        src = it.find("source")
        outlet = (src.text or "").strip() if src is not None else ""
        title = (it.findtext("title") or "").strip()
        if outlet and title.endswith(" - " + outlet):
            title = title[: -len(outlet) - 3]
        try:
            seen = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        except (TypeError, ValueError):
            seen = None
        out.append({"title": title, "url": (it.findtext("link") or "").strip(), "domain": outlet, "seendate": seen})
    return out


def _norm(title):
    return re.sub(r"[^a-z0-9 ]", "", (title or "").lower()).strip()


def tone(text):
    words = re.findall(r"[a-z\-]+", (text or "").lower())
    p, n = sum(w in POS for w in words), sum(w in NEG for w in words)
    return 0.0 if p + n == 0 else round((p - n) / (p + n), 3)


def _iso(seen):
    try:
        return datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def summarize(articles):
    """Group syndicated copies of the same headline; more outlets = more prominent story."""
    stories = {}
    for a in articles:
        url, key = a.get("url") or "", _norm(a.get("title"))
        if not key or not url.startswith(("https://", "http://")):
            continue
        s = stories.setdefault(key, {"title": a["title"].strip()[:200], "url": url, "domain": a.get("domain", ""),
                                     "seen": _iso(a.get("seendate")), "outlets": set(), "tone": tone(a["title"])})
        s["outlets"].add(a.get("domain") or url)
    ranked = sorted(stories.values(), key=lambda s: (len(s["outlets"]), s["seen"] or ""), reverse=True)
    items = [{**{k: v for k, v in s.items() if k != "outlets"}, "sources": len(s["outlets"])} for s in ranked[:SHOW]]
    w = [len(s["outlets"]) for s in ranked]
    feat = {"articles": len(articles), "stories": len(ranked), "sources": sum(w),
            "tone": round(sum(s["tone"] * x for s, x in zip(ranked, w)) / sum(w), 3) if ranked else 0.0}
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
        source, arts = "GDELT", from_gdelt(inst["news"]["query"])
        if not arts:
            source, arts = "Google News", from_google(inst["news"]["query"]) or []
        if not arts:
            print(f"news {inst['key']}: nothing from either source, keeping the previous file", flush=True)
            continue
        items, feat = summarize(arts)
        json.dump({"updated": now.isoformat(timespec="seconds"), "hours": HOURS, "source": source,
                   "stats": feat, "items": items},
                  open(os.path.join(data_dir, f"news-{inst['key']}.json"), "w"), separators=(",", ":"))
        append_history(os.path.join(hist_dir, f"{inst['key']}.json"), now.strftime("%Y-%m-%d"), {**feat, "src": source})
        print(f"news {inst['key']} ({source}): {feat['articles']} articles, {feat['stories']} stories, tone {feat['tone']:+.2f}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
