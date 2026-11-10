"""The * leans held longer: forward returns over a hold, and the closing-auction cut (no network)."""
import os
import sys
import unittest
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import star_hold_study as sh  # noqa: E402


def day(d, closes, pred=1.0, star=True):
    c = np.array(closes, float)
    return pd.DataFrame({"d": d, "k": range(1, len(c)), "price": c[:-1], "y": c[1:] / c[:-1] - 1,
                         "pred": pred, "star": star, "year": d.year})


class Forward(unittest.TestCase):

    def test_holds_end_inside_the_day(self):
        t = day(date(2024, 1, 2), [100, 101, 103, 102, 106])
        r3, n3 = sh.forward(t, 3)
        self.assertAlmostEqual(r3.iloc[0], 102 / 100 - 1)            # 3 candles on from the first row's close
        self.assertAlmostEqual(r3.iloc[1], 106 / 101 - 1)
        self.assertTrue(np.isnan(r3.iloc[2]))                         # would run past the day
        end, n = sh.forward(t, None)
        self.assertAlmostEqual(end.iloc[1], 106 / 101 - 1)
        self.assertEqual(list(n), [4, 3, 2, 1])

    def test_days_do_not_mix_and_pricing(self):
        t = pd.concat([day(date(2024, 1, 2), [100, 110]), day(date(2024, 1, 3), [200, 190], pred=-1.0)])
        r, n = sh.forward(t, 1)
        self.assertEqual([round(x, 3) for x in r], [0.1, -0.05])
        s = sh.summary(t, r, n, 0.5, -0.1)
        self.assertEqual(s["right"], 1.0)                               # up lean up, down lean down
        self.assertEqual(s["pts"], round(0.5 * 10 - 0.1 - 1.85, 2))     # both moves are 10 points the right way

    def test_no_1515_lean_after_the_closing_auction(self):
        closes = list(range(100, 138))                                  # 37 rows: k = 1 ... 37
        t = pd.concat([day(date(2026, 7, 31), closes), day(date(2026, 8, 3), closes)])
        out = sh.run(t, 0.5, 0.0)["H1 10 minutes"]
        self.assertEqual(out["trades"], 37 + 34)                        # from 3 Aug rows 35-37 are dropped


if __name__ == "__main__":
    unittest.main()
