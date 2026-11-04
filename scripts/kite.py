"""Zerodha Kite Connect: NIFTY's own 5-minute candles in place of Yahoo's (4 Nov 2026, asked by the user).

Yahoo's 5-minute NIFTY bars freeze from about 15:10 (since Aug 2026; 3 Nov 2026 the chart ended 80 points below the
official close). Kite's market data needs no static IP (that rule covers order placement only, which this app never
does), but its access token lasts one day: someone logs in to Kite once each morning (docs/kite.html), Kite sends a
one-time request_token back to that page, and the "Kite login" workflow trades it for the day's access token with
the API secret. The token is stored encrypted with a key made from the API secret (the kite-session branch is
public), and every 10-minute run decrypts it. With no login that day, the runs use Yahoo as before.

Secrets (GitHub, never in the repo or in logs): KITE_API_KEY, KITE_API_SECRET.
Usage: python scripts/kite.py check                       (are the key and secret accepted? no login needed)
       python scripts/kite.py login <request_token> <dir>  (the workflow; writes <dir>/session.json, status.json)
       python scripts/kite.py test <dir>                    (today's or the last session's candles with the stored token)
"""
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
API = "https://api.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login?v=3&api_key="
NIFTY = 256265                         # NSE:NIFTY 50's instrument token
SESSION, STATUS = "session.json", "status.json"


class KiteError(RuntimeError):
    pass


_LAST = [0.0]


def _req(path, key=None, token=None, data=None, timeout=20):
    """Kite's JSON answer; errors say Kite's error type and message, never a key or token. At most ~3 requests a
    second (Kite's limit for historical candles)."""
    import time as _t
    wait = _LAST[0] + 0.35 - _t.time()
    if wait > 0:
        _t.sleep(wait)
    _LAST[0] = _t.time()
    h = {"X-Kite-Version": "3", "User-Agent": "commodities-trading"}
    if token:
        h["Authorization"] = f"token {key}:{token}"
    body = urllib.parse.urlencode(data).encode() if data else None
    try:
        with urllib.request.urlopen(urllib.request.Request(API + path, data=body, headers=h), timeout=timeout) as f:
            return json.load(f)
    except urllib.error.HTTPError as e:
        try:
            j = json.load(e)
        except Exception:
            j = {}
        raise KiteError(f"HTTP {e.code} {j.get('error_type', '')}: {j.get('message', '')}".strip()) from None


def _fernet(secret):
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("kite-session:" + secret).encode()).digest()))


def expires(now):
    """Kite access tokens end at 06:00 IST the next morning (or this morning, for a login before 06:00)."""
    t = now.replace(hour=6, minute=0, second=0, microsecond=0)
    return t if now < t else t + timedelta(days=1)


def _mask(s):
    if os.environ.get("GITHUB_ACTIONS") and s:
        print(f"::add-mask::{s}", flush=True)


def login(request_token, store_dir, key, secret, now=None, post=_req):
    """Trade the one-time request_token for the day's access token; saved encrypted."""
    now = now or datetime.now(IST)
    _mask(request_token)
    checksum = hashlib.sha256((key + request_token + secret).encode()).hexdigest()
    d = post("/session/token", data={"api_key": key, "request_token": request_token, "checksum": checksum})["data"]
    tok = d["access_token"]
    _mask(tok)
    os.makedirs(store_dir, exist_ok=True)
    until = expires(now).isoformat(timespec="minutes")
    json.dump({"at": now.isoformat(timespec="minutes"), "until": until, "token": _fernet(secret).encrypt(tok.encode()).decode()},
              open(os.path.join(store_dir, SESSION), "w"))
    json.dump({"at": now.isoformat(timespec="minutes"), "until": until}, open(os.path.join(store_dir, STATUS), "w"))
    return tok


def load(store_dir, secret, now=None):
    """The stored access token while it is valid, else None."""
    try:
        s = json.load(open(os.path.join(store_dir, SESSION)))
        if (now or datetime.now(IST)) >= datetime.fromisoformat(s["until"]):
            return None
        tok = _fernet(secret).decrypt(s["token"].encode()).decode()
    except Exception:
        return None
    _mask(tok)
    return tok


def candles(key, token, day, interval="5minute", instrument=NIFTY, get=_req):
    """[(aware start, o, h, l, c)] for one session (the candle still forming included, as Yahoo's)."""
    q = urllib.parse.urlencode({"from": f"{day} 09:15:00", "to": f"{day} 15:30:00"})
    d = get(f"/instruments/historical/{instrument}/{interval}?{q}", key, token)
    return [(datetime.strptime(c[0], "%Y-%m-%dT%H:%M:%S%z").astimezone(IST), float(c[1]), float(c[2]), float(c[3]), float(c[4]))
            for c in d["data"]["candles"]]


_SESSION = {}


def session(now=None):
    """(api_key, access_token) when there is a valid login today, else None (a found login is kept; a missing one is
    looked for again after 5 minutes)."""
    import time as _t
    if _SESSION.get("v") or _t.time() - _SESSION.get("at", 0) < 300:
        return _SESSION.get("v")
    key, secret, d = (os.environ.get(k, "").strip() for k in ("KITE_API_KEY", "KITE_API_SECRET", "KITE_DIR"))
    tok = load(d, secret, now) if key and secret and d else None
    _SESSION.update(v=(key, tok) if tok else None, at=_t.time())
    return _SESSION["v"]


