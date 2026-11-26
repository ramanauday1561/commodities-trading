import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import orb_study as orb  # noqa: E402


def day(bars):
    """5-minute candles from 09:15: [(open, high, low, close), ...]."""
    t = pd.date_range("2026-11-26 09:15", periods=len(bars), freq="5min")
    return pd.DataFrame(bars, columns=["Open", "High", "Low", "Close"], index=t)


RANGE = [(100, 110, 90, 105)] * 3                             # range 90-110, middle 100


class OrbTest(unittest.TestCase):
    def test_breakout_up_hits_1r_target(self):
        g = day(RANGE + [(105, 112, 104, 111), (112, 113, 111, 112), (112, 125, 111, 124)])
        tr = orb.orb_trade(g, "1R")
        self.assertEqual((tr["side"], tr["entry"], tr["why"]), (1, 112.0, "target"))
        self.assertEqual(tr["exit"], 124.0)                    # entry 112 + risk 12 (112 - middle 100)
        self.assertEqual(tr["in_t"].strftime("%H:%M"), "09:35")

    def test_stop_first_when_both_in_one_candle(self):
        g = day(RANGE + [(105, 112, 104, 111), (112, 130, 95, 112)])
        tr = orb.orb_trade(g, "1R")
        self.assertEqual((tr["why"], tr["exit"]), ("stop", 100.0))

    def test_breakdown_put_and_time_exit(self):
        bars = RANGE + [(95, 96, 85, 86)] + [(86, 87, 84, 85)] * 80
        tr = orb.orb_trade(day(bars), "stop_only")
        self.assertEqual((tr["side"], tr["why"]), (-1, "time"))
        self.assertEqual(tr["out_t"].strftime("%H:%M"), "15:10")

    def test_no_breakout_no_trade(self):
        self.assertIsNone(orb.orb_trade(day(RANGE + [(100, 108, 92, 101)] * 70), "1R"))

    def test_option_rs(self):
        tr = {"side": 1, "entry": 100.0, "exit": 110.0, "in_t": pd.Timestamp("2026-11-26 09:35"),
              "out_t": pd.Timestamp("2026-11-26 09:40")}
        self.assertAlmostEqual(orb.option_rs(tr, 0.5, 0.0), (5 - 1.85) * 65)


if __name__ == "__main__":
    unittest.main()
