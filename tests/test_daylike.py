"""'Days like today': the table from past candles and the lookup for the session (no network)."""
import os
import sys
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import daylike  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def day(d, closes):
    t = pd.date_range(f"{d} 09:15", periods=len(closes), freq="5min")
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c}, index=t)


class Daylike(unittest.TestCase):
    def setUp(self):
        dates = pd.bdate_range("2025-01-01", periods=61).date
        self.days = {dates[0]: day(dates[0], [10000.0] * 75)}
        pc = 10000.0
        for k, d in enumerate(dates[1:]):                       # flat to 13:15, then up 0.5% on 2 of 3 days
            end = pc * (1.005 if k % 3 else 0.995)
            self.days[d] = day(d, [pc] * 49 + list(np.linspace(pc, end, 26)))
            pc = end
        self.tab = daylike.build(self.days)

    def test_table_and_lookup(self):
        self.assertEqual(len(self.tab["dates"]), 60)
        self.assertEqual(self.tab["13:15"]["now"][0], 0.0)
        d = daylike.lookup(self.tab, "13:20", 0.0, -0.01, 0.01)
        self.assertEqual((d["at"], d["days"], d["up"]), ("13:15", 60, 0.67))
        self.assertIn("leans up, untested", daylike.line(d))
        self.assertIsNone(daylike.lookup(self.tab, "09:50", 0.0, 0.0, 0.0))     # before the first checkpoint

    def test_for_today_only_in_the_session(self):
        today = {"status": "open", "preopen": {"prev_close": 10000.0},
                 "intraday": {"price": 10000.0, "low": 9999.0, "high": 10001.0}}
        now = datetime(2026, 10, 28, 13, 20, tzinfo=IST)
        self.assertEqual(daylike.for_today(self.tab, today, now)["days"], 60)
        self.assertIsNone(daylike.for_today(self.tab, {**today, "status": "closed"}, now))
        self.assertIsNone(daylike.for_today(None, today, now))


if __name__ == "__main__":
    unittest.main()
