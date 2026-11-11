"""The order server for your own picks (server/orders_server.py), against a fake Kite (no network, no orders)."""
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import orders_server as osv  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
SYM = "NIFTY26N0924500CE"


class FakeKite:
    """Orders sit OPEN (or TRIGGER PENDING) until the test fills, triggers or rejects them."""

    def __init__(self):
        self.token, self.book, self.calls, self.prices = "tok", {}, [], {SYM: (100.0, 99.5, 100.5)}

    def place(self, symbol, side, qty, order_type, price, trigger=None):
        oid = str(len(self.book) + 1)
        self.book[oid] = {"order_id": oid, "symbol": symbol, "side": side, "qty": qty, "order_type": order_type, "price": price,
                          "trigger": trigger, "status": "TRIGGER PENDING" if order_type == "SL" else "OPEN",
                          "filled_quantity": 0, "average_price": 0}
        self.calls.append(("place", side, order_type, qty, price, trigger))
        return oid

    def modify(self, oid, price, order_type="LIMIT"):
        self.book[oid]["price"] = price
        self.calls.append(("modify", oid, price))

    def cancel(self, oid):
        if self.book[oid]["status"] == "COMPLETE":
            raise osv.KiteError("InputException: order already complete")
        self.book[oid]["status"] = "CANCELLED"
        self.calls.append(("cancel", oid))

    def orders(self):
        return {k: dict(v) for k, v in self.book.items()}

    def quote(self, symbols):
        out = {}
        for s in symbols:
            if s == "NSE:NIFTY 50":
                out[s] = {"last_price": 24510.0}
            else:
                ltp, bid, ask = self.prices.get(s.split(":")[1], (50.0, 49.5, 50.5))
                out[s] = {"last_price": ltp, "depth": {"buy": [{"price": bid}], "sell": [{"price": ask}]}}
        return out

    def instruments(self):
        return [{"tradingsymbol": f"NIFTY26N09{k}{t}", "name": "NIFTY", "segment": "NFO-OPT", "expiry": "2026-11-09",
                 "strike": str(k), "instrument_type": t, "lot_size": "65"} for k in (24450, 24500, 24550) for t in ("CE", "PE")]

    def charges(self, legs):                                       # Rs 20 brokerage an order, 0.1% STT on sales
        tot = sum(20 + (0.001 * q * p if side == "SELL" else 0) for _, side, q, p in legs)
        return {"total": round(tot, 2), "brokerage": 20.0 * len(legs)}

    def funds(self):
        return {"net": 15000.0, "available": {"opening_balance": 20000.0, "live_balance": 15000.0}}

    def positions(self):
        return [{"tradingsymbol": SYM, "pnl": 650.0}]

    def fill(self, oid, price, qty=None):
        o = self.book[oid]
        o.update(status="COMPLETE", filled_quantity=qty or o["qty"], average_price=price)


class Clock:
    def __init__(self):
        self.t, self.dt = 1000.0, datetime(2026, 11, 6, 10, 0, tzinfo=IST)     # Friday 10:00

    def now(self):
        return self.dt

    def clock(self):
        return self.t


LIMITS = {"max_lots": 2, "max_open": 2, "max_loss_day": 3000}


