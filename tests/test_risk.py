"""Volatility-aware ranges and big-move scoring."""
import math
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from blend import blend_forecast  # noqa: E402

try:
    import gbm  # noqa: E402
except ImportError:          # lightgbm not installed in the test job
    gbm = None


class Ranges(unittest.TestCase):
    def fit(self):
        return {"weights": {"a": 1.0}, "cal": [-0.01, 0.01], "platt": {"blend": {"a": 0.0, "b": 1.0, "sd": 0.01}}}

    def models(self):
        return {"a": {"forecast": [{"close": 101.0, "high": 102.0, "low": 100.0}, {"close": 102.0, "high": 103.0, "low": 101.0}]}}

    def test_half_widths_set_the_blend_range(self):
        days = pd.bdate_range("2026-10-14", periods=2)
        out = blend_forecast(self.models(), self.fit(), days, 100.0, 0.01, half_widths=[0.02, 0.03])
        self.assertAlmostEqual(out[0]["cal_p10"], round(101 * math.exp(-0.02), 2))
        self.assertAlmostEqual(out[1]["cal_p90"], round(102 * math.exp(0.03), 2))

    def test_fallback_uses_past_errors(self):
        days = pd.bdate_range("2026-10-14", periods=2)
        out = blend_forecast(self.models(), self.fit(), days, 100.0, 0.01)
        self.assertAlmostEqual(out[0]["cal_p10"], round(101 * 0.99, 2))


@unittest.skipIf(gbm is None, "lightgbm not installed")
class BigMoves(unittest.TestCase):
    def test_auc(self):
        self.assertEqual(gbm.auc([0.9, 0.8, 0.1, 0.2], [1, 1, 0, 0]), 1.0)
        self.assertEqual(gbm.auc([0.1, 0.2, 0.9, 0.8], [1, 1, 0, 0]), 0.0)
        self.assertIsNone(gbm.auc([0.5, 0.5], [0, 0]))

    def test_risk_tracks_volatility_and_range_widens(self):
        rng = np.random.default_rng(0)
        n = 1400
        vol = np.where((np.arange(n) // 100) % 2, 0.02, 0.005)          # alternating calm and stormy spells
        c = 100 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol))
        idx = pd.bdate_range("2020-01-01", periods=n)
        full = pd.DataFrame({"open": c, "high": c * (1 + vol), "low": c * (1 - vol), "close": c, "volume": 0.0}, index=idx)
        stormy = full.iloc[:1350]                                         # ends inside a stormy spell (1300-1399)
        future = pd.bdate_range(idx[1349] + pd.Timedelta(days=1), periods=2)
        res = gbm.run_gbm(stormy, future, float(c[1349]), list(range(900, 1340, 4)), None, 1.5)
        self.assertGreater(res["risk"]["p"], res["risk"]["base_rate"])
        self.assertGreater(res["risk"]["backtest"]["skill"], 0)
        calm = full.iloc[:1250]                                           # ends inside a calm spell (1200-1299)
        res2 = gbm.run_gbm(calm, future, float(c[1249]), list(range(900, 1240, 4)), None, 1.5)
        self.assertGreater(res["half_widths"][0], 2 * res2["half_widths"][0])


if __name__ == "__main__":
    unittest.main()
