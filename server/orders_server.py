"""Order server for your own NIFTY option picks (5 Nov 2026, asked by the user). Runs on a small server with a static
IP (server/setup.sh: a DigitalOcean droplet in Bangalore since 10 Nov 2026), because since 1 April 2026 Zerodha accepts orders through the
Kite Connect API only from a static IP whitelisted in the Kite developer console. Market data needs no static IP and
stays on GitHub Actions; the website stays on GitHub Pages.

What it does: you enter a pick on the phone (docs/orders.html): the option, the lots, the entry (now, or a limit
price), a stop-loss price, an optional target and a time to be out by. From then on the server runs it by itself:
  1. entry: a LIMIT buy (a "now" entry is priced a little above the best ask and re-priced up to 3 times, then
     cancelled if still not filled: never a MARKET order, so a thin book cannot fill it at any price);
  2. as soon as it fills, a stop-loss order is placed at the exchange (SL: trigger at your stop, limit a few % under
     it), so the stop holds even if this server goes down;
  3. it watches the price every 2 seconds: at your target, or at your exit time, it cancels the stop order and sells
     with a LIMIT order a little under the best bid (re-priced until filled);
  4. a stop order that triggered but did not fill within 10 seconds is re-priced under the bid.
Hard limits, set on the server only (/etc/nifty-orders.env, not from the phone): MAX_LOTS a pick, MAX_OPEN picks at
once, MAX_LOSS_DAY rupees: when today's realised plus open loss reaches it, everything is sold and no new pick is taken
until tomorrow. "Stop everything" on the phone does the same at once. Buying NIFTY options only (the most a pick can
lose is what it paid); intraday (MIS), so Zerodha also squares off anything left at about 15:20.

Privacy: the picks, orders and P&L stay on this server (its own disk) and your phone; nothing is written to the
repository or printed with prices in the logs. The phone talks to the server over HTTPS (Caddy, a certificate for
<ip>.sslip.io) with a long passcode made at setup; 10 wrong passcodes in an hour lock the API for an hour.
The day's Kite access token comes from the morning login as before (the kite-session branch, encrypted with the API
secret, which this server also holds).

Usage: python3 server/orders_server.py            (systemd runs it; settings from the environment, see setup.sh)
"""
import hmac
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import kite  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
API = "https://api.kite.trade"
TICK, TAG = 0.05, "niftyapp"
OPEN_T, LAST_ENTRY_T, LAST_EXIT_T = "09:15", "15:00", "15:15"
ENTRY_TRIES, ENTRY_WAIT, EXIT_WAIT, SL_WAIT = 3, 15, 5, 10       # re-prices; seconds between them
SESSION_URL = "https://raw.githubusercontent.com/ramanauday1561/commodities-trading/kite-session/session.json"


