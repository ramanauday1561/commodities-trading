"""Grok (xAI) for notes that explain the market: the morning read, why a big move happened, why the day moved.

Information only (27 Oct 2026): Grok has read the news about past days, so its views cannot be backtested on
history (it would "know" what happened). Its notes are saved every day (store/live/<date>.json) and can be tested
honestly once a few months of them exist; until then they never change CALL / PUT / NOTHING.

The key comes only from the XAI_API_KEY secret (never in the repo or the logs). Every call is counted per day and
stops at DAILY_CAP. Any failure returns None and the caller carries on without the note.
Usage: python scripts/grok.py test   (one short call, to check the key; workflow "Grok test")
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

URL = "https://api.x.ai/v1/chat/completions"
MODELS = [m for m in (os.environ.get("GROK_MODEL"), "grok-4-latest", "grok-4", "grok-3-latest") if m]
DAILY_CAP = 20
SYSTEM = ("You help a retail trader understand NIFTY 50 (India's main stock index) during the trading day. Be factual "
          "and brief; say 'no clear news' when you are not sure. Never give investment advice or a trade instruction.")


def _post(body, key):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=90).read())


def ask(prompt, search=True, max_tokens=400):
    """Grok's answer as text, or None (no key, an error, or nothing usable). With search, Grok may look at live news
    and X; if the API refuses that option the call is repeated without it."""
    key = os.environ.get("XAI_API_KEY")
    if not key:
        return None
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    for model in MODELS:
        for live in ((True, False) if search else (False,)):
            body = {"model": model, "messages": msgs, "temperature": 0.2, "max_tokens": max_tokens}
            if live:
                body["search_parameters"] = {"mode": "auto", "max_search_results": 10}
            try:
                out = _post(body, key)
                text = (out.get("choices") or [{}])[0].get("message", {}).get("content")
                if text:
                    return text.strip()
            except urllib.error.HTTPError as e:
                print(f"grok {model}{' +search' if live else ''}: HTTP {e.code}", flush=True)   # never the body
                if e.code in (401, 403, 429):
                    return None                     # bad key, no access or rate limit: trying more will not help
            except Exception as e:
                print(f"grok {model}: {type(e).__name__}", flush=True)
                return None
    return None


def json_from(text):
    """The first {...} object in Grok's answer, or None."""
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


class Budget:
    """Calls made today, kept in the day's live state; ask() through here stops at DAILY_CAP."""

    def __init__(self, state):
        self.state = state

    def ask(self, prompt, **kw):
        if self.state.get("grok_calls", 0) >= DAILY_CAP:
            print("grok: daily cap reached", flush=True)
            return None
        self.state["grok_calls"] = self.state.get("grok_calls", 0) + 1
        return ask(prompt, **kw)


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        r = ask("In one short sentence: what is NIFTY 50?", search=False, max_tokens=60)
        print("grok test:", "OK, " + r[:120] if r else "FAILED (is the XAI_API_KEY secret set?)")
        sys.exit(0 if r else 1)
