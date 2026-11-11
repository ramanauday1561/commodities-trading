"""Order server for your own NIFTY option picks (5 Nov 2026, asked by the user). Runs on a small server with a static
IP (server/setup.sh: a Hostinger VPS in Mumbai since 10 Nov 2026), because since 1 April 2026 Zerodha accepts orders through the
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
from datetime import datetime, timedelta
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
LEANS_URL = "https://api.github.com/repos/ramanauday1561/commodities-trading/contents/next-nifty.json?ref=site-data"
# 11 Nov 2026: GitHub allows 60 API requests an hour per address without a login, 304 answers included, so polling
# every 20 seconds was refused from 12:2x on and the 12:35 and 12:45 stars were missed; every 75 s is 48 an hour
AUTO_EVERY, AUTO_MAX_AGE, AUTO_STOP, AUTO_HOLD = 75, 180, 0.10, 30   # poll s; a lean older than this is skipped; stop; minutes
FALLBACK_CHARGES_LOT = 120      # Rs a lot for a round trip when Kite's charges API cannot be reached (option_study.py)


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

    def _call(self, method, path, data=None, raw=False, as_json=False):
        h = {"X-Kite-Version": "3", "User-Agent": "nifty-orders", "Authorization": f"token {self.key}:{self.token}"}
        if as_json:                                                   # a list of orders: urlencode cannot take it
            body, h["Content-Type"] = json.dumps(data).encode(), "application/json"
        else:
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

    def charges(self, legs):
        """Kite's own charges (its virtual contract note) for [(symbol, "BUY"/"SELL", qty, price)]: the total and its
        parts in rupees (brokerage, STT, exchange and SEBI fees, stamp duty, GST)."""
        rows = [{"order_id": str(i), "exchange": "NFO", "tradingsymbol": s, "transaction_type": side, "variety": "regular",
                 "product": "MIS", "order_type": "LIMIT", "quantity": int(q), "average_price": float(p)}
                for i, (s, side, q, p) in enumerate(legs, 1)]
        out = {"total": 0.0, "brokerage": 0.0, "stt": 0.0, "exchange": 0.0, "sebi": 0.0, "stamp": 0.0, "gst": 0.0}
        for r in self._call("POST", "/charges/orders", rows, as_json=True):
            c = r.get("charges") or {}
            for k, src in (("total", "total"), ("brokerage", "brokerage"), ("stt", "transaction_tax"),
                           ("exchange", "exchange_turnover_charge"), ("sebi", "sebi_turnover_charge"), ("stamp", "stamp_duty")):
                out[k] += float(c.get(src) or 0)
            out["gst"] += float((c.get("gst") or {}).get("total") or 0)
        return {k: round(v, 2) for k, v in out.items()}

    def funds(self):
        """The equity segment of the account: opening balance, live balance, money free to trade."""
        return self._call("GET", "/user/margins/equity")

    def positions(self):
        return self._call("GET", "/portfolio/positions").get("net", [])

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
        self.auto_on = False
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

    # ------------------------------------------------------------------ charges and money
    def _charges(self, legs, lots):
        """Kite's charges for these legs, or about FALLBACK_CHARGES_LOT a lot when Kite cannot say (marked "estimate")."""
        try:
            c = self.kite.charges(legs)
            c["source"] = "kite"
            return c
        except Exception as e:                                          # never block an exit on a charges lookup
            print(f"charges: {type(e).__name__}", flush=True)
            return {"total": float(FALLBACK_CHARGES_LOT * max(lots, 1)), "source": "estimate"}

    def estimate(self, sym, lots):
        """Before buying: what one round trip at today's price costs, and the move needed just to cover it."""
        with self.lock:
            if not self.kite:
                raise ValueError("no Kite login today: log in on the Kite page first")
            self.load_contracts()
            sym = str(sym or "").strip().upper()
            if sym not in self.contracts:
                raise ValueError(f"{sym or 'the option'} is not a NIFTY option trading today")
            lots = max(1, int(lots or 1))
            qty = lots * self.lot_size(sym)
            ltp, bid, ask = best(self.kite.quote([f"NFO:{sym}"]).get(f"NFO:{sym}", {}))
            ref = ask or ltp
            if not ref or not qty:
                raise ValueError("no price for that option right now")
            c = self._charges([(sym, "BUY", qty, ref), (sym, "SELL", qty, ref)], lots)
            return {"symbol": sym, "qty": qty, "price": ref, "paid": round(ref * qty), "charges": c,
                    "breakeven_pts": round(c["total"] / qty, 2)}

    def money(self, history_path=None):
        """The account's money today from Kite: the day's P&L before and after charges, the balance, and one row a day
        kept on this server (totals only, never positions)."""
        k = self.kite                                                   # Kite calls only: not under the trading lock
        if not k:
            raise ValueError("no Kite login today: log in on the Kite page first")
        f = k.funds()
        av = f.get("available") or {}
        pnl = sum(float(p.get("pnl") or 0) for p in k.positions())
        done = [o for o in k.orders().values() if o.get("status") == "COMPLETE" and int(o.get("filled_quantity") or 0)]
        legs = [(o["tradingsymbol"], o["transaction_type"], int(o["filled_quantity"]), float(o["average_price"])) for o in done]
        ch = self._charges(legs, len(legs) // 2) if legs else {"total": 0.0, "source": "kite"}
        start = float(av.get("opening_balance") or 0)
        day = {"start": round(start), "pnl": round(pnl), "charges": round(ch["total"]), "net": round(pnl - ch["total"]),
               "now": round(start + pnl - ch["total"]), "orders": len(done)}
        hist = {}
        if history_path:
            with self.lock:                                           # one writer at a time
                try:
                    hist = json.load(open(history_path))
                except (OSError, ValueError):
                    pass
                hist[self.state["day"] or self.now().date().isoformat()] = day
                hist = dict(sorted(hist.items())[-90:])
                tmp = history_path + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump(hist, fh)
                os.replace(tmp, history_path)
        return {"day": self.state["day"], "now": self.now().isoformat(timespec="seconds"), "today": day,
                "charges": ch, "free_to_trade": round(float(f.get("net") or 0)),
                "history": [{"d": d, **v} for d, v in hist.items()]}

    def auto_pick(self, lean):
        """A pick for one * lean (Auto): the at-the-money option of the next expiry after today on its side."""
        with self.lock:
            if not self.kite:
                raise ValueError("no Kite login today")
            self.load_contracts()
            today = self.now().date().isoformat()
            exps = sorted({r["expiry"] for r in self.contracts.values() if r["expiry"] > today})
            spot = self.kite.quote(["NSE:NIFTY 50"]).get("NSE:NIFTY 50", {}).get("last_price")
            if not exps or not spot:
                raise ValueError("no expiry or no NIFTY price")
            typ, k = ("CE" if lean["lean"] == "up" else "PE"), round(spot / 50) * 50
            sym = next((s for s, r in self.contracts.items() if r["expiry"] == exps[0] and r["instrument_type"] == typ
                        and float(r["strike"]) == k), None)
            if not sym:
                raise ValueError(f"no {k} {typ} for {exps[0]}")
            ltp, _, ask = best(self.kite.quote([f"NFO:{sym}"]).get(f"NFO:{sym}", {}))
            ref = ask or ltp
            if not ref:
                raise ValueError(f"no price for {sym}")
            out = (self.now() + timedelta(minutes=AUTO_HOLD)).strftime("%H:%M")
            tid = self.add({"symbol": sym, "lots": 1, "stop": down(ref * (1 - AUTO_STOP)), "exit_by": min(out, LAST_EXIT_T)})
            t = next(x for x in self.state["trades"] if x["id"] == tid)
            t["auto"] = f"\u2605 {lean['at']} {lean['lean']}"
            self.log(t, f"placed by itself for the \u2605 lean {lean['at']} {lean['lean']}")
            self.save()
            return tid

    # ------------------------------------------------------------------ the phone's requests
    def view(self):
        with self.lock:
            open_loss = sum(self._pnl(t) for t in self.state["trades"])
            return {"day": self.state["day"], "now": self.now().isoformat(timespec="seconds"), "kite": bool(self.kite),
                    "locked": self.state["locked"], "limits": self.limits, "auto": self.auto_on, "day_pnl": round(open_loss),
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
            est = self._charges([(sym, "BUY", qty, ref), (sym, "SELL", qty, stop)], lots)
            risk = (ref - stop) * qty + est["total"]
            if risk > L["max_loss_day"] + self._pnl_today():
                raise ValueError(f"this pick could lose about Rs{risk:,.0f}, more than what is left of today's limit")
            price = up(limit) if limit else up(ask * 1.01 if ask else ltp * 1.02)
            t = {"id": uuid.uuid4().hex[:8], "symbol": sym, "lots": lots, "qty": qty, "limit": limit, "stop": stop,
                 "target": target, "exit_by": exit_by, "status": "entering", "made": now.isoformat(timespec="seconds"),
                 "entry_price": price, "tries": 0, "since": self.clock(), "filled": 0, "avg_in": None, "avg_out": None,
                 "ltp": ltp, "why": None, "charges_est": round(est["total"], 2)}
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
        c = self._charges([(t["symbol"], "BUY", t["filled"], t["avg_in"]), (t["symbol"], "SELL", t["filled"], avg_out)], t["lots"])
        t["charges"], t["net"] = round(c["total"], 2), round(t["pnl"] - c["total"])
        self.log(t, f"sold {t['filled']} at {avg_out}: {why}; charges Rs{c['total']:.2f}")

    def _pnl(self, t):
        """Rupees after charges (the daily loss limit counts them): closed at the sale price less Kite's charges, open at
        the last price less the charges estimated when it was placed."""
        if t.get("pnl") is not None:
            return t["pnl"] - t.get("charges", t.get("charges_est", 0))
        if t["status"] in ("open", "exiting") and t.get("avg_in") and t.get("ltp"):
            return (t["ltp"] - t["avg_in"]) * t["filled"] - t.get("charges_est", 0)
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


def auto_leans(doc, now, done):
    """The * leans to act on now: today's, confident, made at most AUTO_MAX_AGE seconds ago (the page records the minute
    it was made, so up to a minute more), and not tried before (done: the ids already tried today)."""
    today = now.date().isoformat()
    if not doc or doc.get("date") != today:
        return []
    out = []
    for l in doc.get("leans") or []:
        lid = f"{today} {l.get('at')}"
        if not l.get("confident") or lid in done or l.get("lean") not in ("up", "down"):
            continue
        try:
            made = datetime.strptime(f"{today} {l.get('made') or l['at']}", "%Y-%m-%d %H:%M").replace(tzinfo=now.tzinfo)
        except (KeyError, ValueError):
            continue
        if 0 <= (now - made).total_seconds() <= AUTO_MAX_AGE + 60:
            out.append({**l, "id": lid})
    return out


class Auto:
    """AUTO_STAR=1 (11 Nov 2026, asked by the owner: "make it place orders automatically"): each new * lean becomes a
    pick by itself. The at-the-money option of the next expiry after today on the lean's side (CALL up, PUT down),
    1 lot, stop 10% under the price, out after 30 minutes. Every pick goes through Engine.add like a phone pick (the
    limits, the Kite login, the hours), and each lean is tried once only, even if the order is refused. The * leans
    lost Rs53-72 a lot a trade in the 2017-2026 tests (star_hold_study.py)."""

    def __init__(self, engine, fetch=None, clock=time.time):
        self.engine, self.clock, self.etag, self.checked = engine, clock, None, 0.0
        self.fetch = fetch or self._fetch

    def _fetch(self):
        """next-nifty.json from the site-data branch through GitHub's API (no CDN delay); None when unchanged
        (a 304 answer to If-None-Match does not count against GitHub's rate limit)."""
        h = {"Accept": "application/vnd.github.raw+json", "User-Agent": "nifty-orders"}
        if self.etag:
            h["If-None-Match"] = self.etag
        try:
            with urllib.request.urlopen(urllib.request.Request(LEANS_URL, headers=h), timeout=10) as f:
                self.etag = f.headers.get("ETag")
                return json.load(f)
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return None
            if e.code in (403, 429):                                   # rate limited: wait for GitHub's reset time
                try:
                    reset = float(e.headers.get("X-RateLimit-Reset") or 0)
                except (TypeError, ValueError):
                    reset = 0
                self.checked = max(self.checked, min(reset, self.clock() + 3600) - AUTO_EVERY)
                print(f"auto: GitHub rate limit; next check in {max(0, int(self.checked + AUTO_EVERY - self.clock()))} s", flush=True)
                return None
            raise

    def tick(self):
        if self.clock() - self.checked < AUTO_EVERY:
            return
        self.checked = self.clock()
        doc = self.fetch()
        if doc is None:
            return
        e = self.engine
        with e.lock:
            e._new_day()
            done = e.state.setdefault("auto_done", [])
            todo = auto_leans(doc, e.now(), set(done))
            for l in todo:
                done.append(l["id"])                         # before trying: never twice, even after a refusal
            e.save()
        for l in todo:
            try:
                tid = e.auto_pick(l)
                print(f"auto: star {l['at']} {l['lean']}: pick {tid}", flush=True)
            except (ValueError, KiteError) as err:
                print(f"auto: star {l['at']} {l['lean']} not placed: {err}", flush=True)


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


def handler(engine, guard, origin, history_path=None):
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
                q = urllib.parse.parse_qs(u.query)
                if u.path == "/api/estimate":
                    return self._send(200, engine.estimate(q.get("symbol", [""])[0], q.get("lots", ["1"])[0]))
                if u.path == "/api/money":
                    return self._send(200, engine.money(history_path))
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
    engine.auto_on = os.environ.get("AUTO_STAR", "0").strip() == "1"
    auto = Auto(engine) if engine.auto_on else None
    srv = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("ORDERS_PORT", "8787"))),
                              handler(engine, Guard(code), os.environ.get("ALLOW_ORIGIN", "https://ramanauday1561.github.io"),
                                      os.path.join(data, "money.json")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"orders server up; limits {engine.limits}; automatic star picks {'ON' if engine.auto_on else 'off'}", flush=True)
    while True:
        try:
            sess.refresh()
            engine.tick()
            if auto:
                auto.tick()
        except Exception as e:                                       # keep going; the exchange holds each stop
            print(f"loop: {type(e).__name__}: {e}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