class Engine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c, self.k = Clock(), FakeKite()
        self.e = osv.Engine(os.path.join(self.tmp.name, "state.json"), dict(LIMITS), now=self.c.now, clock=self.c.clock)
        self.e.kite = self.k

    def tearDown(self):
        self.tmp.cleanup()

    def pick(self, **kw):
        req = {"symbol": SYM, "lots": 1, "stop": 80, **kw}
        return self.e.add(req)

    def trade(self, tid):
        return next(t for t in self.e.state["trades"] if t["id"] == tid)

    def test_entry_stop_then_target(self):
        tid = self.pick(target=130)
        self.assertEqual(self.k.calls[0], ("place", "BUY", "LIMIT", 65, osv.up(100.5 * 1.01), None))   # never MARKET
        self.k.fill("1", 101.0)
        self.e.tick()
        t = self.trade(tid)
        self.assertEqual((t["status"], t["avg_in"]), ("open", 101.0))
        self.assertEqual(self.k.calls[-1][:4], ("place", "SELL", "SL", 65))                          # the stop is at the exchange
        self.assertEqual(self.k.calls[-1][5], 80.0)
        self.k.prices[SYM] = (131.0, 130.5, 131.5)
        self.e.tick()
        self.assertIn(("cancel", "2"), self.k.calls)                                                 # stop cancelled first
        self.assertEqual((t["status"], self.k.calls[-1][1:3]), ("exiting", ("SELL", "LIMIT")))
        self.k.fill("3", 130.0)
        self.e.tick()
        self.assertEqual((t["status"], t["pnl"], t["why"]), ("closed", round(29 * 65), "target reached"))
        saved = json.load(open(os.path.join(self.tmp.name, "state.json")))
        self.assertEqual(saved["trades"][0]["status"], "closed")

    def test_stopped_out_at_the_exchange(self):
        tid = self.pick()
        self.k.fill("1", 100.0)
        self.e.tick()
        self.k.fill("2", 79.0)
        self.e.tick()
        t = self.trade(tid)
        self.assertEqual((t["status"], t["pnl"], t["why"]), ("closed", -21 * 65, "stopped out"))

    def test_triggered_stop_not_filled_is_repriced(self):
        self.pick()
        self.k.fill("1", 100.0)
        self.e.tick()
        self.k.book["2"]["status"] = "OPEN"                       # triggered, the limit not reached
        self.k.prices[SYM] = (70.0, 69.0, 71.0)
        self.e.tick()
        self.c.t += osv.SL_WAIT
        self.e.tick()
        self.assertEqual(self.k.calls[-1], ("modify", "2", osv.down(69.0 * 0.99)))

    def test_now_entry_repriced_then_cancelled(self):
        tid = self.pick()
        for _ in range(osv.ENTRY_TRIES):
            self.c.t += osv.ENTRY_WAIT
            self.e.tick()
        self.assertEqual(sum(1 for c in self.k.calls if c[0] == "modify"), osv.ENTRY_TRIES)
        self.c.t += osv.ENTRY_WAIT
        self.e.tick()
        self.assertEqual(self.trade(tid)["status"], "not entered")
        self.assertIn(("cancel", "1"), self.k.calls)

    def test_exit_time(self):
        tid = self.pick(exit_by="10:30")
        self.k.fill("1", 100.0)
        self.e.tick()
        self.c.dt = self.c.dt.replace(minute=30)
        self.e.tick()
        self.assertEqual((self.trade(tid)["status"], self.trade(tid)["why"]), ("exiting", "exit time"))

    def test_day_loss_limit_sells_and_locks(self):
        self.pick(lots=2, stop=90)
        self.k.fill("1", 100.0)
        self.e.tick()
        self.k.prices[SYM] = (76.0, 75.0, 77.0)                   # 2 lots x 65 x -24 = -3,120: past the 3,000 limit
        self.e.tick()
        self.assertIn("MAX_LOSS_DAY", self.e.state["locked"])
        self.assertEqual(self.e.state["trades"][0]["status"], "exiting")
        with self.assertRaisesRegex(ValueError, "locked"):
            self.pick()

    def test_stop_everything(self):
        a = self.pick()
        self.k.fill("1", 100.0)
        self.e.tick()
        b = self.pick()
        self.e.stop_all()
        self.assertEqual(self.trade(a)["status"], "exiting")
        self.assertEqual(self.trade(b)["status"], "not entered")
        self.assertTrue(self.e.state["locked"])

    def test_part_filled_entry_keeps_what_filled(self):
        tid = self.pick(limit=100)
        self.k.book["1"].update(status="CANCELLED", filled_quantity=30, average_price=100.0)
        self.e.tick()
        t = self.trade(tid)
        self.assertEqual((t["status"], t["filled"]), ("open", 30))
        self.assertEqual(self.k.calls[-1][3], 30)

    def test_rejected_entry(self):
        tid = self.pick()
        self.k.book["1"].update(status="REJECTED", status_message="Insufficient funds")
        self.e.tick()
        self.assertEqual((self.trade(tid)["status"], self.trade(tid)["why"]), ("not entered", "Insufficient funds"))

    def test_checks_before_any_order(self):
        cases = [({"lots": 3}, "lots must be"), ({"stop": 120}, "stop must be below"), ({"target": 90}, "target must be above"),
                 ({"symbol": "BANKNIFTYX"}, "not a NIFTY option"), ({"exit_by": "15:20"}, "exit time"), ({"stop": "x"}, "numbers")]
        for kw, msg in cases:
            with self.subTest(kw=kw), self.assertRaisesRegex(ValueError, msg):
                self.pick(**kw)
        self.c.dt = self.c.dt.replace(hour=15, minute=5)
        with self.assertRaisesRegex(ValueError, "picks are taken"):
            self.pick()
        self.c.dt = self.c.dt.replace(hour=10)
        self.e.limits["max_loss_day"] = 500
        with self.assertRaisesRegex(ValueError, "could lose"):
            self.pick()
        self.e.kite = None
        with self.assertRaisesRegex(ValueError, "no Kite login"):
            self.pick()
        self.assertEqual(self.k.calls, [])

    def test_max_open(self):
        self.pick()
        self.pick()
        with self.assertRaisesRegex(ValueError, "MAX_OPEN"):
            self.pick()

    def test_new_day_starts_clean(self):
        self.pick()
        self.e.stop_all()
        self.c.dt = datetime(2026, 11, 9, 9, 20, tzinfo=IST)
        self.e.tick()
        self.assertEqual((self.e.state["day"], self.e.state["locked"], self.e.state["trades"]), ("2026-11-09", None, []))

    def test_chain(self):
        c = self.e.chain()
        self.assertEqual((c["expiry"], c["spot"], c["lot"], len(c["options"])), ("2026-11-09", 24510.0, 65, 6))

    def test_ticks(self):
        self.assertEqual((osv.up(100.51), osv.down(100.54), osv.down(0.01)), (100.55, 100.5, 0.05))


