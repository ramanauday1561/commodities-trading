"""Next-candle lean: training on stored candles and the live lean after the last finished candle (no network)."""
import os
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import nextcandle as nc  # noqa: E402
import nextcandle_study as ns  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def days(n, bars=75, seed=0, start="2026-06-01"):
    rng = np.random.default_rng(seed)
    out, px = {}, 22000.0
    for d in pd.bdate_range(start, periods=n).date:
        t = pd.date_range(f"{d} 09:15", periods=bars, freq="5min")
        c = px * np.exp(np.cumsum(rng.normal(0, 0.0008, bars)))
        out[d] = pd.DataFrame({"Open": np.r_[px, c[:-1]], "High": c * 1.0004, "Low": c * 0.9996, "Close": c}, index=t)
        px = c[-1]
    return out


class NextCandle(unittest.TestCase):
    def test_live_rows_keep_todays_last_candle(self):
        d = days(3)
        today = sorted(d)[-1]
        d[today] = d[today].iloc[:13]                                           # 09:15 ... 10:15 finished
        df = ns.rows(d, d, d, live=True)
        last = df[df["d"] == today].iloc[-1]
        self.assertEqual(int(last["k"]), 5)                                     # the 10:05 candle; 10:15 is half done
        self.assertTrue(np.isnan(last["y"]))

    def test_train_and_lean(self):
        import lightgbm  # noqa: F401
        tmp = tempfile.mkdtemp()
        hist = days(40, seed=1)
        with unittest.mock.patch("intraday_data.load", side_effect=lambda d, k: hist):
            meta = nc.train("unused", tmp)
        self.assertEqual(meta["record"]["rs_per_lot"], -73)
        live = days(3, seed=2, start="2026-10-27")
        today = sorted(live)[-1]
        live[today] = live[today].iloc[:20]
        out = nc.lean(tmp, datetime.combine(today, datetime.min.time(), IST).replace(hour=11), get=lambda s: live)
        self.assertEqual(out["at"], "10:55")
        self.assertIn(out["lean"], ("up", "down"))
        self.assertIn("lost about Rs73", out["record"]["text"])
        self.assertIsNone(nc.lean(tempfile.mkdtemp(), datetime(2026, 10, 29, 11, tzinfo=IST), get=lambda s: live))


if __name__ == "__main__":
    unittest.main()