def up(x):
    """Price rounded up to the tick."""
    return round(-(-round(x / TICK, 6) // 1) * TICK, 2)


def down(x):
    return max(TICK, round((round(x / TICK, 6) // 1) * TICK, 2))


def hm(now):
    return now.strftime("%H:%M")


class KiteError(RuntimeError):
    pass


class Kite:
    """The few Kite Connect calls the server needs (orders, quotes, instruments)."""

    def __init__(self, key, token):
        self.key, self.token = key, token

    def _call(self, method, path, data=None, raw=False):
        h = {"X-Kite-Version": "3", "User-Agent": "nifty-orders", "Authorization": f"token {self.key}:{self.token}"}
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        try:
            with urllib.request.urlopen(urllib.request.Request(API + path, data=body, headers=h, method=method), timeout=15) as f:
                return f.read().decode() if raw else json.load(f)["data"]
        except urllib.error.HTTPError as e:
            try:
                j = json.load(e)
            except Exception:
                j = {}
            raise KiteError(f"{j.get('error_type', 'HTTP ' + str(e.code))}: {j.get('message', '')}".strip()) from None

    def place(self, symbol, side, qty, order_type, price, trigger=None):
        d = {"exchange": "NFO", "tradingsymbol": symbol, "transaction_type": side, "quantity": qty, "product": "MIS",
             "order_type": order_type, "price": f"{price:.2f}", "validity": "DAY", "tag": TAG}
        if trigger is not None:
            d["trigger_price"] = f"{trigger:.2f}"
        return self._call("POST", "/orders/regular", d)["order_id"]

    def modify(self, order_id, price, order_type="LIMIT"):
        self._call("PUT", f"/orders/regular/{order_id}", {"order_type": order_type, "price": f"{price:.2f}"})

    def cancel(self, order_id):
        self._call("DELETE", f"/orders/regular/{order_id}")

    def orders(self):
        """{order_id: {status, filled_quantity, average_price, status_message}} for today."""
        return {o["order_id"]: o for o in self._call("GET", "/orders")}

    def quote(self, symbols):
        q = "&".join("i=" + urllib.parse.quote(s) for s in symbols)
        return self._call("GET", f"/quote?{q}")

    def instruments(self):
        import csv
        import io
        return list(csv.DictReader(io.StringIO(self._call("GET", "/instruments/NFO", raw=True))))


def best(q):
    """(ltp, bid, ask) from a full quote."""
    d = q.get("depth") or {}
    bid = next((x["price"] for x in d.get("buy", []) if x.get("price")), None)
    ask = next((x["price"] for x in d.get("sell", []) if x.get("price")), None)
    return q.get("last_price"), bid, ask


class Engine:
    """Your picks and the orders for them. One lock; the HTTP threads and the 2-second loop both use it."""

    def __init__(self, state_path, limits, now=None, clock=time.time):
        self.path, self.limits = state_path, limits
        self.now = now or (lambda: datetime.now(IST))
        self.clock = clock
        self.lock = threading.RLock()
        self.kite, self.contracts, self.contracts_day = None, {}, None
        self.state = {"day": None, "locked": None, "trades": []}
        try:
            self.state.update(json.load(open(state_path)))
        except (OSError, ValueError):
            pass
        self._new_day()

    # ------------------------------------------------------------------ state
    def _new_day(self):
        today = self.now().date().isoformat()
        if self.state.get("day") != today:
            for t in self.state["trades"]:                    # MIS: Zerodha squared off anything left yesterday
                if t["status"] in ("entering", "open", "exiting"):
                    print(f"pick {t['id']} was still {t['status']} at the end of {self.state.get('day')}: check Kite", flush=True)
            self.state = {"day": today, "locked": None, "trades": []}
            self.save()

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.path)

    def log(self, t, msg):
        t.setdefault("log", []).append(f"{hm(self.now())} {msg}")

    def lot_size(self, symbol):
        return int(self.contracts.get(symbol, {}).get("lot_size") or 0)

    def load_contracts(self):
        today = self.now().date().isoformat()
        if self.kite and self.contracts_day != today:
            self.contracts = {r["tradingsymbol"]: r for r in self.kite.instruments()
                              if r.get("name") == "NIFTY" and r.get("segment") == "NFO-OPT" and r.get("expiry", "") >= today}
            self.contracts_day = today

    # ------------------------------------------------------------------ the phone's requests
    def view(self):
        with self.lock:
            open_loss = sum(self._pnl(t) for t in self.state["trades"])
            return {"day": self.state["day"], "now": self.now().isoformat(timespec="seconds"), "kite": bool(self.kite),
                    "locked": self.state["locked"], "limits": self.limits, "day_pnl": round(open_loss),
                    "trades": [{k: v for k, v in t.items() if k not in ("entry_id", "sl_id", "exit_id")} for t in self.state["trades"]]}

    def add(self, req):
        with self.lock:
            self._new_day()
            now, L = self.now(), self.limits
            sym = str(req.get("symbol", "")).strip().upper()
            try:
                lots = int(req.get("lots", 0))
                stop = float(req["stop"])
                limit = float(req["limit"]) if req.get("limit") not in (None, "") else None
                target = float(req["target"]) if req.get("target") not in (None, "") else None
            except (KeyError, TypeError, ValueError):
                raise ValueError("lots, stop, limit and target must be numbers; a stop is required")
            exit_by = str(req.get("exit_by") or "15:10")[:5]
            if not self.kite:
                raise ValueError("no Kite login today: log in on the Kite page first")
            if self.state["locked"]:
                raise ValueError(f"locked for today: {self.state['locked']}")
            if not (OPEN_T <= hm(now) < LAST_ENTRY_T) or now.weekday() >= 5:
                raise ValueError(f"picks are taken from {OPEN_T} to {LAST_ENTRY_T} on market days")
            self.load_contracts()
            if sym not in self.contracts:
                raise ValueError(f"{sym or 'the option'} is not a NIFTY option trading today")
            if not 1 <= lots <= L["max_lots"]:
                raise ValueError(f"lots must be 1 to {L['max_lots']} (MAX_LOTS on the server)")
            live = [t for t in self.state["trades"] if t["status"] in ("entering", "open", "exiting")]
            if len(live) >= L["max_open"]:
                raise ValueError(f"already {len(live)} open picks (MAX_OPEN {L['max_open']})")
            if not (hm(now) < exit_by <= LAST_EXIT_T):
                raise ValueError(f"the exit time must be after now and no later than {LAST_EXIT_T}")
            q = self.kite.quote([f"NFO:{sym}"]).get(f"NFO:{sym}", {})
            ltp, bid, ask = best(q)
            ref = limit or ask or ltp
            if not ref:
                raise ValueError("no price for that option right now")
            if not 0 < stop < ref:
                raise ValueError(f"the stop must be below the entry price ({ref})")
            if target is not None and target <= ref:
                raise ValueError(f"the target must be above the entry price ({ref})")
            qty = lots * self.lot_size(sym)
            if qty <= 0:
                raise ValueError("no lot size for that option")
            risk = (ref - stop) * qty
            if risk > L["max_loss_day"] + self._pnl_today():
                raise ValueError(f"this pick could lose about Rs{risk:,.0f}, more than what is left of today's limit")
            price = up(limit) if limit else up(ask * 1.01 if ask else ltp * 1.02)
            t = {"id": uuid.uuid4().hex[:8], "symbol": sym, "lots": lots, "qty": qty, "limit": limit, "stop": stop,
                 "target": target, "exit_by": exit_by, "status": "entering", "made": now.isoformat(timespec="seconds"),
                 "entry_price": price, "tries": 0, "since": self.clock(), "filled": 0, "avg_in": None, "avg_out": None,
                 "ltp": ltp, "why": None}
            try:
                t["entry_id"] = self.kite.place(sym, "BUY", qty, "LIMIT", price)
            except KiteError as e:
                raise ValueError(f"Kite refused the order: {e}")
            self.log(t, f"buy {qty} limit {price}")
            self.state["trades"].append(t)
            self.save()
            return t["id"]

    def exit(self, tid, why="exit from the phone"):
        with self.lock:
            t = next((x for x in self.state["trades"] if x["id"] == tid), None)
            if not t:
                raise ValueError("no such pick")
            self._exit(t, why)
            self.save()

    def stop_all(self, why="stop everything from the phone"):
        with self.lock:
            self.state["locked"] = why
            for t in self.state["trades"]:
                if t["status"] in ("entering", "open"):
                    self._exit(t, why)
            self.save()

    # ------------------------------------------------------------------ the 2-second loop
    def tick(self):
        with self.lock:
            self._new_day()
            live = [t for t in self.state["trades"] if t["status"] in ("entering", "open", "exiting")]
            if not live or not self.kite:
                return
            orders = self.kite.orders()
            quotes = self.kite.quote([f"NFO:{s}" for s in {t["symbol"] for t in live}])
            for t in live:
                ltp, bid, ask = best(quotes.get(f"NFO:{t['symbol']}", {}))
                t["ltp"], t["bid"], t["ask"] = ltp, bid, ask
                try:
                    getattr(self, "_" + t["status"])(t, orders, ltp, bid, ask)
                except KiteError as e:
                    self.log(t, f"Kite: {e}")
            if self.state["locked"] is None and self._pnl_today() <= -self.limits["max_loss_day"]:
                self.state["locked"] = f"today's loss reached Rs{self.limits['max_loss_day']:,} (MAX_LOSS_DAY)"
                for t in self.state["trades"]:
                    if t["status"] in ("entering", "open"):
                        self._exit(t, self.state["locked"])
            self.save()

    def _entering(self, t, orders, ltp, bid, ask):
        o = orders.get(t["entry_id"], {})
        st = o.get("status")
        if st == "COMPLETE":
            t["filled"], t["avg_in"] = int(o["filled_quantity"]), float(o["average_price"])
            self.log(t, f"bought {t['filled']} at {t['avg_in']}")
            return self._protect(t)
        if st in ("REJECTED", "CANCELLED"):
            filled = int(o.get("filled_quantity") or 0)
            if filled:                                              # part filled, rest cancelled: keep what we have
                t["filled"], t["avg_in"] = filled, float(o["average_price"])
                return self._protect(t)
            t["status"], t["why"] = "not entered", o.get("status_message") or st.lower()
            return self.log(t, f"entry {st.lower()}: {t['why']}")
        if hm(self.now()) >= t["exit_by"]:
            return self._exit(t, "exit time reached before the entry filled")
        if t["limit"] is None and self.clock() - t["since"] >= ENTRY_WAIT:
            if t["tries"] >= ENTRY_TRIES:
                self._cancel_entry(t)
                t["status"], t["why"] = "not entered", "not filled after re-pricing; cancelled"
                return
            t["tries"] += 1
            t["entry_price"], t["since"] = up((ask or ltp) * 1.01), self.clock()
            self.kite.modify(t["entry_id"], t["entry_price"])
            self.log(t, f"re-priced the buy to {t['entry_price']}")

    def _protect(self, t):
        trig = down(t["stop"])
        price = down(trig - max(1.0, trig * 0.05))
        t["sl_id"] = self.kite.place(t["symbol"], "SELL", t["filled"], "SL", price, trigger=trig)
        t["status"], t["since"] = "open", self.clock()
        self.log(t, f"stop-loss at the exchange: trigger {trig}, limit {price}")

    def _open(self, t, orders, ltp, bid, ask):
        o = orders.get(t.get("sl_id"), {})
        st = o.get("status")
        if st == "COMPLETE":
            return self._closed(t, float(o["average_price"]), "stopped out")
        if st in ("REJECTED", "CANCELLED"):                          # no stop at the exchange any more: get out
            self.log(t, f"the stop order was {st.lower()}: {o.get('status_message') or ''}")
            t["sl_id"] = None
            return self._exit(t, "stop order rejected; sold")
        if st == "OPEN":                                             # triggered, limit not reached
            if self.clock() - t.setdefault("sl_seen", self.clock()) >= SL_WAIT and bid:
                self.kite.modify(t["sl_id"], down(bid * 0.99))
                t["sl_seen"] = self.clock()
                self.log(t, f"the stop triggered; re-priced to {down(bid * 0.99)}")
            return
        if t["target"] is not None and ltp is not None and ltp >= t["target"]:
            return self._exit(t, "target reached")
        if hm(self.now()) >= t["exit_by"]:
            return self._exit(t, "exit time")

    def _exiting(self, t, orders, ltp, bid, ask):
        o = orders.get(t.get("exit_id"), {})
        st = o.get("status")
        if st == "COMPLETE":
            return self._closed(t, float(o["average_price"]), t["why"])
        if st in ("REJECTED", "CANCELLED"):
            self.log(t, f"the sell was {st.lower()}: {o.get('status_message') or ''}; trying again")
            return self._sell(t, ltp, bid)
        if self.clock() - t["since"] >= EXIT_WAIT and (bid or ltp):
            p = down((bid or ltp) * 0.98)
            self.kite.modify(t["exit_id"], p)
            t["since"] = self.clock()
            self.log(t, f"re-priced the sell to {p}")

    def _exit(self, t, why):
        t["why"] = why
        if t["status"] == "entering":
            self._cancel_entry(t)
            o = self.kite.orders().get(t["entry_id"], {})
            filled = int(o.get("filled_quantity") or 0)
            if not filled:
                t["status"] = "not entered"
                return self.log(t, f"entry cancelled: {why}")
            t["filled"], t["avg_in"] = filled, float(o["average_price"])
        elif t["status"] != "open":
            return
        if t.get("sl_id"):
            try:
                self.kite.cancel(t["sl_id"])
            except KiteError:                                          # it may have just filled
                o = self.kite.orders().get(t["sl_id"], {})
                if o.get("status") == "COMPLETE":
                    return self._closed(t, float(o["average_price"]), "stopped out")
        q = self.kite.quote([f"NFO:{t['symbol']}"]).get(f"NFO:{t['symbol']}", {})
        ltp, bid, _ = best(q)
        self._sell(t, ltp, bid)
        self.log(t, f"selling: {why}")

    def _sell(self, t, ltp, bid):
        p = down((bid or ltp or t["avg_in"]) * 0.98)
        t["exit_id"] = self.kite.place(t["symbol"], "SELL", t["filled"], "LIMIT", p)
        t["status"], t["since"] = "exiting", self.clock()

    def _cancel_entry(self, t):
        try:
            self.kite.cancel(t["entry_id"])
        except KiteError:
            pass

    def _closed(self, t, avg_out, why):
        t["status"], t["avg_out"], t["why"] = "closed", avg_out, why
        t["pnl"] = round((avg_out - t["avg_in"]) * t["filled"])
        self.log(t, f"sold {t['filled']} at {avg_out}: {why}")

    def _pnl(self, t):
        """Rupees before charges: closed at the sale price, open at the last price."""
        if t.get("pnl") is not None:
            return t["pnl"]
        if t["status"] in ("open", "exiting") and t.get("avg_in") and t.get("ltp"):
            return (t["ltp"] - t["avg_in"]) * t["filled"]
        return 0

    def _pnl_today(self):
        return sum(self._pnl(t) for t in self.state["trades"] if t["made"][:10] == self.state["day"])

    # ------------------------------------------------------------------ the option list for the phone
    def chain(self, expiry=None, width=8):
        with self.lock:
            if not self.kite:
                raise ValueError("no Kite login today")
            self.load_contracts()
            exps = sorted({r["expiry"] for r in self.contracts.values()})[:3]
            exp = expiry if expiry in exps else (exps[0] if exps else None)
            spot = self.kite.quote(["NSE:NIFTY 50"]).get("NSE:NIFTY 50", {}).get("last_price")
            rows = [r for r in self.contracts.values() if r["expiry"] == exp]
            strikes = sorted({float(r["strike"]) for r in rows}, key=lambda k: abs(k - (spot or 0)))[:2 * width + 1]
            pick = sorted((r for r in rows if float(r["strike"]) in strikes), key=lambda r: (float(r["strike"]), r["instrument_type"]))
            q = self.kite.quote([f"NFO:{r['tradingsymbol']}" for r in pick]) if pick else {}
            return {"expiries": exps, "expiry": exp, "spot": spot, "lot": int(pick[0]["lot_size"]) if pick else None,
                    "options": [{"symbol": r["tradingsymbol"], "strike": float(r["strike"]), "type": r["instrument_type"],
                                 "ltp": q.get(f"NFO:{r['tradingsymbol']}", {}).get("last_price")} for r in pick]}


class Session:
    """The day's access token from the morning Kite login (the kite-session branch), checked every minute until found."""

    def __init__(self, engine, key, secret, store, fetch=None):
        self.engine, self.key, self.secret, self.store = engine, key, secret, store
        self.fetch = fetch or (lambda: urllib.request.urlopen(SESSION_URL, timeout=15).read())
        self.checked = 0

    def refresh(self):
        tok = kite.load(self.store, self.secret, self.engine.now())
        if not tok and time.time() - self.checked >= 60:
            self.checked = time.time()
            try:
                os.makedirs(self.store, exist_ok=True)
                with open(os.path.join(self.store, kite.SESSION), "wb") as f:
                    f.write(self.fetch())
                tok = kite.load(self.store, self.secret, self.engine.now())
            except Exception as e:
                print(f"kite session: {type(e).__name__}", flush=True)
        with self.engine.lock:
            if tok and (not self.engine.kite or self.engine.kite.token != tok):
                self.engine.kite = Kite(self.key, tok)
                print("kite session: today's login found", flush=True)
            elif not tok:
                self.engine.kite = None


class Guard:
    """The passcode check: constant-time compare; 10 failures in an hour lock the API for an hour."""

    def __init__(self, passcode, clock=time.time):
        self.passcode, self.clock, self.fails = passcode.encode(), clock, []

    def ok(self, given):
        now = self.clock()
        self.fails = [t for t in self.fails if now - t < 3600]
        if len(self.fails) >= 10:
            return False
        if given and hmac.compare_digest(given.encode(), self.passcode):
            return True
        self.fails.append(now)
        return False


def handler(engine, guard, origin):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):                          # no request lines (they would show what was asked)
            pass

        def _send(self, code, body):
            b = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_OPTIONS(self):
            self._send(204, {})

        def _auth(self):
            h = self.headers.get("Authorization", "")
            if guard.ok(h[7:] if h.startswith("Bearer ") else ""):
                return True
            self._send(401, {"error": "wrong passcode (10 wrong in an hour lock the server for an hour)"})
            return False

        def do_GET(self):
            if not self._auth():
                return
            u = urllib.parse.urlparse(self.path)
            try:
                if u.path == "/api/state":
                    return self._send(200, engine.view())
                if u.path == "/api/chain":
                    return self._send(200, engine.chain(urllib.parse.parse_qs(u.query).get("expiry", [None])[0]))
            except (ValueError, KiteError) as e:
                return self._send(400, {"error": str(e)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._auth():
                return
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 10000)
                req = json.loads(self.rfile.read(n) or b"{}")
                p = self.path.rstrip("/")
                if p == "/api/picks":
                    return self._send(200, {"id": engine.add(req)})
                if p.startswith("/api/picks/") and p.endswith("/exit"):
                    engine.exit(p.split("/")[3])
                    return self._send(200, {"ok": True})
                if p == "/api/stop":
                    engine.stop_all()
                    return self._send(200, {"ok": True})
            except (ValueError, KiteError) as e:
                return self._send(400, {"error": str(e)})
            self._send(404, {"error": "not found"})
    return H


def limits_from_env():
    return {"max_lots": int(os.environ.get("MAX_LOTS", "1")), "max_open": int(os.environ.get("MAX_OPEN", "2")),
            "max_loss_day": int(os.environ.get("MAX_LOSS_DAY", "3000"))}


def main():
    key, secret, code = (os.environ.get(k, "").strip() for k in ("KITE_API_KEY", "KITE_API_SECRET", "ORDERS_PASSCODE"))
    if not (key and secret and len(code) >= 24):
        sys.exit("KITE_API_KEY, KITE_API_SECRET and ORDERS_PASSCODE (24+ characters) must be set (/etc/nifty-orders.env)")
    data = os.environ.get("ORDERS_DATA", "/var/lib/nifty-orders")
    os.makedirs(data, exist_ok=True)
    engine = Engine(os.path.join(data, "state.json"), limits_from_env())
    sess = Session(engine, key, secret, os.path.join(data, "kite"))
    srv = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("ORDERS_PORT", "8787"))),
                              handler(engine, Guard(code), os.environ.get("ALLOW_ORIGIN", "https://ramanauday1561.github.io")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"orders server up; limits {engine.limits}", flush=True)
    while True:
        try:
            sess.refresh()
            engine.tick()
        except Exception as e:                                       # keep going; the exchange holds each stop
            print(f"loop: {type(e).__name__}: {e}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