class Http(unittest.TestCase):
    def test_passcode_and_lockout(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        c = Clock()
        e = osv.Engine(os.path.join(tmp.name, "s.json"), dict(LIMITS), now=c.now, clock=c.clock)
        code = "p" * 32
        srv = ThreadingHTTPServer(("127.0.0.1", 0), osv.handler(e, osv.Guard(code), "https://example.github.io"))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_port}/api/state"

        def get(tok):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})) as f:
                    return f.status, json.load(f)
            except urllib.error.HTTPError as err:
                return err.code, None
        status, body = get(code)
        self.assertEqual((status, body["kite"], body["limits"]["max_lots"]), (200, False, 2))
        for _ in range(10):
            self.assertEqual(get("wrong")[0], 401)
        self.assertEqual(get(code)[0], 401)                      # locked for an hour after 10 wrong


class Charges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c, self.k = Clock(), FakeKite()
        self.e = osv.Engine(os.path.join(self.tmp.name, "state.json"), dict(LIMITS), now=self.c.now, clock=self.c.clock)
        self.e.kite = self.k

    def tearDown(self):
        self.tmp.cleanup()

    def test_estimate_before_buying(self):
        est = self.e.estimate(SYM, 1)
        self.assertEqual((est["qty"], est["price"], est["paid"]), (65, 100.5, round(100.5 * 65)))
        self.assertEqual(est["charges"]["total"], round(40 + 0.001 * 65 * 100.5, 2))
        self.assertEqual(est["breakeven_pts"], round(est["charges"]["total"] / 65, 2))
        with self.assertRaisesRegex(ValueError, "not a NIFTY option"):
            self.e.estimate("INFY", 1)

    def test_closed_trade_is_counted_after_charges(self):
        tid = self.e.add({"symbol": SYM, "lots": 1, "stop": 80, "target": 130})
        t = next(x for x in self.e.state["trades"] if x["id"] == tid)
        self.assertEqual(t["charges_est"], round(40 + 0.001 * 65 * 80, 2))       # sold at the stop: the worst case
        self.k.fill("1", 101.0)
        self.e.tick()
        self.k.prices[SYM] = (131.0, 130.5, 131.5)
        self.e.tick()
        self.k.fill("3", 130.0)
        self.e.tick()
        ch = round(40 + 0.001 * 65 * 130.0, 2)
        self.assertEqual((t["pnl"], t["charges"], t["net"]), (29 * 65, ch, round(29 * 65 - ch)))
        self.assertAlmostEqual(self.e._pnl_today(), 29 * 65 - ch)                  # the loss limit counts charges

    def test_charges_fall_back_when_kite_cannot_say(self):
        def broken(legs):
            raise osv.KiteError("NetworkException")
        self.k.charges = broken
        c = self.e._charges([(SYM, "BUY", 65, 100)], 1)
        self.assertEqual((c["total"], c["source"]), (osv.FALLBACK_CHARGES_LOT, "estimate"))

    def test_money_today_and_history(self):
        self.k.fill(self.k.place(SYM, "BUY", 65, "LIMIT", 100.0), 100.0)
        self.k.fill(self.k.place(SYM, "SELL", 65, "LIMIT", 110.0), 110.0)
        for o in self.k.book.values():                                            # Kite's order fields
            o.update(tradingsymbol=o["symbol"], transaction_type=o["side"])
        path = os.path.join(self.tmp.name, "money.json")
        m = self.e.money(path)
        ch = round(40 + 0.001 * 65 * 110.0)
        self.assertEqual(m["today"], {"start": 20000, "pnl": 650, "charges": ch, "net": 650 - ch, "now": 20000 + 650 - ch, "orders": 2})
        self.assertEqual(m["free_to_trade"], 15000)
        self.assertEqual([h["d"] for h in m["history"]], ["2026-11-06"])
        self.assertNotIn(SYM, open(path).read())                                   # totals only, never positions


