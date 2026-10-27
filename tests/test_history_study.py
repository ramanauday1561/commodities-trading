"""History study: the trade path on 5-minute candles and NIFTY's weekly expiry days (no network)."""
import os
import sys
import unittest
from datetime import date, time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import history_study as hs  # noqa: E402


def day(closes):
    t = pd.date_range("2026-10-27 09:15", periods=len(closes), freq="5min")
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c + 0.05, "Low": c - 0.05, "Close": c}, index=t)


class Path(unittest.TestCase):
    def test_stop_exit_time_and_close(self):
        g = day([100.0] * 10 + [99.0] * 65)                       # falls 1% at 10:05
        self.assertAlmostEqual(hs.path(g, 1), -0.5 - hs.COST)       # the live 0.5% stop
        self.assertAlmostEqual(hs.path(g, -1), 1.0 - hs.COST)       # short: held to the close
        self.assertAlmostEqual(hs.path(g, 1, stop=None, exit_at=time(10, 0)), -hs.COST)

    def test_trailing_stop_keeps_part_of_a_gain(self):
        g = day(list(np.linspace(100, 101, 30)) + [100.0] * 45)     # up 1%, then all of it back
        self.assertGreater(hs.path(g, 1, trail=0.5), 0.3)
        self.assertAlmostEqual(hs.path(g, 1, breakeven=0.5), -hs.COST)


class Expiry(unittest.TestCase):
    def test_thursday_then_tuesday_and_holidays(self):
        d = list(pd.bdate_range("2025-08-18", "2025-09-12").date)
        d.remove(date(2025, 8, 21))                                # a Thursday holiday: the expiry moves to Wednesday
        self.assertEqual(sorted(hs.expiries(d)), [date(2025, 8, 20), date(2025, 8, 28), date(2025, 9, 2), date(2025, 9, 9)])


if __name__ == "__main__":
    unittest.main()
