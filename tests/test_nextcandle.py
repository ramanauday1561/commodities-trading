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
        self.assertEqual(meta["day_record"]["quantiles"]["50"], -3801)
        at = lambda h, m: datetime.combine(today, datetime.min.time(), IST).replace(hour=h, minute=m)
        live[today] = days(3, seed=2, start="2026-10-27")[today].iloc[:72]            # to the 15:10 bar: 15:05 finished
        self.assertEqual(nc.lean(tmp, at(15, 16), get=lambda s: live)["at"], "15:15")
        live[today] = days(3, seed=2, start="2026-10-27")[today].iloc[:74]            # 15:15 finished: next is the stub
        self.assertIsNone(nc.lean(tmp, at(15, 26), get=lambda s: live))
        live[today] = days(3, seed=2, start="2026-10-27")[today].iloc[:20]            # the last full candle is 10:45
        self.assertIsNone(nc.lean(tmp, at(11, 2), get=lambda s: live))               # 7 min into 10:55: stale

    def test_replay_a_day(self):
        import json as js
        hist = days(45, seed=3)
        d = sorted(hist)[-1]
        frames = {"nifty": hist, "banknifty": hist, "vix": hist}
        store = tempfile.mkdtemp()
        os.makedirs(os.path.join(store, "live"))
        js.dump({"candles": [], "leans": [{"at": "10:05", "lean": "up"}]}, open(os.path.join(store, "live", f"{d}.json"), "w"))
        with unittest.mock.patch("intraday_data.load", side_effect=lambda dd, k: frames[k]):
            out = nc.replay(str(d), "unused", store)
        self.assertEqual(out["trained_until"], str(sorted(hist)[-2]))                  # only the days before
        self.assertEqual(out["replay"]["leans"], 35)                                     # 09:35 ... 15:15
        self.assertEqual(out["leans"][0]["at"], "09:35")                                 # as live: 09:25 has no candle before
        self.assertEqual(out["same_lean"].split(" of ")[1], "1")
        self.assertEqual(out["replay"]["rs"], sum(x["rs"] for x in out["leans"]))


if __name__ == "__main__":
    unittest.main()
