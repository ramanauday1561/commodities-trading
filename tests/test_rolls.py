"""Futures roll detection and back-adjustment (no network)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import rolls  # noqa: E402


def market(n=80, roll_at=60, ratio=0.95, seed=0):
    """Continuous closes on the old contract before `roll_at` and the new one from it; the new contract = old * ratio."""
    days = pd.bdate_range("2026-06-01", periods=n)
    new = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 0.01, n))), index=days)
    cont = pd.concat([new.iloc[:roll_at] / ratio, new.iloc[roll_at:]])
    return cont, new


class Detect(unittest.TestCase):
    def test_finds_the_roll_day_and_ratio(self):
        cont, new = market()
        r = rolls.detect(cont, {"CLZ26.NYM": new, "CLF27.NYM": new * 0.98})
        self.assertEqual(r["date"], cont.index[60].strftime("%Y-%m-%d"))
        self.assertAlmostEqual(r["ratio"], 0.95, places=5)
        self.assertEqual(r["contract"], "CLZ26.NYM")

    def test_wti_20_oct_2026(self):
        days = pd.DatetimeIndex(["2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20"])
        cont = pd.Series([101.9, 102.4, 103.66, 96.09], index=days)          # November contract, then December
        dec = pd.Series([97.6, 97.5, 98.24, 96.10], index=days)
        r = rolls.detect(cont, {"CLZ26.NYM": dec})
        self.assertEqual(r["date"], "2026-10-20")
        self.assertAlmostEqual(r["ratio"], 98.24 / 103.66, places=5)

    def test_no_roll_when_the_series_is_one_contract(self):
        cont, new = market(roll_at=0)
        self.assertIsNone(rolls.detect(cont, {"X": new}))

    def test_nothing_matches_the_latest_close(self):
        cont, new = market()
        self.assertIsNone(rolls.detect(cont, {"X": new * 1.01}))

    def test_live_close_fetched_a_moment_apart(self):
        cont, new = market()
        cont.iloc[-1] *= 1.004                         # the live price moved between the two downloads
        self.assertEqual(rolls.detect(cont, {"X": new})["date"], cont.index[60].strftime("%Y-%m-%d"))

    def test_one_odd_day_is_not_a_roll(self):
        cont, new = market()
        cont.iloc[70] *= 1.01                          # a single bad print after the roll
        self.assertEqual(rolls.detect(cont, {"X": new})["date"], cont.index[60].strftime("%Y-%m-%d"))

    def test_days_missing_from_the_dated_contract_are_skipped(self):
        cont, new = market()
        self.assertEqual(rolls.detect(cont, {"X": new.drop(new.index[[59, 65]])})["date"],
                         cont.index[60].strftime("%Y-%m-%d"))

    def test_an_implausible_jump_is_rejected(self):
        cont, new = market(ratio=0.7)
        self.assertIsNone(rolls.detect(cont, {"X": new}))


class Adjust(unittest.TestCase):
    def test_rolls_compound_backwards(self):
        days = pd.bdate_range("2026-01-01", periods=6)
        df = pd.DataFrame({c: [10.0] * 6 for c in rolls.PRICES} | {"volume": [5.0] * 6}, index=days)
        out = rolls.adjust(df, [{"date": str(days[2].date()), "ratio": 0.5}, {"date": str(days[4].date()), "ratio": 0.9}])
        self.assertEqual(out["close"].round(6).tolist(), [4.5, 4.5, 9.0, 9.0, 10.0, 10.0])
        self.assertEqual(out["volume"].tolist(), [5.0] * 6)
        self.assertEqual(df["close"].tolist(), [10.0] * 6)          # the input is left alone

    def test_roll_outside_the_data_changes_nothing(self):
        days = pd.bdate_range("2026-01-01", periods=3)
        df = pd.DataFrame({c: [1.0, 2.0, 3.0] for c in rolls.PRICES}, index=days)
        out = rolls.adjust(df, [{"date": "2027-01-01", "ratio": 0.5}, {"date": "2025-01-01", "ratio": 0.5}])
        self.assertEqual(out["close"].tolist(), [1.0, 2.0, 3.0])


class Log(unittest.TestCase):
    index = pd.bdate_range("2026-01-01", periods=60)

    def test_same_roll_found_again_is_not_added(self):
        log = [{"date": "2026-01-15", "ratio": 0.98, "contract": "A"}]
        again = {"date": "2026-01-16", "ratio": 0.981, "contract": "A"}
        self.assertEqual(rolls.merge_log(log, again, self.index), log)

    def test_a_new_roll_is_added(self):
        log = [{"date": "2026-01-15", "ratio": 0.98, "contract": "A"}]
        new = {"date": "2026-03-10", "ratio": 1.01, "contract": "B"}
        self.assertEqual([r["date"] for r in rolls.merge_log(log, new, self.index)], ["2026-01-15", "2026-03-10"])

    def test_merge_saves_the_rolls_used(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as store:
            os.makedirs(os.path.join(store, "rolls"))
            json.dump([{"date": "2026-09-23", "ratio": 0.99, "contract": "CLX26.NYM"}],
                      open(os.path.join(store, "rolls", "crude.json"), "w"))
            json.dump({"key": "crude", "rolls": [{"date": "2026-10-20", "ratio": 0.9477, "contract": "CLZ26.NYM"}]},
                      open(os.path.join(data, "crude.json"), "w"))
            json.dump({"key": "nifty", "rolls": []}, open(os.path.join(data, "nifty.json"), "w"))
            rolls.merge(data, store)
            saved = json.load(open(os.path.join(store, "rolls", "crude.json")))
            self.assertEqual([r["date"] for r in saved], ["2026-09-23", "2026-10-20"])
            self.assertFalse(os.path.exists(os.path.join(store, "rolls", "nifty.json")))


class Candidates(unittest.TestCase):
    def test_next_six_months_across_the_year_end(self):
        self.assertEqual(rolls.candidates("CL", "NYM", date(2026, 10, 20)),
                         ["CLV26.NYM", "CLX26.NYM", "CLZ26.NYM", "CLF27.NYM", "CLG27.NYM", "CLH27.NYM"])


if __name__ == "__main__":
    unittest.main()
