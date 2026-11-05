"""The order server for your own picks (server/orders_server.py), against a fake Kite (no network, no orders)."""
import json
import os
import sys
import tempfile
import threading
import unittest
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


if __name__ == "__main__":
    unittest.main()