class KiteCharges(unittest.TestCase):
    def test_charges_are_sent_as_json(self):
        """11 Nov 2026: the real call failed with TypeError (urlencode cannot take a list of orders)."""
        seen = {}
        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b""
        def fake(req, timeout):
            seen["type"], seen["body"] = req.get_header("Content-type"), json.loads(req.data)
            import io
            return io.BytesIO(json.dumps({"data": [{"charges": {"total": 30.5, "brokerage": 20, "transaction_tax": 5,
                                                                "gst": {"total": 3.6}}}]}).encode())
        orig, osv.urllib.request.urlopen = osv.urllib.request.urlopen, fake
        try:
            c = osv.Kite("k", "t").charges([(SYM, "BUY", 65, 100.0)])
        finally:
            osv.urllib.request.urlopen = orig
        self.assertEqual(seen["type"], "application/json")
        self.assertEqual(seen["body"][0]["tradingsymbol"], SYM)
        self.assertEqual((c["total"], c["stt"], c["gst"]), (30.5, 5.0, 3.6))


class AutoStar(unittest.TestCase):
    """AUTO_STAR=1: each new * lean becomes a pick by itself, once."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c, self.k = Clock(), FakeKite()                                   # Friday 10:00, NIFTY 24,510
        self.e = osv.Engine(os.path.join(self.tmp.name, "state.json"), dict(LIMITS), now=self.c.now, clock=self.c.clock)
        self.e.kite = self.k
        self.k.prices["NIFTY26N0924500PE"] = (80.0, 79.5, 80.5)
        self.doc = {"date": "2026-11-06", "leans": [
            {"at": "09:45", "lean": "up", "confident": True, "made": "09:45"},      # 15 minutes old: too late
            {"at": "09:55", "lean": "up", "confident": False, "made": "09:59"},     # not a star
            {"at": "10:05", "lean": "down", "confident": True, "made": "09:59"}]}   # fresh star

    def tearDown(self):
        self.tmp.cleanup()

    def test_which_leans(self):
        got = osv.auto_leans(self.doc, self.c.now(), set())
        self.assertEqual([x["id"] for x in got], ["2026-11-06 10:05"])
        self.assertEqual(osv.auto_leans(self.doc, self.c.now(), {"2026-11-06 10:05"}), [])
        self.assertEqual(osv.auto_leans({**self.doc, "date": "2026-11-05"}, self.c.now(), set()), [])

    def test_a_star_becomes_one_pick(self):
        docs = [self.doc, None, self.doc]                                      # then unchanged, then the same again
        a = osv.Auto(self.e, fetch=lambda: docs.pop(0), clock=self.c.clock)
        a.tick()
        self.assertEqual(self.k.calls[0][:4], ("place", "BUY", "LIMIT", 65))     # 1 lot, limit order
        t = self.e.state["trades"][0]
        self.assertEqual((t["symbol"], t["lots"], t["exit_by"]), ("NIFTY26N0924500PE", 1, "10:30"))   # ATM PUT, next expiry
        self.assertEqual(t["stop"], osv.down(80.5 * 0.9))
        self.assertIn("10:05 down", t["auto"])
        for _ in range(2):
            self.c.t += osv.AUTO_EVERY
            a.tick()
        self.assertEqual(len(self.e.state["trades"]), 1)                        # never twice

    def test_rate_limit_waits_for_the_reset(self):
        import email.message
        a = osv.Auto(self.e, clock=self.c.clock)
        h = email.message.Message()
        h["X-RateLimit-Reset"] = str(self.c.t + 900)
        calls = []
        def refused(req, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(osv.LEANS_URL, 403, "rate limit exceeded", h, None)
        orig, osv.urllib.request.urlopen = osv.urllib.request.urlopen, refused
        try:
            a.tick()
            self.c.t += osv.AUTO_EVERY * 3                                       # still before the reset: no request
            a.tick()
            self.assertEqual(len(calls), 1)
            self.c.t += 900
            a.tick()
            self.assertEqual(len(calls), 2)
        finally:
            osv.urllib.request.urlopen = orig
        self.assertLessEqual(3600 / osv.AUTO_EVERY, 50)                          # under GitHub's 60 an hour

    def test_a_refused_star_is_not_retried(self):
        self.e.state["locked"] = "stop everything from the phone"
        a = osv.Auto(self.e, fetch=lambda: self.doc, clock=self.c.clock)
        a.tick()
        self.c.t += osv.AUTO_EVERY
        self.e.state["locked"] = None
        a.tick()
        self.assertEqual((self.e.state["trades"], self.k.calls), ([], []))
        self.assertEqual(self.e.state["auto_done"], ["2026-11-06 10:05"])


class Practice(unittest.TestCase):
    """AUTO_STAR=practice: an automatic pick with no order; scored at the stop or the exit time; not in the real P&L."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c, self.k = Clock(), FakeKite()
        self.e = osv.Engine(os.path.join(self.tmp.name, "state.json"), dict(LIMITS), now=self.c.now, clock=self.c.clock)
        self.e.kite, self.e.auto_mode = self.k, "practice"
        self.k.prices["NIFTY26N0924500PE"] = (80.0, 79.5, 80.5)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_order_and_out_at_the_exit_time(self):
        tid = self.e.auto_pick({"at": "10:05", "lean": "down"})
        self.assertEqual(self.k.calls, [])                                       # nothing sent to Kite
        t = self.e.state["trades"][0]
        self.assertEqual((t["status"], t["avg_in"], t["exit_by"], t["practice"]), ("practice", 80.5, "10:30", True))
        self.k.prices["NIFTY26N0924500PE"] = (90.0, 89.5, 90.5)
        self.e.tick()
        self.assertEqual(t["status"], "practice")
        self.c.dt = self.c.dt.replace(minute=30)
        self.e.tick()
        self.assertEqual((t["status"], t["avg_out"], t["why"], t["pnl"]), ("closed", 89.5, "exit time (practice)", round(9 * 65)))
        self.assertIn("charges", t)
        self.assertEqual(self.e._pnl_today(), 0)                                 # never in the real P&L or the limit
        self.assertEqual(self.e.view()["practice_pnl"], round(9 * 65 - t["charges"]))
        self.assertEqual(self.k.calls, [])
        self.assertEqual(tid, t["id"])

    def test_stop(self):
        self.e.auto_pick({"at": "10:05", "lean": "down"})
        t = self.e.state["trades"][0]
        self.k.prices["NIFTY26N0924500PE"] = (70.0, 69.5, 70.5)                  # under the 10% stop (72.45)
        self.e.tick()
        self.assertEqual((t["status"], t["avg_out"], t["why"]), ("closed", t["stop"], "stop (practice)"))


