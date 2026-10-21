"""Hourly chart candles (no network)."""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import hourly  # noqa: E402


class Rows(unittest.TestCase):
    def test_times_read_as_ist_and_candles_are_consistent(self):
        idx = pd.DatetimeIndex(["2026-10-21 03:45"], tz="UTC")                # the 09:15 IST bar
        raw = pd.DataFrame({"Open": [23016.0], "High": [23000.0], "Low": [22990.0], "Close": [23050.123]})
        r = hourly.to_rows(idx, raw)[0]
        shown = pd.Timestamp(r["time"], unit="s")                             # the chart treats the number as UTC
        self.assertEqual(shown.strftime("%H:%M"), "09:15")
        self.assertEqual((r["high"], r["low"], r["close"]), (23050.12, 22990.0, 23050.12))


if __name__ == "__main__":
    unittest.main()
