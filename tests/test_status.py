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
        self.assertEqual(status.decide(today(direction="up"), at(10, 0))["state"], "CALL")
        self.assertEqual(status.decide(today(st="open"), at(14, 50))["state"], "EXIT")

    def test_no_trade_results_and_early(self):
        self.assertEqual(status.decide(today(trade=False), at(8, 58))["state"], "WAIT")
        self.assertEqual(status.decide(today(skipped=True, trade=False), at(8, 58))["state"], "WAIT")
        self.assertEqual(status.decide(today(), at(6, 30))["state"], "PENDING")
        self.assertEqual(status.decide({"date": "2026-10-21", "status": "closed"}, at(9, 0))["state"], "CLOSED")

    def test_closed_reports_the_trade(self):
        rec = [{"d": "2026-10-22", "open": 22687.75, "close": 22600.0}]
        s = status.decide(today(st="closed", recent=rec), at(15, 50))
        self.assertEqual(s["state"], "CLOSED")
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
        s1, n1 = self.run_at(today(), None, at(6, 30))               # PENDING: quiet
        s2, n2 = self.run_at(today(), s1, at(8, 58))                 # -> PUT: alert
        s3, n3 = self.run_at(today(st="open"), s2, at(10, 0))        # still PUT: no alert
        s4, n4 = self.run_at(today(st="open"), s3, at(14, 50))       # -> EXIT: alert
        self.assertEqual((n1, n2, n3, n4), (0, 1, 0, 1))
        self.assertEqual(s3["since"], s2["since"])

    def test_quiet_close_after_no_trade(self):
        s1, _ = self.run_at(today(trade=False), None, at(8, 58))
        _, n = self.run_at(today(trade=False, st="closed"), s1, at(15, 50))
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
