"""The trend-day rule: inputs at 10:15, the trade to 15:15, the stop (no network)."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import trendday_study as t  # noqa: E402


def day(d, closes, start=100.0):
    """A session of 5-minute candles from 09:15 with these closes (75 candles; the rest flat)."""
    closes = list(closes) + [closes[-1]] * (75 - len(closes))
    idx = pd.date_range(f"{d} 09:15", periods=75, freq="5min")
    opens = [start] + closes[:-1]
    return pd.DataFrame({"Open": opens, "High": np.maximum(opens, closes) + 0.01, "Low": np.minimum(opens, closes) - 0.01,
                         "Close": closes}, index=idx)


class Rule(unittest.TestCase):
    def setUp(self):
        a, d = pd.Timestamp("2026-10-28").date(), pd.Timestamp("2026-10-29").date()
        up = [100.0 + 0.05 * k for k in range(12)] + [101.0] * 63                  # +0.55% by the 10:10 candle's close
        self.nifty = {a: day(a, [100.0]), d: day(d, up)}
        self.bank = {a: day(a, [100.0]), d: day(d, up)}
        self.vix = {a: day(a, [15.0], 15.0), d: day(d, [14.5], 15.0)}

    def test_a_strong_morning_with_bank_nifty_and_a_falling_vix_is_a_call(self):
        r = t.days(self.nifty, self.bank, self.vix)[-1]
        self.assertAlmostEqual(r["entry"], 100.55)
        self.assertEqual(t.signal(r), 1)
        self.assertAlmostEqual(t.trade(r, 1), (101.0 / 100.55 - 1) * 100 - t.COST_PCT)

    def test_no_call_when_vix_rises(self):
        d = max(self.vix)
        self.vix[d] = day(d, [15.5], 15.0)
        self.assertEqual(t.signal(t.days(self.nifty, self.bank, self.vix)[-1]), 0)

    def test_the_stop_is_checked_after_the_entry(self):
        r = t.days(self.nifty, self.bank, self.vix)[-1]
        r["lows"] = r["lows"].copy()
        r["lows"][5] = r["entry"] * 0.994                                          # a 0.6% dip after 10:15
        self.assertAlmostEqual(t.trade(r, 1, stop=0.5), -0.5 - t.COST_PCT)


if __name__ == "__main__":
    unittest.main()