def history(key, token, instrument, interval, start, end, get=_req, max_days=100):
    """[(aware IST start, o, h, l, c, volume)] from start to end (datetimes), in chunks of max_days (Kite's limit per
    request: minute 60, 3/5/10minute 100, 15/30minute 200, 60minute 400, day 2000)."""
    out, a = [], start
    while a <= end:
        b = min(a + timedelta(days=max_days) - timedelta(seconds=1), end)
        q = urllib.parse.urlencode({"from": f"{a:%Y-%m-%d %H:%M:%S}", "to": f"{b:%Y-%m-%d %H:%M:%S}"})
        d = get(f"/instruments/historical/{instrument}/{interval}?{q}", key, token)
        out += [(datetime.strptime(c[0], "%Y-%m-%dT%H:%M:%S%z").astimezone(IST), float(c[1]), float(c[2]), float(c[3]),
                 float(c[4]), float(c[5]) if len(c) > 5 and c[5] is not None else 0.0) for c in d["data"]["candles"]]
        a = b + timedelta(seconds=1)
    return out


def quote(key, token, symbols, get=_req):
    """Kite's full quotes {"NFO:NIFTY...": {...}} for up to 500 instruments ("EXCHANGE:TRADINGSYMBOL")."""
    q = "&".join("i=" + urllib.parse.quote(s) for s in symbols)
    return get(f"/quote?{q}", key, token)["data"]


def instruments(exchange, get=None):
    """Kite's instrument list for one exchange (CSV, refreshed by Kite each morning) as a list of dicts."""
    import csv
    import io
    s = session()
    if not s:
        return []
    h = {"X-Kite-Version": "3", "User-Agent": "commodities-trading", "Authorization": f"token {s[0]}:{s[1]}"}
    with urllib.request.urlopen(urllib.request.Request(f"{API}/instruments/{exchange}", headers=h), timeout=60) as f:
        return list(csv.DictReader(io.StringIO(f.read().decode())))


class Bars(list):
    """Candles that came from Kite: no frozen-feed check (that is Yahoo's fault, live.drop_frozen)."""
    feed = "kite"


def bars5(now=None, get=_req):
    """Today's 5-minute NIFTY candles from Kite, or None (no secrets, no login today, or Kite failed: Yahoo then)."""
    key, secret, d = os.environ.get("KITE_API_KEY"), os.environ.get("KITE_API_SECRET"), os.environ.get("KITE_DIR")
    if not (key and secret and d):
        return None
    now = now or datetime.now(IST)
    tok = load(d, secret, now)
    if not tok:
        print("kite: no login today; using Yahoo", flush=True)
        return None
    try:
        b = candles(key, tok, now.date().isoformat(), get=get)
    except Exception as e:
        print(f"kite: candles failed ({e}); using Yahoo", flush=True)
        return None
    return Bars(b) if b else None


def check(key, secret):
    """Whether Kite accepts the key and the secret, without a login: a made-up request_token is refused either way,
    but Kite says which part it did not accept."""
    print(f"KITE_API_KEY: {'set, ' + str(len(key)) + ' characters' if key else 'MISSING'}; "
          f"KITE_API_SECRET: {'set, ' + str(len(secret)) + ' characters' if secret else 'MISSING'}", flush=True)
    if not (key and secret):
        return False
    try:
        with urllib.request.urlopen(urllib.request.Request(LOGIN + urllib.parse.quote(key),
                                                           headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as f:
            page = f.read().decode("utf-8", "replace")
            code = f.status
    except urllib.error.HTTPError as e:
        page, code = e.read().decode("utf-8", "replace"), e.code
    bad_key = code >= 400 or "invalid" in page.lower() and "api_key" in page.lower()
    print(f"Kite login page for this key: HTTP {code}{' - Kite does not accept this API key' if bad_key else ' (accepted)'}", flush=True)
    fake = "x" * 32
    try:
        _req("/session/token", data={"api_key": key, "request_token": fake,
                                     "checksum": hashlib.sha256((key + fake + secret).encode()).hexdigest()})
        print("session/token: unexpected success", flush=True)
    except KiteError as e:
        print(f"session/token with a made-up request token (refused, as expected): {e}", flush=True)
    return not bad_key


def test(store_dir, key, secret, now=None):
    now = now or datetime.now(IST)
    tok = load(store_dir, secret, now)
    if not tok:
        print("no valid login stored (log in on the Kite page first)", flush=True)
        return False
    for k in range(7):                                   # today, or the last session before it
        day = (now - timedelta(days=k)).date().isoformat()
        b = candles(key, tok, day)
        if b:
            print(f"Kite works: {len(b)} five-minute NIFTY candles on {day}, last {b[-1][0]:%H:%M} close {b[-1][4]:,.2f}", flush=True)
            return True
    print("Kite answered but had no candles in the last week", flush=True)
    return False


if __name__ == "__main__":
    key, secret = os.environ.get("KITE_API_KEY", "").strip(), os.environ.get("KITE_API_SECRET", "").strip()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        sys.exit(0 if check(key, secret) else 1)
    if cmd == "login":
        login(sys.argv[2].strip(), sys.argv[3], key, secret)
        print("Kite login saved; valid until", json.load(open(os.path.join(sys.argv[3], STATUS)))["until"], flush=True)
        test(sys.argv[3], key, secret)
    if cmd == "test":
        sys.exit(0 if test(sys.argv[2], key, secret) else 1)
