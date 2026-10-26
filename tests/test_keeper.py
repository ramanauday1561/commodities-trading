"""The 09:08 check that the 08:57 call reached the Status page (no network)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import keeper  # noqa: E402


class Watchdog(unittest.TestCase):
    def test_signal_ok(self):
        self.assertTrue(keeper.signal_ok({"date": "2026-10-27", "kind": "no_trade"}, "2026-10-27"))
        self.assertTrue(keeper.signal_ok({"date": "2026-10-27", "kind": "put"}, "2026-10-27"))
        self.assertFalse(keeper.signal_ok({"date": "2026-10-27", "kind": "pending"}, "2026-10-27"))
        self.assertFalse(keeper.signal_ok({"date": "2026-10-26", "kind": "no_trade"}, "2026-10-27"))
        self.assertFalse(keeper.signal_ok(None, "2026-10-27"))

    def run_watchdog(self, statuses):
        today = keeper.datetime.now(keeper.IST).date().isoformat()
        seq = [dict(s, date=today) if s else None for s in statuses]
        with mock.patch.object(keeper, "live_status", side_effect=seq), mock.patch.object(keeper, "dispatch") as d, \
                mock.patch("status.notify", return_value={"telegram": "sent"}) as n, mock.patch.object(keeper.time, "sleep"):
            ok = keeper.watchdog()
        return ok, d.call_count, n.call_args_list

    def test_call_there_nothing_sent(self):
        self.assertEqual(self.run_watchdog([{"kind": "no_trade"}])[:2], (True, 0))

    def test_retry_that_works_sends_no_warning(self):
        ok, retries, warned = self.run_watchdog([{"kind": "pending"}, {"kind": "call"}])
        self.assertEqual((ok, retries, warned), (True, 1, []))

    def test_still_missing_after_the_retry_warns_the_phone(self):
        ok, retries, warned = self.run_watchdog([None, {"kind": "pending"}])
        self.assertEqual((ok, retries), (False, 1))
        self.assertEqual(warned[0].args[0]["kind"], "warning")


if __name__ == "__main__":
    unittest.main()
