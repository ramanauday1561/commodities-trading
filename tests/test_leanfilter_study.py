"""leanfilter_study.py: the option pricing from saved Kite quotes, the trend measure and the filters (no network)."""
import csv
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import leanfilter_study as lf  # noqa: E402

FIELDS = ["at", "tradingsymbol", "expiry", "strike", "type", "ltp", "spot"]


def write_day(d, day, runs):
    os.makedirs(os.path.join(d, "snapshots"), exist_ok=True)
    with open(os.path.join(d, "snapshots", f"{day}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for at, spot, ce, pe in runs:
            k = round(spot / 50) * 50
            for typ, p in (("CE", ce), ("PE", pe)):
                w.writerow({"at": at, "tradingsymbol": "X", "expiry": "2026-11-17", "strike": f"{k}.0", "type": typ, "ltp": p, "spot": spot})
                w.writerow({"at": at, "tradingsymbol": "X", "expiry": day, "strike": f"{k}.0", "type": typ, "ltp": 1, "spot": spot})


class Pricing(unittest.TestCase):
    def test_recovers_share_and_decay(self):
        """Options built to move 0.6 x NIFTY on their side and lose 0.5 a run: the fit finds both."""
        with tempfile.TemporaryDirectory() as d:
            rng = np.random.default_rng(1)
            spot, ce, pe, runs = 24500.0, 150.0, 140.0, []
            for i in range(40):
                h, m = divmod(9 * 60 + 25 + 10 * i, 60)
                runs.append((f"{h:02d}:{m:02d}", spot, round(ce, 2), round(pe, 2)))
                dn = float(rng.normal(0, 12))
                spot, ce, pe = spot + dn, ce + 0.6 * dn - 0.5, pe - 0.6 * dn - 0.5
            write_day(d, "2026-11-10", runs)
            c = lf.calibrate(d)
        self.assertGreater(c["pairs"], 50)
        self.assertAlmostEqual(c["b"], 0.6, delta=0.02)
        self.assertAlmostEqual(c["a"], -0.5, delta=0.1)
        self.assertEqual(c["by_day"]["2026-11-10"]["days_to_expiry"], 7)       # the expiring-today chain is skipped

    def test_late_run_is_no_pair_and_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            write_day(d, "2026-11-10", [("09:25", 24500, 100, 100), ("09:45", 24510, 106, 95), ("09:55", 24520, 112, 90)])
            self.assertEqual(lf.calibrate(d)["pairs"], 2)                        # 09:25 -> 09:45 is 20 minutes: left out
            self.assertEqual(lf.calibrate(os.path.join(d, "none"))["pairs"], 0)


def day_rows(closes, opn, d="2026-11-10", year=2026):
    """rows() as nextcandle_study makes them, for one day (k from 1)."""
    out = []
    for k in range(1, len(closes)):
        out.append({"d": d, "k": k, "year": year, "price": closes[k], "r1": closes[k] / closes[k - 1] - 1,
                    "since_open": closes[k] / opn - 1})
    return pd.DataFrame(out)


class Trend(unittest.TestCase):
    def test_straight_day_is_1_and_choppy_day_is_low(self):
        up = lf.trend_inputs(day_rows([101, 102, 103, 104], 100))
        self.assertTrue(np.allclose(up["er"], 1.0))
        chop = lf.trend_inputs(day_rows([101, 100, 101, 100, 101], 100))
        l1, l2 = np.log(101 / 100), np.log(101 / 100)
        self.assertAlmostEqual(chop["er"].iloc[-1], l1 / (5 * l2), places=6)
        self.assertLess(chop["er"].iloc[-1], 0.25)

    def test_each_day_starts_again(self):
        df = pd.concat([day_rows([101, 102, 103], 100, "2026-11-09"), day_rows([99, 100, 99], 100, "2026-11-10")], ignore_index=True)
        t = lf.trend_inputs(df)
        self.assertTrue(np.allclose(t[t["d"] == "2026-11-09"]["er"], 1.0))
        self.assertLess(t[t["d"] == "2026-11-10"]["er"].iloc[-1], 0.5)


class Filters(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({"pred": [1.0, -1.0, 1.0, -1.0], "star": [True, False, True, False], "size_pts": [30, 10, 20, 12],
                             "typical_pts": [20, 20, 20, 10], "k": [3, 3, 1, 5], "er": [0.6, 0.6, 0.9, 0.2],
                             "since_open": [0.01, 0.01, 0.01, -0.01], "y": [0.001, -0.002, 0.0, 0.001],
                             "price": [25000.0] * 4, "year": [2017, 2018, 2022, 2026]})

    def test_masks(self):
        f = lf.filters(self.frame())
        self.assertEqual(list(f["F1 star"]), [True, False, True, False])
        self.assertEqual(list(f["F2 big (size >= 1.2x usual)"]), [True, False, False, True])
        # with the day (row 2 is against it), late enough (row 3 is k=1) and trending (row 4 is choppy)
        self.assertEqual(list(f["F3 trend (with the day, er >= 0.4)"]), [True, False, False, False])

    def test_summary_prices_both_ways(self):
        t = self.frame()
        r = lf.summary(t, np.ones(4, bool), 0.5, 0.0)
        self.assertAlmostEqual(r["pts"], np.mean([0.5 * 25 - 1.85, 0.5 * 50 - 1.85, -1.85, 0.5 * -25 - 1.85]), places=2)
        r2 = lf.summary(t, np.ones(4, bool), 0.6, -0.5)
        self.assertLess(r2["pts"], r["pts"] + 0.1 * 12.5 + 0.01)
        self.assertEqual(r["years_up"], "2/4")

    def test_pass_rule(self):
        good = {"trades": 400, "pts": 0.3, "halves": [0.2, 0.4], "since_2022": 0.1, "years_up": "7/10"}
        self.assertTrue(lf.passes(good))
        for bad in ({"trades": 200}, {"years_up": "6/10"}, {"halves": [-0.1, 0.4]}, {"since_2022": -0.1}, {"pts": -0.01}):
            self.assertFalse(lf.passes({**good, **bad}))


if __name__ == "__main__":
    unittest.main()
