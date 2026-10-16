"""From-open study helpers: expiry calendar and trade scoring (no network)."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import open_study as os_  # noqa: E402


class Expiry(unittest.TestCase):
    def test_thursday_then_tuesday_and_holidays(self):
        days = pd.bdate_range("2025-08-18", "2025-09-12")
        days = days[days != pd.Timestamp("2025-08-28")]          # a Thursday holiday: expiry moves to Wednesday
        weekly, monthly = os_.expiry_flags(days)
        exp = [d.strftime("%Y-%m-%d") for d in weekly[weekly > 0].index]
        self.assertEqual(exp, ["2025-08-21", "2025-08-27", "2025-09-02", "2025-09-09"])
        self.assertEqual([d.strftime("%Y-%m-%d") for d in monthly[monthly > 0].index], ["2025-08-27", "2025-09-09"])


class Trades(unittest.TestCase):
    def test_costs_and_halves(self):
        side = np.array([1, -1, 0, 1])
        ret = np.array([0.01, 0.01, 0.05, -0.002])
        r = os_.trades(side, ret)
        self.assertEqual(r["trades"], 3)
        self.assertAlmostEqual(r["avg_pct"], round((1 - 1 - 0.2) / 3 - os_.COST_PCT, 3))
        self.assertEqual(r["win_rate"], round(1 / 3, 3))

    def test_levels_use_only_earlier_days(self):
        pred = np.r_[np.linspace(0.1, 1, 30), [5.0]]
        ret = np.r_[np.zeros(30), [0.01]]
        out = os_.by_level(pred, ret, np.ones(31, bool))
        # rising confidence: every day from day 20 beats all earlier days, so it is "top 10%" by the earlier-days
        # cut-off even though later days are higher (a cut-off that looked ahead would take only the last 3)
        self.assertEqual(out["top10"]["trades"], 11)
        self.assertEqual(out["all"]["trades"], 11)             # tiers start after 20 days of history


if __name__ == "__main__":
    unittest.main()
