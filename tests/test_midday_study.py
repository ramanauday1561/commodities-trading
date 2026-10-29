"""Midday recovery rule: which days qualify and what the trade earns (no network)."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import midday_study as ms  # noqa: E402


def day(d, closes):
    t = pd.date_range(f"{d} 09:15", periods=len(closes), freq="5min")
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c}, index=t)


class Midday(unittest.TestCase):
    def setUp(self):
        dip = [10000.0] * 6 + [9920.0] * 12 + [9990.0] * 25 + list(np.linspace(9990, 10040, 32))   # -0.8%, back by 13:00
        self.days = {pd.Timestamp("2026-10-27").date(): day("2026-10-27", [10000.0] * 75),
                     pd.Timestamp("2026-10-28").date(): day("2026-10-28", dip)}

    def test_the_28_oct_shape_is_a_call_and_earns_the_afternoon(self):
        st = ms.setups(self.days)
        d = pd.Timestamp("2026-10-28").date()
        self.assertEqual(ms.sides(st, "call"), {d: 1})
        self.assertEqual(ms.sides(st, "put"), {})
        r = ms.trade(self.days[d], 1, 0.3)
        self.assertGreater(r, 0)

    def test_the_stop(self):
        g = day("2026-10-28", [10000.0] * 49 + [9950.0] * 26)                 # 13:00 = 10000, then -0.5%
        self.assertAlmostEqual(ms.trade(g, 1, 0.3), -0.3 - ms.COST)
        self.assertAlmostEqual(ms.trade(g, 1, None), (9950 / 10000 - 1) * 100 - ms.COST)


if __name__ == "__main__":
    unittest.main()
