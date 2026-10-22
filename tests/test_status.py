"""Status page decisions and when an alert goes out (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import status  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def at(h, m, day=22):
    return datetime(2026, 10, day, h, m, tzinfo=IST)


def today(trade=True, direction="down", st="pre_open", skipped=False, recent=None):
    return {"date": "2026-10-22", "status": st, "record": {"recent": recent or []},
            "preopen": {"close": {"direction": direction, "tier": "lean"},
                        "from_open": {"direction": direction, "trade": trade, "skipped_for_results": skipped,
                                      "trade_stats": {"days": 80, "from_open": {"win_rate": 0.575, "avg_pct_after_costs": 0.151}}}}}


class Decide(unittest.TestCase):
    def test_trade_day(self):
        self.assertEqual(status.decide(today(direction="down"), at(8, 58))["state"], "PUT")
        self.assertEqual(status.decide(today(direction="up"), at(9, 5))["state"], "CALL")
        s = status.decide(today(direction="up", st="open"), at(10, 0))
        self.assertEqual((s["state"], s["side"]), ("STAY", "CALL"))
        s = status.decide(today(st="open"), at(14, 50))
        self.assertEqual((s["state"], s["kind"]), ("NOTHING", "exit"))

    def test_no_trade_results_and_early(self):
        kinds = lambda s: (s["state"], s["kind"])
        self.assertEqual(kinds(status.decide(today(trade=False), at(8, 58))), ("NOTHING", "no_trade"))
        self.assertEqual(kinds(status.decide(today(skipped=True, trade=False), at(8, 58))), ("NOTHING", "no_trade"))
        self.assertEqual(kinds(status.decide(today(), at(6, 30))), ("NOTHING", "pending"))
        self.assertEqual(kinds(status.decide({"date": "2026-10-21", "status": "closed"}, at(9, 0))), ("NOTHING", "closed"))
        for h, m in ((6, 30), (8, 58), (10, 0), (14, 50), (16, 0)):
            self.assertIn(status.decide(today(st="open"), at(h, m))["state"], ("CALL", "PUT", "STAY", "NOTHING"))

    def test_closed_reports_the_trade(self):
        rec = [{"d": "2026-10-22", "open": 22687.75, "close": 22600.0}]
        s = status.decide(today(st="closed", recent=rec), at(15, 50))
        self.assertEqual((s["state"], s["kind"]), ("NOTHING", "closed"))
        self.assertIn("won", s["headline"])


class Alerts(unittest.TestCase):
    def run_at(self, d, prev, now):
        with tempfile.TemporaryDirectory() as dd:
            json.dump(d, open(os.path.join(dd, "today-nifty.json"), "w"))
            if prev:
                json.dump(prev, open(os.path.join(dd, "status.json"), "w"))
            with mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), mock.patch.object(status, "notify") as n:
                out = status.main(dd, now)
            return out, n.call_count

    def test_alert_only_on_change(self):
        s1, n1 = self.run_at(today(), None, at(6, 30))               # NOTHING (pending): quiet
        s2, n2 = self.run_at(today(), s1, at(8, 58))                 # -> PUT: alert
        s3, n3 = self.run_at(today(st="open"), s2, at(9, 50))        # -> STAY: alert
        s4, n4 = self.run_at(today(st="open"), s3, at(11, 5))        # still STAY: no alert
        s5, n5 = self.run_at(today(st="open"), s4, at(14, 50))       # -> NOTHING (exit): alert
        self.assertEqual((n1, n2, n3, n4, n5), (0, 1, 1, 0, 1))
        self.assertEqual(s4["since"], s3["since"])

    def test_no_trade_morning_still_alerts(self):
        s1, _ = self.run_at(today(trade=False), None, at(6, 30))     # pending
        _, n = self.run_at(today(trade=False), s1, at(8, 58))         # NOTHING -> NOTHING, but now a real "no trade"
        self.assertEqual(n, 1)

    def test_quiet_close_after_no_trade(self):
        s1, _ = self.run_at(today(trade=False), None, at(8, 58))
        _, n = self.run_at(today(trade=False, st="closed"), s1, at(15, 50))
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
