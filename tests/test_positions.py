"""Phone alerts on your own Kite positions (no network)."""
import os
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import positions as ps  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def at(h, m):
    return datetime(2026, 11, 5, h, m, tzinfo=IST)


def pos(sym="NIFTY26N1023800CE", qty=65, avg=100.0, ltp=100.0, product="MIS", exch="NFO"):
    return {"tradingsymbol": sym, "exchange": exch, "product": product, "quantity": qty, "average_price": avg,
            "last_price": ltp, "pnl": (ltp - avg) * qty}


class Check(unittest.TestCase):

    def test_bought_option_levels_once_each(self):
        a, st = ps.check([pos()], {}, at(9, 30))
        self.assertEqual([x[0] for x in a], ["position"])
        self.assertIn("Tracking: Bought NIFTY26N1023800CE x65 (MIS)", a[0][1])
        a, st = ps.check([pos(ltp=78)], st, at(9, 40))                      # -22%: the warning
        self.assertEqual([(x[0], x[1].split(":")[0]) for x in a], [("position", "Warning")])
        a, st = ps.check([pos(ltp=60)], st, at(9, 50))                      # -40%: the stop, once
        self.assertEqual([x[0] for x in a], ["position_stop"])
        self.assertEqual(ps.check([pos(ltp=55)], st, at(10, 0))[0], [])
        closed = dict(pos(qty=0, ltp=55), pnl=-2925.0)                       # Kite: quantity 0, the realised P&L
        a, st = ps.check([closed], st, at(10, 10))
        self.assertEqual(a[0][1], "Closed: NIFTY26N1023800CE")
        self.assertIn("-Rs2,925", a[0][2])

    def test_sold_option_and_size_change(self):
        a, st = ps.check([pos(qty=-65, avg=100, ltp=100)], {}, at(9, 30))
        self.assertIn("Sold", a[0][1])
        a, st = ps.check([pos(qty=-65, avg=100, ltp=55)], st, at(10, 0))   # decayed 45%: profit
        self.assertEqual(a[0][1].split(":")[0], "Profit")
        a, st = ps.check([pos(qty=-130, avg=100, ltp=55)], st, at(10, 10))  # added a lot: tracked again
        self.assertTrue(a[0][1].startswith("Tracking"))

    def test_square_off_reminder_and_filters(self):
        other = [pos(sym="RELIANCE", exch="NSE"), pos(sym="SENSEX26N1080000CE", exch="BFO")]
        a, st = ps.check(other, {}, at(15, 12))
        self.assertEqual(a, [])                                               # only NIFTY / BANKNIFTY options
        a, st = ps.check([pos()], {}, at(15, 12))
        self.assertEqual([x[0] for x in a], ["position", "position_stop"])
        self.assertIn("Zerodha squares these off", a[1][2])
        self.assertEqual(ps.check([pos()], st, at(15, 14))[0], [])

    def test_silent_takeover_and_new_day(self):
        a, st = ps.check([pos(ltp=60)], {}, at(14, 15), silent=True)
        self.assertEqual(a, [])
        self.assertEqual(ps.check([pos(ltp=60)], st, at(14, 20))[0], [])     # already-crossed levels not repeated
        a, _ = ps.check([pos(ltp=60)], dict(st, date="2026-11-04"), at(9, 30))
        self.assertTrue(a)

    def test_watcher_paces_and_looks_for_a_login(self):
        sent, refreshed = [], []
        w = ps.Watcher(every=0, fetch_fn=lambda: None, notify_fn=sent.append, refresh_fn=lambda: refreshed.append(1))
        self.assertEqual(w.check(at(9, 30)), 0)
        self.assertEqual(refreshed, [1])
        w.fetch = lambda: [pos()]
        self.assertEqual(w.check(at(8, 50)), 0)                               # before the session
        self.assertEqual(w.check(at(9, 31)), 1)
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
