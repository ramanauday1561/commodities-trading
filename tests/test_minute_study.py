"""1-minute inputs for the 30 / 60-minute prediction: features at a candle's end, the join, the pass rule (no network)."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import minute_study as ms  # noqa: E402


def minutes(d, closes):
    t = pd.date_range(f"{d} 09:15", periods=len(closes), freq="1min")
    return pd.DataFrame({"date": t.strftime("%Y-%m-%d %H:%M:%S+05:30"), "open": closes, "high": closes, "low": closes,
                         "close": closes})


class Minute(unittest.TestCase):
    def setUp(self):
        self.d = pd.Timestamp("2026-05-04").date()
        self.n = ms.minute_days(minutes(self.d, [100.0 + 0.1 * i for i in range(375)]))      # a steady rise
        self.b = ms.minute_days(minutes(self.d, [200.0 + 0.4 * i for i in range(375)]))

    def test_inputs_use_only_minutes_before_the_candle_ends(self):
        f = ms.features(self.n, self.b, self.d, 3)                     # candle 09:45-09:55 ends 09:55: 40 minutes
        self.assertAlmostEqual(f["m_r1"], 103.9 / 103.8 - 1)
        self.assertAlmostEqual(f["m_eff30"], 1.0)                       # a straight line
        self.assertEqual(f["m_up10"], 1.0)
        self.assertAlmostEqual(f["m_lead5"], (215.6 / 213.6 - 1) - (103.9 / 103.4 - 1))
        self.assertIsNone(ms.features(self.n, self.b, self.d, 1))      # 09:35: fewer than 31 minutes
        self.assertIsNone(ms.features({}, self.b, self.d, 3))

    def test_the_join_keeps_days_with_minutes(self):
        df = pd.DataFrame({"d": [self.d, self.d, pd.Timestamp("2026-05-05").date()], "k": [3, 1, 3], "y": [0.1, 0.2, 0.3]})
        out = ms.add_minutes(df, self.n, self.b)
        self.assertEqual(len(out), 1)
        self.assertTrue(set(ms.MIN_FEATS) <= set(out.columns))

    def test_pass_rule(self):
        base = {"halves_pts": [-0.5, -0.2]}
        good = {"top_hit": 0.56, "top_pts": 0.4, "halves_pts": [0.3, 0.5], "years_up": "7/10"}
        self.assertTrue(ms.passes(good, base))
        self.assertFalse(ms.passes({**good, "top_hit": 0.54}, base))
        self.assertFalse(ms.passes({**good, "halves_pts": [-0.1, 0.9]}, base))
        self.assertFalse(ms.passes({**good, "years_up": "5/10"}, base))


if __name__ == "__main__":
    unittest.main()
