"""Selling options from the open, on bhavcopy-like rows (no network)."""
import os
import sys
import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import short_option_study as so  # noqa: E402


def market(days=300, seed=1):
    rng = np.random.default_rng(seed)
    d0 = date(2015, 1, 5)
    dates = [d0 + timedelta(days=k) for k in range(days * 2) if (d0 + timedelta(days=k)).weekday() < 5][:days]
    nd = pd.DataFrame({"open": 10000.0, "close": 10000.0 + rng.normal(0, 60, len(dates))},
                      index=pd.DatetimeIndex([pd.Timestamp(x) for x in dates]))
    rows = []
    for x, (_, r) in zip(dates, nd.iterrows()):
        exp = [x + timedelta(days=(3 - x.weekday()) % 7 + 7 * k) for k in range(2)]
        move = r["close"] - r["open"]
        for e in exp:
            for k in range(9800, 10201, 50):
                for t in ("CE", "PE"):
                    intrinsic_close = max(0.0, (r["close"] - k) if t == "CE" else (k - r["close"]))
                    o = 80.0 if k == 10000 else max(5.0, 80.0 - abs(k - 10000) * 0.3)
                    c = max(1.0, o * 0.92 + (move if t == "CE" else -move) * 0.5) if intrinsic_close == 0 else intrinsic_close + 5
                    rows.append({"d": x, "expiry": e, "strike": float(k), "type": t, "open": o, "high": max(o, c) * 1.1,
                                 "low": min(o, c) * 0.9, "close": c})
    return pd.DataFrame(rows), nd


class Study(unittest.TestCase):

    def test_variants_and_rule(self):
        opt, nd = market()
        rows = so.day_rows(opt, nd)
        self.assertEqual(set(rows["v"]), set("ABCDEF"))
        for v, g in rows.groupby("v"):
            out = so.judge(g)
            self.assertEqual(out["days"], 300)
            self.assertIn("passes", out)
            self.assertGreater(out["median_margin_rs"], 0)
        e = rows[rows["v"] == "E"]
        self.assertTrue((e["margin"] < rows[rows["v"] == "A"]["margin"].median()).all())     # wings cap the margin

    def test_stop(self):
        leg = pd.Series({"open": 100.0, "high": 160.0, "close": 90.0})
        self.assertEqual(so.leg_short(leg), (10.0, False))
        self.assertEqual(so.leg_short(leg, 0.5), (-52.0, True))                               # bought back at 150 + 2
        self.assertEqual(so.leg_short(pd.Series({"open": 100.0, "high": 140.0, "close": 90.0}), 0.5), (10.0, False))


if __name__ == "__main__":
    unittest.main()
