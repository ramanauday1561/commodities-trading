import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import star_grace_study as sg  # noqa: E402


def rows(lows):
    """One day's 5-minute PUT candles for strike 25600, opening at 100 each candle."""
    out = []
    for i, low in enumerate(lows):
        m = 35 + 5 * i
        t = f"2026-11-25 {9 + m // 60:02d}:{m % 60:02d}"
        out.append({"datetime": t, "expiry": "2026-12-01", "strike": "25600.0", "type": "PE",
                    "open": "100", "high": "110", "low": str(low), "close": "105"})
    return out


class StarGraceTest(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(sg.levels(3, "10%"), [0.10, 0.10, 0.10])
        self.assertEqual(sg.levels(3, "G5"), [None, 0.10, 0.10])
        self.assertEqual(sg.levels(3, "G10c25"), [0.25, 0.25, 0.10])

    def test_grace_skips_an_early_dip(self):
        r = rows([88, 100, 100, 100, 100, 100])                 # -12% in the first candle only
        now = sg.real_pick(r, "2026-11-25", "09:35", "down", 25600, "10%")
        grace = sg.real_pick(r, "2026-11-25", "09:35", "down", 25600, "G5")
        self.assertEqual(now["rs"], round(-10 * 65 - 120))     # sold at the 10% stop
        self.assertEqual(grace["rs"], round(5 * 65 - 120))     # held to the close at 105

    def test_guard_stop_in_the_grace(self):
        r = rows([70, 100, 100, 100, 100, 100])                 # -30% in the first candle
        self.assertEqual(sg.real_pick(r, "2026-11-25", "09:35", "down", 25600, "G5c25")["rs"], round(-25 * 65 - 120))

    def test_otm_strike_and_missing(self):
        r = rows([100] * 6)
        self.assertIsNotNone(sg.real_pick(r, "2026-11-25", "09:35", "down", 25700, "10%", otm=2))
        self.assertIsNone(sg.real_pick(r, "2026-11-25", "09:35", "down", 25600, "10%", otm=2))

    def test_path_pick_grace(self):
        w = pd.DataFrame({"Open": [100.0, 100.0], "High": [101.0, 101.0], "Low": [80.0, 99.0], "Close": [100.0, 110.0]})
        # CALL, b 1, a 0, premium 100: a -20 dip in candle 1 stops 10% but not the grace rule
        self.assertEqual(sg.path_pick(100.0, 1, w, 100.0, 1.0, 0.0, [0.10, 0.10]), -10.0)
        self.assertEqual(sg.path_pick(100.0, 1, w, 100.0, 1.0, 0.0, [None, 0.10]), 10.0)


if __name__ == "__main__":
    unittest.main()
