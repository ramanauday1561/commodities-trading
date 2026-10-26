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


class StopWatcherTest(unittest.TestCase):
    def watcher(self, st, rng):
        today = keeper.datetime.now(keeper.IST).date().isoformat()
        st = dict(st, date=today) if st else None
        return keeper.StopWatcher(status_fn=lambda: st, range_fn=lambda: rng)

    def test_starts_a_run_when_the_stop_is_reached_then_waits_for_the_page(self):
        w = self.watcher({"kind": "hold", "side": "PUT"}, (22524.4, 22650.0, 22500.0))
        with mock.patch.object(keeper, "dispatch") as d:
            self.assertTrue(w.check())
            self.assertFalse(w.check())                    # 10 minutes for that run to update the page
        self.assertEqual(d.call_count, 1)

    def test_nothing_before_the_stop(self):
        w = self.watcher({"kind": "put", "side": "PUT"}, (22524.4, 22600.0, 22400.0))
        with mock.patch.object(keeper, "dispatch") as d:
            self.assertFalse(w.check())
        self.assertEqual(d.call_count, 0)

    def test_stops_watching_on_a_no_trade_day_or_after_the_stop(self):
        for kind in ("no_trade", "stop"):
            w = self.watcher({"kind": kind, "side": "PUT"}, (22524.4, 23000.0, 22000.0))
            with mock.patch.object(keeper, "dispatch") as d:
                self.assertFalse(w.check())
                self.assertTrue(w.done)
            self.assertEqual(d.call_count, 0)


if __name__ == "__main__":
    unittest.main()