class Local(unittest.TestCase):
    """The lean made on the server, 15-120 s after each 10-minute boundary."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c, self.k = Clock(), FakeKite()
        self.e = osv.Engine(os.path.join(self.tmp.name, "state.json"), dict(LIMITS), now=self.c.now, clock=self.c.clock)
        self.e.kite = self.k
        self.files = {"nextcandle-model.txt": b"m", "nextcandle-size.txt": b"s",
                      "nextcandle-meta.json": json.dumps({"trained_until": "2026-11-05"}).encode()}
        self.seen = []

    def tearDown(self):
        self.tmp.cleanup()

    def lean(self, model_dir, now, get):
        self.seen.append(get("^NSEI"))
        return {"at": now.strftime("%H:%M"), "lean": "down", "confident": True, "pts": -2.0}

    def test_boundaries(self):
        b = osv.LocalLeans.boundary
        t = self.c.dt                                                            # 10:00:00 is not a boundary (09:15 + 10n)
        self.assertIsNone(b(t))
        self.assertIsNone(b(t.replace(minute=5, second=10)))                     # too soon: the bar may not be final
        self.assertEqual(b(t.replace(minute=5, second=20)), "10:05")
        self.assertIsNone(b(t.replace(minute=7, second=5)))                      # too late
        self.assertIsNone(b(t.replace(hour=9, minute=15, second=30)))            # 09:15: nothing finished yet
        self.assertIsNone(b(t.replace(hour=15, minute=15, second=30)))           # the closing auction: no 15:15 lean

    def test_a_local_star_is_bought_once(self):
        self.k.history5 = lambda tok, a, b: [["2026-11-06T09:55:00+0530", 1, 2, 0.5, 1.5, 0],
                                             ["2026-11-06T10:00:00+0530", 1, 2, 0.5, 1.6, 0],
                                             ["2026-11-06T10:05:00+0530", 1, 2, 0.5, 1.7, 0]]   # still forming
        self.k.prices["NIFTY26N0924500PE"] = (80.0, 79.5, 80.5)
        loc = osv.LocalLeans(self.e, os.path.join(self.tmp.name, "model"), download=self.files.__getitem__, lean=self.lean)
        a = osv.Auto(self.e, fetch=lambda: None, clock=self.c.clock, local=loc)
        self.c.dt = self.c.dt.replace(minute=5, second=20)
        a.tick()
        a.tick()                                                                 # same boundary again: nothing new
        self.assertEqual(len(self.e.state["trades"]), 1)
        self.assertEqual(self.e.state["trades"][0]["auto"], "\u2605 10:05 down")
        bars = self.seen[0][self.c.dt.date()]
        self.assertEqual([str(i)[11:16] for i in bars.index], ["09:55", "10:00"])     # the forming 10:05 bar is left out

    def test_a_model_trained_on_today_is_not_used(self):
        self.files["nextcandle-meta.json"] = json.dumps({"trained_until": "2026-11-06"}).encode()
        loc = osv.LocalLeans(self.e, os.path.join(self.tmp.name, "model"), download=self.files.__getitem__, lean=self.lean)
        self.c.dt = self.c.dt.replace(minute=5, second=20)
        self.assertIsNone(loc.check())
        self.assertEqual(self.seen, [])


class KiteLogin(unittest.TestCase):
    """The morning Kite login on the VPS: traded with Kite, saved for both servers, copied to GitHub."""

    def test_login_saved_and_copied(self):
        store, seen = tempfile.mkdtemp(), []
        def fake_login(rt, d, key, secret):
            seen.append((rt, key, secret))
            json.dump({"until": "2026-11-12T06:00+05:30", "token": "enc"}, open(os.path.join(d, osv.kite.SESSION), "w"))
        with mock.patch.object(osv.kite, "login", fake_login):
            out = osv.kite_login("AbC123xyz789", store, "k", "s", push=lambda: True)
        self.assertEqual(out, {"until": "2026-11-12T06:00+05:30", "pushed": True})
        self.assertEqual(seen, [("AbC123xyz789", "k", "s")])

    def test_junk_and_kite_refusals(self):
        with mock.patch.object(osv.kite, "login", side_effect=AssertionError("must not be called")):
            for bad in (None, "", "short", "has spaces in it", "x" * 80):
                with self.assertRaisesRegex(ValueError, "not a Kite request token"):
                    osv.kite_login(bad, tempfile.mkdtemp(), "k", "s", push=lambda: True)
        with mock.patch.object(osv.kite, "login", side_effect=RuntimeError("TokenException: secret-ish text")):
            with self.assertRaises(ValueError) as e:
                osv.kite_login("AbC123xyz789", tempfile.mkdtemp(), "k", "s", push=lambda: True)
        self.assertNotIn("AbC123xyz789", str(e.exception))                       # the token is never echoed


if __name__ == "__main__":
    unittest.main()
